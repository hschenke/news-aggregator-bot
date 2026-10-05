"""
Verwaltung von Quellen, Kategorien und Einstellungen (sources.yaml) sowie GitHub- und CDN-Synchronisation.
"""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import Any

import requests
import yaml

from src.filters import normalize_keywords

logger = logging.getLogger(__name__)


PROMPT_KEYS: set[str] = {"custom_main_prompt", "custom_prompt_directives"}


def get_streamlit_app_url(config_path: str = "config/sources.yaml") -> str:
    """Helper delegating to summarizer.get_streamlit_app_url."""
    from src.summarizer import get_streamlit_app_url as _get_url
    return _get_url(config_path)


def get_sources_path(config_path: str = "config/sources.yaml") -> Path:
    """Ermittelt den absoluten Pfad zur sources.yaml-Datei."""
    path = Path(config_path)
    if not path.is_absolute():
        root_path = Path(__file__).resolve().parent.parent / config_path
        if root_path.exists() or not path.exists():
            return root_path
    return path


def get_settings_path(config_path: str = "config/settings.yaml") -> Path:
    """Ermittelt den absoluten Pfad zur settings.yaml-Datei."""
    path = Path(config_path)
    if not path.is_absolute():
        root_path = Path(__file__).resolve().parent.parent / config_path
        if root_path.exists() or not path.exists():
            return root_path
    return path


def get_prompts_path(config_path: str = "config/prompts.yaml") -> Path:
    """Ermittelt den absoluten Pfad zur prompts.yaml-Datei."""
    path = Path(config_path)
    if not path.is_absolute():
        root_path = Path(__file__).resolve().parent.parent / config_path
        if root_path.exists() or not path.exists():
            return root_path
    return path


def get_github_sync_config() -> dict[str, str]:
    """Liest GitHub Sync Konfiguration aus Umgebungsvariablen oder Streamlit Secrets."""
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    repo = os.getenv("GITHUB_REPO", "hschenke/news-aggregator-bot")
    branch = os.getenv("GITHUB_BRANCH", "main")

    if not token and ("STREAMLIT_SERVER_PORT" in os.environ or "streamlit" in sys.modules):
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                if "GITHUB_TOKEN" in st.secrets:
                    token = str(st.secrets["GITHUB_TOKEN"])
                elif "GH_TOKEN" in st.secrets:
                    token = str(st.secrets["GH_TOKEN"])
                if "GITHUB_REPO" in st.secrets:
                    repo = str(st.secrets["GITHUB_REPO"])
                if "GITHUB_BRANCH" in st.secrets:
                    branch = str(st.secrets["GITHUB_BRANCH"])
        except Exception:
            pass

    return {
        "token": (token or "").strip(),
        "repo": (repo or "hschenke/news-aggregator-bot").strip(),
        "branch": (branch or "main").strip(),
    }


def sync_sources_to_github(
    config_dict: dict[str, Any] | None = None,
    config_path: str = "config/sources.yaml",
    commit_message: str = "chore(config): update sources.yaml and RSS feeds via web dashboard",
    include_rss_feeds: bool = True
) -> dict[str, Any]:
    """
    Pusht die aktuelle sources.yaml und alle generierten static/rss/*.xml Feeds
    direkt per GitHub Git Data API (Trees & Commits) in einem einzigen atomaren Commit.
    Falls die Git Data API fehlschlägt, erfolgt ein Fallback über die Contents API.
    """
    gh_cfg = get_github_sync_config()
    token = gh_cfg["token"]
    if not token or token.startswith("your_"):
        return {"success": False, "error": "Kein GITHUB_TOKEN hinterlegt."}

    repo = gh_cfg["repo"]
    branch = gh_cfg["branch"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        if config_dict is not None:
            save_sources(config_dict, config_path=config_path, sync_github=False)

        config_files_to_sync = [
            ("config/sources.yaml", get_sources_path(config_path)),
            ("config/settings.yaml", get_settings_path()),
            ("config/prompts.yaml", get_prompts_path()),
        ]

        # 1. Versuch: Atomarer Multi-File-Push via Git Data API (Trees & Commits)
        if include_rss_feeds:
            try:
                ref_res = requests.get(f"https://api.github.com/repos/{repo}/git/ref/heads/{branch}", headers=headers, timeout=8)
                if ref_res.status_code == 200:
                    latest_commit_sha = ref_res.json().get("object", {}).get("sha")
                    commit_info_res = requests.get(f"https://api.github.com/repos/{repo}/git/commits/{latest_commit_sha}", headers=headers, timeout=8)
                    base_tree_sha = commit_info_res.json().get("tree", {}).get("sha")

                    tree_elements: list[dict[str, Any]] = []
                    for rel_p, abs_p in config_files_to_sync:
                        if abs_p.exists():
                            tree_elements.append({
                                "path": rel_p,
                                "mode": "100644",
                                "type": "blob",
                                "content": abs_p.read_text(encoding="utf-8")
                            })

                    from src.rss_generator import get_static_rss_dir
                    rss_dir = get_static_rss_dir()
                    for xml_file in rss_dir.rglob("*.xml"):
                        rel_path = xml_file.relative_to(rss_dir.parent.parent).as_posix()
                        try:
                            tree_elements.append({
                                "path": rel_path,
                                "mode": "100644",
                                "type": "blob",
                                "content": xml_file.read_text(encoding="utf-8")
                            })
                        except Exception:
                            pass

                    tree_res = requests.post(
                        f"https://api.github.com/repos/{repo}/git/trees",
                        headers=headers,
                        json={"base_tree": base_tree_sha, "tree": tree_elements},
                        timeout=12
                    )
                    if tree_res.status_code in [200, 201]:
                        new_tree_sha = tree_res.json().get("sha")

                        new_commit_res = requests.post(
                            f"https://api.github.com/repos/{repo}/git/commits",
                            headers=headers,
                            json={
                                "message": commit_message,
                                "tree": new_tree_sha,
                                "parents": [latest_commit_sha]
                            },
                            timeout=10
                        )
                        if new_commit_res.status_code in [200, 201]:
                            new_commit_sha = new_commit_res.json().get("sha")

                            update_ref_res = requests.patch(
                                f"https://api.github.com/repos/{repo}/git/refs/heads/{branch}",
                                headers=headers,
                                json={"sha": new_commit_sha, "force": False},
                                timeout=10
                            )
                            if update_ref_res.status_code == 200:
                                purge_res = purge_jsdelivr_cache()
                                return {
                                    "success": True,
                                    "commit_sha": new_commit_sha,
                                    "method": "git_data_api_multi_file",
                                    "files_count": len(tree_elements),
                                    "jsdelivr_purge": purge_res,
                                }
            except Exception as e_tree:
                logger.warning("Git Data API Multi-File-Push fehlgeschlagen, wechsle zu Contents API Fallback: %s", e_tree)

        # 2. Fallback: Konfigurationsdateien via Contents API aktualisieren
        import base64
        last_sha = None
        for rel_p, abs_p in config_files_to_sync:
            if not abs_p.exists():
                continue
            get_res = requests.get(
                f"https://api.github.com/repos/{repo}/contents/{rel_p}?ref={branch}",
                headers=headers,
                timeout=8
            )
            current_sha = get_res.json().get("sha") if get_res.status_code == 200 else None
            content_b64 = base64.b64encode(abs_p.read_bytes()).decode("utf-8")
            payload: dict[str, Any] = {
                "message": commit_message,
                "content": content_b64,
                "branch": branch,
            }
            if current_sha:
                payload["sha"] = current_sha

            put_res = requests.put(
                f"https://api.github.com/repos/{repo}/contents/{rel_p}",
                headers=headers,
                json=payload,
                timeout=10
            )
            if put_res.status_code in [200, 201]:
                last_sha = put_res.json().get("commit", {}).get("sha")

        if last_sha:
            purge_res = purge_jsdelivr_cache()
            return {"success": True, "commit_sha": last_sha, "method": "contents_api", "jsdelivr_purge": purge_res}
        return {"success": False, "error": "Fehler beim Aktualisieren der Konfigurationsdateien via Contents API"}

    except Exception as exc:
        return {"success": False, "error": str(exc)}


def trigger_rss_update_workflow() -> dict[str, Any]:
    """Triggert den GitHub Actions Workflow zur vollautomatischen RSS-Feed-Generierung via repository_dispatch."""
    gh_cfg = get_github_sync_config()
    token = gh_cfg["token"]
    if not token or token.startswith("your_"):
        return {"success": False, "error": "Kein GITHUB_TOKEN hinterlegt."}

    repo = gh_cfg["repo"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "event_type": "update-rss-feeds",
        "client_payload": {"triggered_by": "streamlit_dashboard"}
    }
    try:
        res = requests.post(
            f"https://api.github.com/repos/{repo}/dispatches",
            headers=headers,
            json=payload,
            timeout=10
        )
        if res.status_code in [200, 204]:
            return {"success": True}
        return {"success": False, "error": f"Status {res.status_code}: {res.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def purge_jsdelivr_cache(
    paths: list[str] | None = None,
    repo: str | None = None,
    branch: str | None = None,
    timeout: int = 8,
) -> dict[str, Any]:
    """Leert den weltweiten Edge-Cache des jsDelivr CDNs für geänderte RSS-Dateien.

    Unterstützt sowohl gezielte Pfade als auch alle Dateien im static/rss/ Verzeichnis.
    Führt einen Batch-Purge via POST https://purge.jsdelivr.net/ durch sowie eine synchrone
    Invalidierung für die primären Feeds (briefing.xml, all.xml).
    """
    gh_cfg = get_github_sync_config()
    target_repo = repo or gh_cfg.get("repo") or "hschenke/news-aggregator-bot"
    target_branch = branch or gh_cfg.get("branch") or "main"

    formatted_paths: list[str] = []
    if paths:
        for p in paths:
            clean = p.lstrip("/").replace("\\", "/")
            if not clean.startswith("gh/"):
                formatted_paths.append(f"/gh/{target_repo}@{target_branch}/{clean}")
            else:
                formatted_paths.append(f"/{clean}")
    else:
        try:
            from src.rss_generator import get_static_rss_dir
            rss_dir = get_static_rss_dir()
            root_dir = rss_dir.parent.parent
            for xml_file in rss_dir.rglob("*.xml"):
                try:
                    rel = xml_file.relative_to(root_dir).as_posix()
                    formatted_paths.append(f"/gh/{target_repo}@{target_branch}/{rel}")
                except Exception:
                    pass
        except Exception as e_find:
            logger.debug("Konnte lokale RSS-Pfade für Purge nicht automatisch ermitteln: %s", e_find)

    if not formatted_paths:
        formatted_paths = [
            f"/gh/{target_repo}@{target_branch}/static/rss/briefing.xml",
            f"/gh/{target_repo}@{target_branch}/static/rss/all.xml",
        ]

    results: dict[str, Any] = {"success": True, "purged_count": len(formatted_paths), "errors": []}

    # 1. Batch-Purge via POST https://purge.jsdelivr.net/
    try:
        post_resp = requests.post(
            "https://purge.jsdelivr.net/",
            json={"path": formatted_paths},
            headers={"Content-Type": "application/json", "User-Agent": "NewsBot-CDN-Purge/1.0"},
            timeout=timeout,
        )
        if post_resp.status_code in [200, 201, 202]:
            logger.info("⚡ [CDN] jsDelivr Batch-Purge erfolgreich angestoßen (%d Pfade, Status %d).", len(formatted_paths), post_resp.status_code)
        else:
            logger.warning("jsDelivr Batch-Purge antwortete mit Status %d: %s", post_resp.status_code, post_resp.text)
            results["errors"].append(f"Status {post_resp.status_code}")
    except Exception as e_post:
        logger.warning("jsDelivr Batch-Purge fehlgeschlagen: %s", e_post)
        results["errors"].append(str(e_post))

    # 2. Sofortige synchrone Edge-Invalidierung für briefing.xml & all.xml
    for key_file in ["briefing.xml", "all.xml"]:
        key_url = f"https://purge.jsdelivr.net/gh/{target_repo}@{target_branch}/static/rss/{key_file}"
        try:
            get_resp = requests.get(key_url, headers={"User-Agent": "NewsBot-CDN-Purge/1.0"}, timeout=timeout)
            if get_resp.status_code in [200, 201, 202]:
                logger.info("⚡ [CDN] jsDelivr Edge-Cache für %s synchron geleert.", key_file)
            else:
                logger.debug("jsDelivr Synchron-Purge für %s: Status %d", key_file, get_resp.status_code)
        except Exception as e_get:
            logger.debug("jsDelivr Synchron-Purge für %s nicht möglich: %s", key_file, e_get)

    results["success"] = len(results["errors"]) == 0
    return results


def reconcile_prompt_templates(config: dict[str, Any]) -> bool:
    """Gleicht gespeicherte Prompt-Vorlagen in der Konfiguration mit den kanonischen Standards ab."""
    from src.summarizer import DEFAULT_MAIN_PROMPT_TEMPLATE, DEFAULT_DIRECTIVES

    settings = config.setdefault("settings", {})
    changed = False

    current_main = settings.get("custom_main_prompt")
    if not current_main or not str(current_main).strip():
        settings["custom_main_prompt"] = DEFAULT_MAIN_PROMPT_TEMPLATE.strip()
        changed = True

    current_directives = settings.get("custom_prompt_directives")
    if not current_directives or not str(current_directives).strip():
        settings["custom_prompt_directives"] = DEFAULT_DIRECTIVES.strip()
        changed = True

    return changed


def load_prompts(config_path: str = "config/prompts.yaml") -> dict[str, Any]:
    """Lädt die KI-Prompt-Konfiguration aus config/prompts.yaml."""
    path = get_prompts_path(config_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def save_prompts(
    prompts: dict[str, Any],
    config_path: str = "config/prompts.yaml",
    sync_github: bool = False,
) -> dict[str, Any]:
    """Speichert Prompts persistent in config/prompts.yaml."""
    path = get_prompts_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(prompts, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    gh_res = {"success": False, "error": "Kein Token"}
    if sync_github:
        gh_res = sync_sources_to_github()
    return gh_res


def load_settings(config_path: str = "config/settings.yaml") -> dict[str, Any]:
    """Lädt die allgemeinen Anwendungseinstellungen aus config/settings.yaml."""
    path = get_settings_path(config_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if isinstance(data, dict) and "settings" in data and isinstance(data["settings"], dict):
        return data["settings"]
    return data if isinstance(data, dict) else {}


def save_settings(
    settings: dict[str, Any],
    config_path: str = "config/settings.yaml",
    sync_github: bool = False,
) -> dict[str, Any]:
    """Speichert globale Einstellungen persistent in config/settings.yaml (ohne Prompt-Keys)."""
    clean_settings = {k: v for k, v in settings.items() if k not in PROMPT_KEYS}
    path = get_settings_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(clean_settings, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    gh_res = {"success": False, "error": "Kein Token"}
    if sync_github:
        gh_res = sync_sources_to_github()
    return gh_res


def load_sources_raw(config_path: str = "config/sources.yaml") -> dict[str, Any]:
    """Lädt ausschließlich die Kategorien und Feeds aus config/sources.yaml."""
    path = get_sources_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Konfigurationsdatei {path} nicht gefunden.")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        data = {}
    if "categories" not in data:
        data["categories"] = []
    data["categories"].sort(key=lambda c: c.get("name", "").strip().lower())
    for cat in data["categories"]:
        for f in cat.get("feeds", []):
            f.pop("max_items", None)
    return data


def load_sources(config_path: str = "config/sources.yaml", auto_reconcile: bool = True) -> dict[str, Any]:
    """Lädt die Quellenkonfiguration aus sources.yaml, ergänzt um Einstellungen aus settings.yaml
    und Prompts aus prompts.yaml für nahtlose Abwärtskompatibilität."""
    data = load_sources_raw(config_path)

    path = get_sources_path(config_path)
    settings_file = path.parent / "settings.yaml"
    prompts_file = path.parent / "prompts.yaml"

    settings_data: dict[str, Any] = {}
    if settings_file.exists():
        settings_data = load_settings(str(settings_file))
    elif get_settings_path().exists():
        settings_data = load_settings()

    prompts_data: dict[str, Any] = {}
    if prompts_file.exists():
        prompts_data = load_prompts(str(prompts_file))
    elif get_prompts_path().exists():
        prompts_data = load_prompts()

    merged_settings = dict(data.get("settings", {}))
    merged_settings.update(settings_data)
    merged_settings.update(prompts_data)
    data["settings"] = merged_settings

    if auto_reconcile:
        reconcile_prompt_templates(data)

    return data


def save_sources(
    config: dict[str, Any],
    config_path: str = "config/sources.yaml",
    sync_github: bool = True
) -> dict[str, Any]:
    """Speichert die Quellenkonfiguration persistent in sources.yaml, settings.yaml und prompts.yaml
    und synchronisiert bei Bedarf mit GitHub."""
    path = get_sources_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    sources_data: dict[str, Any] = {}
    if "categories" in config:
        categories = list(config["categories"])
        categories.sort(key=lambda c: c.get("name", "").strip().lower())
        for cat in categories:
            for f in cat.get("feeds", []):
                f.pop("max_items", None)
        sources_data["categories"] = categories
    else:
        sources_data["categories"] = []

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(sources_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    settings_dict = config.get("settings")
    if isinstance(settings_dict, dict):
        settings_file = path.parent / "settings.yaml"
        prompts_file = path.parent / "prompts.yaml"

        prompt_data = {k: v for k, v in settings_dict.items() if k in PROMPT_KEYS}
        general_settings = {k: v for k, v in settings_dict.items() if k not in PROMPT_KEYS}

        if general_settings:
            save_settings(general_settings, str(settings_file), sync_github=False)
        if prompt_data:
            save_prompts(prompt_data, str(prompts_file), sync_github=False)

    gh_res = {"success": False, "error": "Kein Token"}
    if sync_github:
        gh_res = sync_sources_to_github(config_dict=config, config_path=config_path)
    return gh_res


def add_feed(
    category_name: str,
    feed_name: str,
    feed_url: str,
    max_items: int | None = None,
    config_path: str = "config/sources.yaml",
    config: dict[str, Any] | None = None,
    save_to_disk: bool = True,
    include_keywords: Any = None,
    exclude_keywords: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Fügt einen neuen Feed zu einer Kategorie hinzu oder aktualisiert ihn, falls die URL bereits existiert.
    Speichert die Änderungen in sources.yaml zurück, falls save_to_disk=True.
    """
    category_name = category_name.strip()
    feed_name = feed_name.strip()
    feed_url = feed_url.strip()

    if not category_name or not feed_name or not feed_url:
        raise ValueError("Kategorie, Feed-Name und Feed-URL dürfen nicht leer sein.")

    if config is None:
        config = load_sources(config_path)
    categories = config.setdefault("categories", [])

    target_category = None
    for cat in categories:
        if cat.get("name", "").strip().lower() == category_name.lower():
            target_category = cat
            break

    if not target_category:
        target_category = {"name": category_name, "feeds": []}
        categories.append(target_category)

    categories.sort(key=lambda c: c.get("name", "").strip().lower())
    feeds = target_category.setdefault("feeds", [])

    existing_feed = None
    for f in feeds:
        if f.get("url", "").strip() == feed_url:
            existing_feed = f
            break

    new_feed_obj = {
        "name": feed_name,
        "url": feed_url,
    }
    norm_inc = normalize_keywords(include_keywords)
    if norm_inc:
        new_feed_obj["include_keywords"] = norm_inc
    norm_exc = normalize_keywords(exclude_keywords)
    if norm_exc:
        new_feed_obj["exclude_keywords"] = norm_exc

    if existing_feed:
        existing_feed.update(new_feed_obj)
        existing_feed.pop("max_items", None)
    else:
        feeds.append(new_feed_obj)

    feeds.sort(key=lambda f: f.get("name", "").strip().lower())

    if save_to_disk:
        save_sources(config, config_path)
    return config


def delete_feed(
    category_name: str,
    feed_url: str,
    delete_empty_category: bool = False,
    config_path: str = "config/sources.yaml",
    config: dict[str, Any] | None = None,
    save_to_disk: bool = True,
) -> bool:
    """Löscht einen Feed anhand seiner Kategorie und URL aus sources.yaml oder dem config-Objekt."""
    if config is None:
        config = load_sources(config_path)
    categories = config.get("categories", [])
    found = False

    for cat in categories:
        if cat.get("name", "").strip().lower() == category_name.strip().lower():
            feeds = cat.get("feeds", [])
            initial_len = len(feeds)
            cat["feeds"] = [f for f in feeds if f.get("url", "").strip() != feed_url.strip()]
            if len(cat["feeds"]) < initial_len:
                found = True
            break

    if found:
        if delete_empty_category:
            config["categories"] = [
                c for c in config["categories"]
                if len(c.get("feeds", [])) > 0 or c.get("name", "").strip().lower() != category_name.strip().lower()
            ]
        if save_to_disk:
            save_sources(config, config_path)

    return found


def update_feed(
    category_name: str,
    old_url: str,
    new_name: str | None = None,
    new_url: str | None = None,
    new_max_items: int | None = None,
    new_category: str | None = None,
    config_path: str = "config/sources.yaml",
    config: dict[str, Any] | None = None,
    save_to_disk: bool = True,
    include_keywords: Any = None,
    exclude_keywords: Any = None,
    **kwargs: Any,
) -> bool:
    """Aktualisiert Name, URL, Keywords und/oder Kategorie eines bestehenden Feeds."""
    if config is None:
        config = load_sources(config_path)
    categories = config.get("categories", [])
    updated = False
    feed_to_move = None
    source_cat = None
    target_feed = None

    for cat in categories:
        if cat.get("name", "").strip().lower() == category_name.strip().lower():
            for f in cat.get("feeds", []):
                if f.get("url", "").strip() == old_url.strip():
                    source_cat = cat
                    target_feed = f
                    break
            if source_cat:
                break

    if not source_cat:
        for cat in categories:
            for f in cat.get("feeds", []):
                if f.get("url", "").strip() == old_url.strip():
                    source_cat = cat
                    target_feed = f
                    break
            if source_cat:
                break

    if source_cat and target_feed:
        if new_name is not None and new_name.strip():
            target_feed["name"] = new_name.strip()
        if new_url is not None and new_url.strip():
            target_feed["url"] = new_url.strip()
        target_feed.pop("max_items", None)

        if include_keywords is not None:
            norm_inc = normalize_keywords(include_keywords)
            if norm_inc:
                target_feed["include_keywords"] = norm_inc
            else:
                target_feed.pop("include_keywords", None)

        if exclude_keywords is not None:
            norm_exc = normalize_keywords(exclude_keywords)
            if norm_exc:
                target_feed["exclude_keywords"] = norm_exc
            else:
                target_feed.pop("exclude_keywords", None)

        updated = True

        actual_cat_name = source_cat.get("name", "").strip()
        if new_category and new_category.strip().lower() != actual_cat_name.lower():
            feed_to_move = dict(target_feed)
            source_cat["feeds"] = [x for x in source_cat.get("feeds", []) if x is not target_feed]

    if updated:
        if feed_to_move and new_category:
            target_cat = None
            target_cat_name_clean = new_category.strip()
            for c in categories:
                if c.get("name", "").strip().lower() == target_cat_name_clean.lower():
                    target_cat = c
                    break
            if not target_cat:
                target_cat = {"name": target_cat_name_clean, "feeds": []}
                categories.append(target_cat)

            target_feeds = target_cat.setdefault("feeds", [])
            target_url = feed_to_move.get("url", "").strip()
            existing_idx = None
            for idx, tf in enumerate(target_feeds):
                if tf.get("url", "").strip() == target_url:
                    existing_idx = idx
                    break
            if existing_idx is not None:
                target_feeds[existing_idx] = feed_to_move
            else:
                target_feeds.append(feed_to_move)

        categories.sort(key=lambda c: c.get("name", "").strip().lower())
        for c in categories:
            c.get("feeds", []).sort(key=lambda f: f.get("name", "").strip().lower())

        if save_to_disk:
            save_sources(config, config_path)

    return updated


def rename_category(
    old_name: str,
    new_name: str,
    config_path: str = "config/sources.yaml",
    config: dict[str, Any] | None = None,
    save_to_disk: bool = True,
) -> bool:
    """Benennt eine bestehende Kategorie um."""
    old_name = old_name.strip()
    new_name = new_name.strip()
    if not old_name or not new_name:
        raise ValueError("Alter und neuer Kategoriename dürfen nicht leer sein.")
    if old_name.lower() == new_name.lower():
        return True

    if config is None:
        config = load_sources(config_path)
    categories = config.get("categories", [])

    for cat in categories:
        if cat.get("name", "").strip().lower() == new_name.lower():
            raise ValueError(f"Eine Kategorie namens '{new_name}' existiert bereits.")

    found = False
    for cat in categories:
        if cat.get("name", "").strip().lower() == old_name.lower():
            cat["name"] = new_name
            found = True
            break

    if found:
        categories.sort(key=lambda c: c.get("name", "").strip().lower())
        if save_to_disk:
            save_sources(config, config_path)

    return found


def add_category(
    category_name: str,
    config_path: str = "config/sources.yaml",
    config: dict[str, Any] | None = None,
    save_to_disk: bool = True,
) -> bool:
    """Fügt eine neue Kategorie ohne Feeds hinzu, falls sie noch nicht existiert."""
    category_name = category_name.strip()
    if not category_name:
        raise ValueError("Kategoriename darf nicht leer sein.")

    if config is None:
        config = load_sources(config_path)
    categories = config.setdefault("categories", [])

    for cat in categories:
        if cat.get("name", "").strip().lower() == category_name.lower():
            return False

    categories.append({"name": category_name, "feeds": []})
    categories.sort(key=lambda c: c.get("name", "").strip().lower())
    if save_to_disk:
        save_sources(config, config_path)
    return True


def delete_category(
    category_name: str,
    config_path: str = "config/sources.yaml",
    config: dict[str, Any] | None = None,
    save_to_disk: bool = True,
) -> bool:
    """Löscht eine komplette Kategorie inklusive aller Feeds aus sources.yaml oder dem config-Objekt."""
    if config is None:
        config = load_sources(config_path)
    categories = config.get("categories", [])
    initial_len = len(categories)
    config["categories"] = [
        c for c in categories if c.get("name", "").strip().lower() != category_name.strip().lower()
    ]
    if len(config["categories"]) < initial_len:
        if save_to_disk:
            save_sources(config, config_path)
        return True
    return False


def update_settings(
    new_settings: dict[str, Any],
    config_path: str = "config/sources.yaml",
    config: dict[str, Any] | None = None,
    save_to_disk: bool = True,
) -> None:
    """Aktualisiert den settings-Abschnitt in sources.yaml oder im config-Objekt."""
    if config is None:
        config = load_sources(config_path)
    settings = config.setdefault("settings", {})
    settings.update(new_settings)
    if save_to_disk:
        save_sources(config, config_path)
