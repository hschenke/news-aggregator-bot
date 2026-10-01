import os
import json
import base64
import re
import html
import functools
import urllib.parse
import logging
import requests
import feedparser
import yaml
import calendar
import email.utils
import time
import concurrent.futures
from datetime import datetime, timezone
from typing import Any
from pathlib import Path

from src.models import Article
from src.exceptions import NewsAggregatorError, ConfigurationError, FeedFetchError

logger = logging.getLogger(__name__)


def get_sources_path(config_path: str = "config/sources.yaml") -> Path:
    """Ermittelt den absoluten Pfad zur sources.yaml-Datei."""
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
            yaml_content = yaml.dump(config_dict, allow_unicode=True, sort_keys=False, default_flow_style=False)
        else:
            file_path = get_sources_path(config_path)
            with open(file_path, "r", encoding="utf-8") as f:
                yaml_content = f.read()

        # 1. Versuch: Atomarer Multi-File-Push via Git Data API (Trees & Commits)
        if include_rss_feeds:
            try:
                ref_res = requests.get(f"https://api.github.com/repos/{repo}/git/ref/heads/{branch}", headers=headers, timeout=8)
                if ref_res.status_code == 200:
                    latest_commit_sha = ref_res.json().get("object", {}).get("sha")
                    commit_info_res = requests.get(f"https://api.github.com/repos/{repo}/git/commits/{latest_commit_sha}", headers=headers, timeout=8)
                    base_tree_sha = commit_info_res.json().get("tree", {}).get("sha")

                    tree_elements = [{
                        "path": "config/sources.yaml",
                        "mode": "100644",
                        "type": "blob",
                        "content": yaml_content
                    }]

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
                            html_url = f"https://github.com/{repo}/commit/{new_commit_sha}"

                            update_ref_res = requests.patch(
                                f"https://api.github.com/repos/{repo}/git/refs/heads/{branch}",
                                headers=headers,
                                json={"sha": new_commit_sha, "force": False},
                                timeout=10
                            )
                            if update_ref_res.status_code == 200:
                                return {"success": True, "commit_url": html_url, "error": None}
            except Exception as e_tree:
                print(f"[Hinweis] Git Trees API fehlgeschlagen, weiche auf Contents API aus: {e_tree}")

        # 2. Fallback: sources.yaml per Contents API pushen & Action triggern
        rel_path = "config/sources.yaml"
        url = f"https://api.github.com/repos/{repo}/contents/{rel_path}"
        sha = None
        get_res = requests.get(url, headers=headers, params={"ref": branch}, timeout=8)
        if get_res.status_code == 200:
            sha = get_res.json().get("sha")

        encoded_bytes = base64.b64encode(yaml_content.encode("utf-8")).decode("utf-8")
        payload = {
            "message": commit_message,
            "content": encoded_bytes,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        put_res = requests.put(url, headers=headers, json=payload, timeout=10)
        if put_res.status_code in [200, 201]:
            commit_data = put_res.json().get("commit", {})
            html_url = commit_data.get("html_url", "")
            trigger_rss_update_workflow()
            return {"success": True, "commit_url": html_url, "error": None}
        else:
            return {"success": False, "commit_url": None, "error": f"Status {put_res.status_code}: {put_res.text}"}
    except Exception as e:
        return {"success": False, "commit_url": None, "error": str(e)}


def trigger_rss_update_workflow() -> dict[str, Any]:
    """Löst den GitHub Actions Workflow 'update_rss.yml' per workflow_dispatch aus."""
    gh_cfg = get_github_sync_config()
    token = gh_cfg["token"]
    if not token or token.startswith("your_"):
        return {"success": False, "error": "Kein GITHUB_TOKEN hinterlegt."}

    repo = gh_cfg["repo"]
    branch = gh_cfg["branch"]
    url = f"https://api.github.com/repos/{repo}/actions/workflows/update_rss.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        res = requests.post(url, headers=headers, json={"ref": branch}, timeout=8)
        if res.status_code in [204, 200, 201]:
            return {"success": True, "error": None}
        return {"success": False, "error": f"Status {res.status_code}: {res.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}



def reconcile_prompt_templates(config: dict[str, Any]) -> bool:
    """Gleicht gespeicherte Prompt-Vorlagen in der Konfiguration mit den kanonischen Standards ab.

    Stellt sicher, dass fehlende oder leere Prompts automatisch 1:1 mit den
    kanonischen Vorlagen (DEFAULT_MAIN_PROMPT_TEMPLATE bzw. DEFAULT_DIRECTIVES) initialisiert werden.
    Gibt True zurück, wenn Änderungen vorgenommen wurden.
    """
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


def load_sources(config_path: str = "config/sources.yaml", auto_reconcile: bool = True) -> dict[str, Any]:
    """Lädt die Konfiguration aus sources.yaml, garantiert alphabetische Kategoriensortierung
    und gleicht Prompt-Vorlagen bei Bedarf 1:1 mit den Code-Standards ab."""
    path = get_sources_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Konfigurationsdatei {path} nicht gefunden.")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "categories" not in data:
        data["categories"] = []
    if "settings" not in data:
        data["settings"] = {}

    # Kategorien alphabetisch sortieren
    data["categories"].sort(key=lambda c: c.get("name", "").strip().lower())
    for cat in data["categories"]:
        for f in cat.get("feeds", []):
            f.pop("max_items", None)

    if auto_reconcile:
        reconcile_prompt_templates(data)

    return data


def save_sources(
    config: dict[str, Any],
    config_path: str = "config/sources.yaml",
    sync_github: bool = True
) -> dict[str, Any]:
    """Speichert die Quellenkonfiguration persistent in sources.yaml und synchronisiert mit GitHub (falls konfiguriert)."""
    if "categories" in config:
        config["categories"].sort(key=lambda c: c.get("name", "").strip().lower())
        for cat in config["categories"]:
            for f in cat.get("feeds", []):
                f.pop("max_items", None)

    path = get_sources_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

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

    # Suche nach bestehender Kategorie
    target_category = None
    for cat in categories:
        if cat.get("name", "").strip().lower() == category_name.lower():
            target_category = cat
            break

    if not target_category:
        target_category = {"name": category_name, "feeds": []}
        categories.append(target_category)

    # Kategorien alphabetisch sortieren
    categories.sort(key=lambda c: c.get("name", "").strip().lower())

    feeds = target_category.setdefault("feeds", [])

    # Prüfen, ob Feed mit der gleichen URL bereits in dieser Kategorie existiert
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

    # Feeds alphabetisch sortieren
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
    """
    Löscht einen Feed anhand seiner Kategorie und URL aus sources.yaml oder dem config-Objekt.
    Gibt True zurück, wenn der Feed gefunden und gelöscht wurde.
    """
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
    """
    Aktualisiert Name, URL, Keywords und/oder Kategorie eines bestehenden Feeds.
    Ermöglicht auch das Verschieben von Feeds in bestehende oder neue Kategorien.
    """
    if config is None:
        config = load_sources(config_path)
    categories = config.get("categories", [])
    updated = False
    feed_to_move = None
    source_cat = None
    target_feed = None

    # Zuerst in der angegebenen Kategorie suchen
    for cat in categories:
        if cat.get("name", "").strip().lower() == category_name.strip().lower():
            for f in cat.get("feeds", []):
                if f.get("url", "").strip() == old_url.strip():
                    source_cat = cat
                    target_feed = f
                    break
            if source_cat:
                break

    # Fallback: Falls category_name nicht exakt passte, in allen Kategorien nach old_url suchen
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
            # Feed sicher aus der bisherigen Kategorie entfernen
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

        # Kategorien und Feeds alphabetisch sortieren
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
            return False  # existiert bereits

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


FEED_REQUEST_HEADERS_READER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) NetNewsWire/6.1"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
}

FEED_REQUEST_HEADERS_BOT = {
    "User-Agent": "Feedfetcher-Google; (+http://www.google.com/feedfetcher.html)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

FEED_REQUEST_HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
}


def determine_stream_type(version: str, content_type: str, raw_content: bytes) -> str:
    """Bestimmt den lesbaren Typ des Datenstroms (z. B. RSS 2.0, Atom 1.0, HTML)."""
    v_low = (version or "").lower().strip()
    if v_low == "rss20":
        return "RSS 2.0"
    elif v_low == "atom10":
        return "Atom 1.0"
    elif v_low in ("rss091", "rss092"):
        return "RSS 0.9x"
    elif v_low == "rss10":
        return "RSS 1.0 (RDF)"
    elif v_low == "atom03":
        return "Atom 0.3"
    elif "rss" in v_low:
        return f"RSS ({version})"
    elif "atom" in v_low:
        return f"Atom ({version})"

    head = raw_content[:1500].decode("utf-8", errors="ignore").lower()
    if "<rss" in head:
        return "RSS 2.0"
    if "<feed" in head and ("xmlns=\"http://www.w3.org/2005/atom\"" in head or "xmlns='http://www.w3.org/2005/atom'" in head or "atom" in head):
        return "Atom 1.0"
    if "<rdf:rdf" in head:
        return "RSS 1.0 (RDF)"
    if "<!doctype html" in head or "<html" in head or "text/html" in (content_type or "").lower():
        return "HTML-Webseite (Kein RSS-Stream)"
    return "Unbekanntes Format"


def autodiscover_rss_feeds(raw_content: bytes, base_url: str) -> list[dict[str, str]]:
    """Sucht in HTML-Inhalten nach verlinkten RSS/Atom-Feeds (<link rel='alternate' ...>)."""
    discovered: list[dict[str, str]] = []
    if not raw_content:
        return discovered
    try:
        text = raw_content[:30000].decode("utf-8", errors="ignore")
        link_tags = re.findall(r"<link[^>]+>", text, re.IGNORECASE)
        seen_urls = set()
        for tag in link_tags:
            tag_l = tag.lower()
            if "alternate" in tag_l and ("rss" in tag_l or "atom" in tag_l or "xml" in tag_l):
                m_href = re.search(r'href=[\'"]([^\'"]+)[\'"]', tag, re.IGNORECASE)
                m_title = re.search(r'title=[\'"]([^\'"]+)[\'"]', tag, re.IGNORECASE)
                if m_href:
                    href = m_href.group(1).strip()
                    full_url = urllib.parse.urljoin(base_url, href)
                    if full_url not in seen_urls:
                        seen_urls.add(full_url)
                        title = m_title.group(1).strip() if m_title else "RSS-Feed"
                        discovered.append({"title": title, "url": full_url})
    except Exception:
        pass
    return discovered


def fetch_feed_raw(feed_url: str, timeout: int = 10) -> dict[str, Any]:
    """
    Lädt die Rohdaten einer Feed-URL robust mittels requests herunter.
    Unterstützt automatische RSS-Header, Fallback-Header bei 202/403/406,
    WAF-Bypass-Proxy (Jina AI) und lokalen Projekt-Mirror.
    """
    feed_url = (feed_url or "").strip()
    if not (feed_url.startswith("http://") or feed_url.startswith("https://")):
        return {
            "success": False,
            "status_code": 0,
            "error": "URL muss mit http:// oder https:// beginnen.",
            "content": b"",
            "headers": {},
            "final_url": feed_url,
            "is_redirected": False,
            "content_type": "",
            "latency_ms": 0,
            "is_proxied": False,
            "is_cached_mirror": False,
        }

    header_variants = [FEED_REQUEST_HEADERS_READER, FEED_REQUEST_HEADERS_BOT, FEED_REQUEST_HEADERS_BROWSER]
    last_err = None
    last_resp = None

    t0 = time.time()
    for headers in header_variants:
        try:
            with requests.Session() as session:
                resp = session.get(feed_url, headers=headers, timeout=timeout, allow_redirects=True)
                last_resp = resp
                if resp.status_code == 200:
                    # Validieren, dass nicht ein HTML-Challenge-Body fälschlicherweise mit 200 kam
                    head_l = resp.content[:1500].lower()
                    if b"<rss" in head_l or b"<feed" in head_l or b"<?xml" in head_l or b"<rdf:rdf" in head_l:
                        break
                    if "text/html" in resp.headers.get("content-type", "").lower():
                        continue
                    break
                # Bei WAF-Challenge (202), Forbidden (403), Not Acceptable (406) etc. nächsten Headersatz probieren
                if resp.status_code in [202, 403, 406, 429, 503]:
                    continue
                break
        except Exception as e:
            last_err = e

    latency_ms = int((time.time() - t0) * 1000)

    # 1. Erfolgreicher Direktabruf (echter XML-Stream mit Status 200)
    if last_resp is not None and last_resp.status_code == 200:
        head_l = last_resp.content[:1500].lower()
        if b"<rss" in head_l or b"<feed" in head_l or b"<?xml" in head_l or b"<rdf:rdf" in head_l or "xml" in last_resp.headers.get("content-type", "").lower():
            return {
                "success": True,
                "status_code": 200,
                "content": last_resp.content,
                "headers": dict(last_resp.headers),
                "final_url": str(last_resp.url),
                "is_redirected": str(last_resp.url).rstrip("/") != feed_url.rstrip("/"),
                "content_type": last_resp.headers.get("content-type", ""),
                "latency_ms": latency_ms,
                "is_proxied": False,
                "is_cached_mirror": False,
                "error": None,
            }

    # 2. Versuch über WAF-Bypass-Proxy (r.jina.ai) bei 202 (AWS WAF Challenge), 403 (Forbidden) oder HTML-Challenge
    if last_resp is None or last_resp.status_code in [202, 403, 406, 429, 500, 502, 503] or ("text/html" in getattr(last_resp, "headers", {}).get("content-type", "").lower()):
        try:
            proxy_url = f"https://r.jina.ai/{feed_url}"
            with requests.Session() as session:
                p_resp = session.get(proxy_url, timeout=timeout)
                if p_resp.status_code == 200:
                    text_p = p_resp.text
                    idx_rss = text_p.find("<rss")
                    if idx_rss == -1:
                        idx_rss = text_p.find("<feed")
                    if idx_rss != -1:
                        clean_xml = text_p[idx_rss:].encode("utf-8")
                        return {
                            "success": True,
                            "status_code": 200,
                            "content": clean_xml,
                            "headers": {"content-type": "application/rss+xml; charset=utf-8"},
                            "final_url": feed_url,
                            "is_redirected": False,
                            "content_type": "application/rss+xml; charset=utf-8",
                            "latency_ms": int((time.time() - t0) * 1000),
                            "is_proxied": True,
                            "is_cached_mirror": False,
                            "error": None,
                        }
        except Exception:
            pass

    # 3. Versuch: Synchronisierter lokaler oder GitHub-Projekt-Mirror (static/rss/feeds/)
    try:
        clean_url_key = feed_url.replace("https://", "").replace("http://", "").strip("/")
        feed_dir = Path("static/rss/feeds")
        if feed_dir.exists():
            for xml_file in feed_dir.glob("*.xml"):
                content = xml_file.read_bytes()
                if feed_url.encode("utf-8") in content or clean_url_key.encode("utf-8") in content:
                    return {
                        "success": True,
                        "status_code": 200,
                        "content": content,
                        "headers": {"content-type": "application/rss+xml; charset=utf-8"},
                        "final_url": feed_url,
                        "is_redirected": False,
                        "content_type": "application/rss+xml; charset=utf-8",
                        "latency_ms": int((time.time() - t0) * 1000),
                        "is_proxied": False,
                        "is_cached_mirror": True,
                        "error": None,
                    }
    except Exception:
        pass

    # 4. Falls alles fehlschlägt, letzten HTTP-Fehler zurückgeben
    if last_resp is not None:
        return {
            "success": False,
            "status_code": last_resp.status_code,
            "content": last_resp.content,
            "headers": dict(last_resp.headers),
            "final_url": str(last_resp.url),
            "is_redirected": str(last_resp.url).rstrip("/") != feed_url.rstrip("/"),
            "content_type": last_resp.headers.get("content-type", ""),
            "latency_ms": latency_ms,
            "is_proxied": False,
            "is_cached_mirror": False,
            "error": f"HTTP {last_resp.status_code}" if last_resp.status_code != 200 else "Kein valider RSS-Stream",
        }

    return {
        "success": False,
        "status_code": 0,
        "content": b"",
        "headers": {},
        "final_url": feed_url,
        "is_redirected": False,
        "content_type": "",
        "latency_ms": latency_ms,
        "is_proxied": False,
        "is_cached_mirror": False,
        "error": str(last_err or "Verbindungsaufbau fehlgeschlagen"),
    }

    latency_ms = int((time.time() - t0) * 1000)

    if last_resp is not None:
        return {
            "success": last_resp.status_code == 200,
            "status_code": last_resp.status_code,
            "content": last_resp.content,
            "headers": dict(last_resp.headers),
            "final_url": str(last_resp.url),
            "is_redirected": str(last_resp.url).rstrip("/") != feed_url.rstrip("/"),
            "content_type": last_resp.headers.get("content-type", ""),
            "latency_ms": latency_ms,
            "error": f"HTTP {last_resp.status_code}" if last_resp.status_code != 200 else None,
        }

    return {
        "success": False,
        "status_code": 0,
        "content": b"",
        "headers": {},
        "final_url": feed_url,
        "is_redirected": False,
        "content_type": "",
        "latency_ms": latency_ms,
        "error": str(last_err or "Verbindungsaufbau fehlgeschlagen"),
    }


def test_feed_connection(feed_url: str, timeout: int = 10) -> dict[str, Any]:
    """Testet die Erreichbarkeit, Stream-Validität und Metadaten einer Feed-URL."""
    feed_url = (feed_url or "").strip()
    if not feed_url:
        return {"success": False, "is_valid_feed": False, "error": "URL ist leer.", "item_count": 0, "title": "Keine URL"}

    if not (feed_url.startswith("http://") or feed_url.startswith("https://")):
        return {"success": False, "is_valid_feed": False, "error": "URL muss mit http:// oder https:// beginnen.", "item_count": 0, "title": "Ungültige URL"}

    raw_res = fetch_feed_raw(feed_url, timeout=timeout)
    if not raw_res["success"] and not raw_res["content"]:
        # Fallback auf direkte feedparser URL-Auflösung
        try:
            p_fallback = feedparser.parse(feed_url)
            fb_entries = getattr(p_fallback, "entries", [])
            if fb_entries or getattr(p_fallback, "version", ""):
                feed_title = clean_html_text(p_fallback.feed.get("title", "")) if hasattr(p_fallback, "feed") else ""
                latest_title = clean_html_text(fb_entries[0].get("title", "Kein Titel")) if fb_entries else "Keine Artikel vorhanden"
                return {
                    "success": True,
                    "is_valid_feed": True,
                    "title": feed_title or "Unbekannter Titel",
                    "description": clean_html_text(getattr(p_fallback.feed, "description", "")),
                    "site_url": getattr(p_fallback.feed, "link", ""),
                    "language": getattr(p_fallback.feed, "language", ""),
                    "last_updated": getattr(p_fallback.feed, "updated", "") or getattr(p_fallback.feed, "published", ""),
                    "item_count": len(fb_entries),
                    "latest_title": latest_title,
                    "stream_type": getattr(p_fallback, "version", "RSS/Atom"),
                    "feed_version": getattr(p_fallback, "version", ""),
                    "status_code": getattr(p_fallback, "status", 200),
                    "content_type": p_fallback.get("headers", {}).get("content-type", "application/xml"),
                    "content_length": len(getattr(p_fallback, "raw", b"")),
                    "latency_ms": raw_res.get("latency_ms", 0),
                    "final_url": feed_url,
                    "is_redirected": False,
                    "sample_items": [
                        {
                            "title": clean_html_text(getattr(e, "title", "Ohne Titel")),
                            "link": unwrap_and_clean_url(getattr(e, "link", "").strip()),
                            "published": getattr(e, "published", "") or getattr(e, "updated", ""),
                            "summary": clean_html_text(getattr(e, "summary", "") or getattr(e, "description", ""))[:160],
                        }
                        for e in fb_entries[:3]
                    ],
                    "warning": None,
                    "error": None,
                    "autodiscovered_feeds": [],
                }
        except Exception:
            pass

        return {
            "success": False,
            "is_valid_feed": False,
            "title": "Verbindung fehlgeschlagen",
            "stream_type": "Kein Stream",
            "item_count": 0,
            "latest_title": "Keine Artikel vorhanden",
            "status_code": raw_res.get("status_code", 0),
            "content_type": raw_res.get("content_type", ""),
            "content_length": 0,
            "latency_ms": raw_res.get("latency_ms", 0),
            "final_url": feed_url,
            "is_redirected": False,
            "sample_items": [],
            "error": raw_res.get("error") or "Feed-URL konnte nicht erreicht werden.",
            "warning": None,
            "autodiscovered_feeds": [],
        }

    raw_data = raw_res["content"]
    content_type = raw_res.get("content_type", "")
    final_url = raw_res.get("final_url", feed_url)

    parsed = feedparser.parse(raw_data)
    entries = getattr(parsed, "entries", [])
    feed_meta = getattr(parsed, "feed", {})

    feed_title = clean_html_text(feed_meta.get("title", "")) if hasattr(feed_meta, "get") else ""
    feed_desc = clean_html_text(feed_meta.get("description", "") or feed_meta.get("subtitle", "")) if hasattr(feed_meta, "get") else ""
    feed_link = feed_meta.get("link", "") if hasattr(feed_meta, "get") else ""
    feed_lang = feed_meta.get("language", "") if hasattr(feed_meta, "get") else ""
    feed_updated = feed_meta.get("updated", "") or feed_meta.get("published", "") or feed_meta.get("pubDate", "") if hasattr(feed_meta, "get") else ""

    stream_version = getattr(parsed, "version", "")
    stream_type = determine_stream_type(stream_version, content_type, raw_data)

    is_html = "html" in stream_type.lower() or ("text/html" in content_type.lower() and not entries)
    discovered_feeds = []
    if is_html or (not entries and "text/html" in content_type.lower()):
        discovered_feeds = autodiscover_rss_feeds(raw_data, final_url)

    # Wenn 0 Einträge und HTML oder WAF-Block:
    if not entries and is_html:
        err_msg = "Die URL liefert eine HTML-Webseite statt eines RSS-Streams."
        text_preview = raw_data[:1000].decode("utf-8", errors="ignore").lower()
        if any(term in text_preview for term in ["cloudflare", "waf", "challenge", "403 forbidden", "access denied", "bot"]):
            err_msg += " (Hinweis: Die Website blockiert den automatisierten Zugriff durch einen WAF-/Bot-Schutz)."
        return {
            "success": False,
            "is_valid_feed": False,
            "title": feed_title or "HTML Webseite (Kein Feed)",
            "description": feed_desc,
            "site_url": feed_link or final_url,
            "language": feed_lang,
            "last_updated": feed_updated,
            "stream_type": "HTML-Webseite (Kein RSS-Stream)",
            "feed_version": "",
            "item_count": 0,
            "latest_title": "Keine Artikel vorhanden",
            "status_code": raw_res.get("status_code", 200),
            "content_type": content_type,
            "content_length": len(raw_data),
            "latency_ms": raw_res.get("latency_ms", 0),
            "final_url": final_url,
            "is_redirected": raw_res.get("is_redirected", False),
            "sample_items": [],
            "error": err_msg,
            "warning": None,
            "autodiscovered_feeds": discovered_feeds,
        }

    # Wenn 0 Einträge und fehlerhafte XML-Syntax:
    if not entries and hasattr(parsed, "bozo") and parsed.bozo:
        bozo_exc = getattr(parsed, "bozo_exception", "Unbekannter Parsing-Fehler")
        return {
            "success": False,
            "is_valid_feed": False,
            "title": feed_title or "Ungültiger Stream",
            "description": feed_desc,
            "site_url": feed_link or final_url,
            "language": feed_lang,
            "last_updated": feed_updated,
            "stream_type": stream_type,
            "feed_version": stream_version,
            "item_count": 0,
            "latest_title": "Keine Artikel vorhanden",
            "status_code": raw_res.get("status_code", 200),
            "content_type": content_type,
            "content_length": len(raw_data),
            "latency_ms": raw_res.get("latency_ms", 0),
            "final_url": final_url,
            "is_redirected": raw_res.get("is_redirected", False),
            "sample_items": [],
            "error": f"Fehler beim Parsen des Feeds: {bozo_exc}",
            "warning": None,
            "autodiscovered_feeds": discovered_feeds,
        }

    sample_items = []
    for e in entries[:3]:
        e_title = clean_html_text(getattr(e, "title", "Ohne Titel"))
        e_link = unwrap_and_clean_url(getattr(e, "link", "").strip())
        e_pub = getattr(e, "published", "") or getattr(e, "updated", "") or ""
        e_desc = clean_html_text(getattr(e, "summary", "") or getattr(e, "description", ""))
        if len(e_desc) > 160:
            e_desc = e_desc[:157] + "..."
        sample_items.append({
            "title": e_title,
            "link": e_link,
            "published": e_pub,
            "summary": e_desc,
        })

    latest_title = sample_items[0]["title"] if sample_items else "Keine Artikel vorhanden"
    latest_date = sample_items[0]["published"] if sample_items else ""
    latest_link = sample_items[0]["link"] if sample_items else ""

    display_title = feed_title or (f"Feed ({urllib.parse.urlparse(feed_url).netloc})" if entries else "Unbekannter Titel")

    warning = None
    if raw_res.get("is_proxied"):
        warning = "Der Feed liegt hinter einem WAF-/Bot-Schutz (z. B. CloudFront HTTP 202) und wurde erfolgreich über einen WAF-Proxy geladen."
    elif raw_res.get("is_cached_mirror"):
        warning = "Der Feed liegt hinter einem WAF-/Bot-Schutz und wurde aus dem synchronisierten Projekt-Mirror geladen."
    elif len(entries) == 0:
        warning = "Feed ist erreichbar und syntaktisch valide, enthält aber aktuell 0 Einträge."
    elif raw_res.get("is_redirected"):
        warning = f"URL wurde weitergeleitet auf: {final_url}"

    return {
        "success": True,
        "is_valid_feed": True,
        "title": display_title,
        "description": feed_desc,
        "site_url": feed_link or final_url,
        "language": feed_lang,
        "last_updated": feed_updated,
        "stream_type": stream_type,
        "feed_version": stream_version,
        "status_code": raw_res.get("status_code", 200),
        "content_type": content_type,
        "content_length": len(raw_data),
        "latency_ms": raw_res.get("latency_ms", 0),
        "final_url": final_url,
        "is_redirected": raw_res.get("is_redirected", False),
        "item_count": len(entries),
        "latest_title": latest_title,
        "latest_date": latest_date,
        "latest_link": latest_link,
        "sample_items": sample_items,
        "warning": warning,
        "error": None,
        "autodiscovered_feeds": discovered_feeds,
    }



@functools.lru_cache(maxsize=2048)
def clean_html_text(text: str) -> str:
    """Bereinigt HTML-Tags (z. B. <b>, <i>, <a>), unescaped Entities (&amp;, &quot;) und normalisiert Whitespace."""
    if not text:
        return ""
    # Zweifaches Unescaping für doppelt kodierte HTML-Entities
    cleaned = html.unescape(text)
    if any(entity in cleaned for entity in ["&lt;", "&gt;", "&amp;", "&quot;", "&#"]):
        cleaned = html.unescape(cleaned)
    # Alle HTML-Tags entfernen
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Typische geschützte Leerzeichen und Steuerzeichen aufräumen
    cleaned = cleaned.replace("\xa0", " ").replace("&nbsp;", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


@functools.lru_cache(maxsize=2048)
def format_summary_html(text: str) -> str:
    """
    Bereitet eine Zusammenfassung für HTML-Container auf:
    1. Bereinigt HTML-Tags via clean_html_text().
    2. Wandelt Markdown-Fettdruck (**Text**) in HTML <strong>Text</strong> um,
       sodass Text in HTML-Elementen wie <div> verlässlich fett gerendert wird.
    """
    if not text:
        return ""
    cleaned = clean_html_text(text)
    if not cleaned:
        return ""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", cleaned)


def unwrap_and_clean_url(url: str) -> str:
    """Löst Google Alert Redirect-URLs auf und extrahiert die tatsächliche Ziel-URL."""
    if not url:
        return ""
    url = url.strip()
    if "google.com/url?" in url:
        try:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            target = qs.get("url") or qs.get("q")
            if target and target[0]:
                url = target[0].strip()
        except Exception:
            pass
    return url


def get_canonical_url(url: str) -> str:
    """Normalisiert URLs für die Duplikatsprüfung (entfernt Tracking-Parameter wie utm_*, fbclid)."""
    url = unwrap_and_clean_url(url)
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.query:
            qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            filtered_qs = {
                k: v for k, v in qs.items()
                if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "ocid", "cmpid", "ref"}
            }
            new_query = urllib.parse.urlencode(filtered_qs, doseq=True)
            url = urllib.parse.urlunparse((
                parsed.scheme,
                parsed.netloc.lower(),
                parsed.path.rstrip("/") or "/",
                parsed.params,
                new_query,
                ""
            ))
    except Exception:
        pass
    return url.rstrip("/")


def normalize_keywords(kw: Any) -> list[str]:
    """Wandelt Keywords (Liste, String oder None) in eine bereinigte Liste von Strings um."""
    if not kw:
        return []
    if isinstance(kw, str):
        return [k.strip() for k in kw.split(",") if k.strip()]
    if isinstance(kw, (list, set, tuple)):
        res = []
        for k in kw:
            if isinstance(k, str):
                res.extend([x.strip() for x in k.split(",") if x.strip()])
            elif k is not None:
                res.append(str(k).strip())
        return [r for r in res if r]
    return []


DEFAULT_AD_PATTERNS = [
    r"^heise-angebot:",
    r"\b(?:anzeige|advertorial|partnerangebot|sonderveröffentlichung)\b",
    r"^(?:anzeige|werbung|sponsored|gesponsert|partnerangebot):",
    r"\[(?:anzeige|werbung|sponsored)\]",
    r"\b(?:sponsored post|sponsored content)\b",
    r"\bdeal(?:s)? des tages\b",
    r"^rabatt-aktion\b",
]


def is_ad_item(title: str, summary: str = "", custom_ad_keywords: list[str] | None = None) -> bool:
    """Prüft, ob ein Artikel Werbung, Anzeige, gesponsertes Angebot oder Deal ist."""
    t_clean = (title or "").strip().lower()
    s_clean = (summary or "").strip().lower()

    for pat in DEFAULT_AD_PATTERNS:
        if re.search(pat, t_clean, re.IGNORECASE) or re.search(pat, s_clean, re.IGNORECASE):
            return True

    if custom_ad_keywords:
        for kw in custom_ad_keywords:
            k = kw.strip().lower()
            if k and (k in t_clean or k in s_clean):
                return True

    return False


DEFAULT_MAX_ARTICLE_AGE_WEEKS: int = 20
SECONDS_PER_WEEK: int = 7 * 24 * 60 * 60  # 604_800 Sekunden pro Woche


def get_article_timestamp(item: Any) -> float:
    """
    Ermittelt den Unix-Timestamp (Sekunden seit Epoch) eines Artikels, Eintrags oder Datums.
    Unterstützt Article-Objekte, Dictionaries, feedparser-Entries, Datetime-Objekte und Zahlen.
    Gibt 0.0 zurück, falls kein valides Datum extrahiert werden kann.
    """
    if item is None:
        return 0.0

    if isinstance(item, (int, float)):
        return float(item) if item > 0 else 0.0

    if isinstance(item, datetime):
        return item.timestamp()

    if isinstance(item, time.struct_time):
        try:
            return float(calendar.timegm(item))
        except Exception:
            try:
                return float(time.mktime(item))
            except Exception:
                return 0.0

    # 1. Direkter Timestamp
    ts = None
    if isinstance(item, dict):
        ts = item.get("timestamp")
    elif hasattr(item, "timestamp"):
        ts = getattr(item, "timestamp")

    if ts is not None and isinstance(ts, (int, float)) and ts > 0:
        return float(ts)

    # 2. Parsed struct_time aus RSS/Atom
    parsed_time = None
    if isinstance(item, dict):
        parsed_time = item.get("published_parsed") or item.get("updated_parsed")
    elif hasattr(item, "published_parsed") or hasattr(item, "updated_parsed"):
        parsed_time = getattr(item, "published_parsed", None) or getattr(item, "updated_parsed", None)

    if parsed_time and isinstance(parsed_time, time.struct_time):
        try:
            return float(calendar.timegm(parsed_time))
        except Exception:
            try:
                return float(time.mktime(parsed_time))
            except Exception:
                pass

    # 3. String-Datum (RFC-822 oder ISO-8601)
    pub_str = ""
    if isinstance(item, dict):
        pub_str = item.get("published") or item.get("updated") or ""
    elif hasattr(item, "published") or hasattr(item, "updated"):
        pub_str = getattr(item, "published", "") or getattr(item, "updated", "") or ""

    if isinstance(pub_str, str) and pub_str.strip():
        s = pub_str.strip()
        try:
            dt = email.utils.parsedate_to_datetime(s)
            if dt:
                return dt.timestamp()
        except Exception:
            pass
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            pass

    return 0.0


def is_article_too_old(
    article_or_dict: Any,
    max_age_weeks: int | float | None = DEFAULT_MAX_ARTICLE_AGE_WEEKS,
    now_ts: float | None = None,
) -> bool:
    """
    Prüft, ob ein Artikel älter als max_age_weeks Wochen ist.
    Gibt True zurück, wenn der Artikel älter als der Stichtag ist und herausgefiltert werden soll.
    Falls max_age_weeks None oder <= 0 ist, wird keine Altersbegrenzung angewendet (gibt False zurück).
    Artikel ohne ermittelbares Datum (timestamp <= 0.0) werden nicht als zu alt gewertet.
    """
    if max_age_weeks is None or max_age_weeks <= 0:
        return False

    ts = get_article_timestamp(article_or_dict)
    if ts <= 0.0:
        return False

    if now_ts is None:
        now_ts = time.time()

    cutoff_ts = now_ts - (float(max_age_weeks) * SECONDS_PER_WEEK)
    return ts < cutoff_ts


def filter_articles_by_age(
    articles: list[dict[str, Any]],
    max_age_weeks: int | float | None = DEFAULT_MAX_ARTICLE_AGE_WEEKS,
    now_ts: float | None = None,
) -> list[dict[str, Any]]:
    """Filtert eine Artikelliste und schließt alle Artikel aus, die älter als max_age_weeks Wochen sind."""
    if max_age_weeks is None or max_age_weeks <= 0:
        return articles

    if now_ts is None:
        now_ts = time.time()

    return [
        article for article in articles
        if not is_article_too_old(article, max_age_weeks=max_age_weeks, now_ts=now_ts)
    ]


def filter_news_data_by_age(
    news_data: dict[str, list[dict[str, Any]]],
    max_age_weeks: int | float | None = DEFAULT_MAX_ARTICLE_AGE_WEEKS,
    now_ts: float | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Filtert ein nach Kategorien gruppiertes News-Dictionary nach maximalem Artikel-Alter."""
    if max_age_weeks is None or max_age_weeks <= 0:
        return news_data

    if now_ts is None:
        now_ts = time.time()

    filtered: dict[str, list[dict[str, Any]]] = {}
    for category_name, items in news_data.items():
        filtered[category_name] = filter_articles_by_age(
            items,
            max_age_weeks=max_age_weeks,
            now_ts=now_ts,
        )
    return filtered


_POLICE_TEASER_CACHE: dict[str, str] = {}
_POLICE_CACHE_FILE = Path("data/police_teasers_cache.json")


def _load_police_cache() -> None:
    global _POLICE_TEASER_CACHE
    if not _POLICE_TEASER_CACHE and _POLICE_CACHE_FILE.exists():
        try:
            with open(_POLICE_CACHE_FILE, "r", encoding="utf-8") as f:
                _POLICE_TEASER_CACHE = json.load(f)
        except Exception:
            pass


def _save_police_cache() -> None:
    try:
        _POLICE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_POLICE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_POLICE_TEASER_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def extract_police_teaser(url: str, session: requests.Session | None = None) -> str:
    """Extrahiert den Ereignisort (Bezirk/Stadtteil) und Teaser-Text einer Berliner Polizeimeldung aus dem HTML-Body."""
    if not url or "berlin.de/polizei" not in url:
        return ""
    _load_police_cache()
    clean_u = unwrap_and_clean_url(url)
    if clean_u in _POLICE_TEASER_CACHE and _POLICE_TEASER_CACHE[clean_u]:
        return _POLICE_TEASER_CACHE[clean_u]
    if url in _POLICE_TEASER_CACHE and _POLICE_TEASER_CACHE[url]:
        return _POLICE_TEASER_CACHE[url]

    for attempt in range(2):
        try:
            s = session or requests
            r = s.get(
                url,
                timeout=8.0,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NewsAggregatorBot/1.0"}
            )
            if r.status_code == 200:
                district = ""
                m_dist = re.search(r'title=[\'"]Ereignisort[\'"]>([^<]+)<', r.text, re.IGNORECASE)
                if m_dist:
                    district = clean_html_text(m_dist.group(1)).strip()

                teaser = ""
                m_nr = re.search(r'<p[^>]*>\s*<strong>Nr\.\s*\d+</strong><br\s*/?>\s*(.*?)</p>', r.text, re.DOTALL | re.IGNORECASE)
                if m_nr:
                    clean = clean_html_text(m_nr.group(1))
                    clean = re.sub(r"^Nr\.\s*\d+\s*", "", clean).strip()
                    if len(clean) > 300:
                        clean = clean[:297] + "..."
                    teaser = clean
                else:
                    for p in re.findall(r'<p.*?>(.*?)</p>', r.text, re.DOTALL):
                        clean = clean_html_text(p)
                        if len(clean) > 40 and not any(bad in clean.lower() for bad in ["barrierefrei", "berlin.de ist ein angebot", "kontakt zur ansprechperson", "landesbeauftragte", "impressum"]):
                            clean = re.sub(r"^Nr\.\s*\d+\s*", "", clean).strip()
                            if len(clean) > 300:
                                clean = clean[:297] + "..."
                            teaser = clean
                            break

                res = ""
                if district and teaser:
                    res = f"📍 **{district}** – {teaser}"
                elif district:
                    res = f"📍 **{district}**"
                elif teaser:
                    res = teaser

                if res:
                    _POLICE_TEASER_CACHE[url] = res
                    _POLICE_TEASER_CACHE[clean_u] = res
                    _POLICE_TEASER_CACHE[get_canonical_url(url)] = res
                    return res
        except Exception:
            pass
    return ""


def fetch_feed_items(
    feed_url: str,
    max_items: int | None = None,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    filter_ads: bool = True,
    custom_ad_keywords: list[str] | None = None,
    max_age_weeks: int | float | None = DEFAULT_MAX_ARTICLE_AGE_WEEKS,
) -> list[dict[str, Any]]:
    """Liest einen RSS- oder Atom-Feed ein, bereinigt HTML-Tags, filtert Werbung & Keywords, dedupliziert und sortiert nach Datum."""
    try:
        raw_res = fetch_feed_raw(feed_url)
        if raw_res.get("success") and raw_res.get("content"):
            parsed = feedparser.parse(raw_res["content"])
        else:
            parsed = feedparser.parse(feed_url)

        entries = getattr(parsed, "entries", [])
        if not entries and raw_res.get("content"):
            disc = autodiscover_rss_feeds(raw_res["content"], raw_res.get("final_url", feed_url))
            if disc:
                alt_res = fetch_feed_raw(disc[0]["url"])
                if alt_res.get("success") and alt_res.get("content"):
                    alt_parsed = feedparser.parse(alt_res["content"])
                    if getattr(alt_parsed, "entries", []):
                        parsed = alt_parsed
                        entries = getattr(parsed, "entries", [])

        if max_items is not None and max_items > 0:
            entries = entries[:max_items]

        norm_inc = normalize_keywords(include_keywords)
        norm_exc = normalize_keywords(exclude_keywords)

        # Spezialbehandlung für Berliner Polizei: RSS liefert standardmäßig leere description (<description><![CDATA[]]></description>)
        # Wir laden Teaser & Ort parallel im Hintergrund nach und nutzen einen persistenten Cache
        police_teasers = {}
        if "berlin.de/polizei" in feed_url:
            _load_police_cache()
            urls_to_fetch = [unwrap_and_clean_url(getattr(e, "link", "")) for e in entries if getattr(e, "link", "")]
            urls_to_fetch = [u for u in urls_to_fetch if u]

            uncached_urls = []
            for u in urls_to_fetch:
                cached = _POLICE_TEASER_CACHE.get(u) or _POLICE_TEASER_CACHE.get(get_canonical_url(u))
                if cached:
                    police_teasers[u] = cached
                else:
                    uncached_urls.append(u)

            if uncached_urls:
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                    with requests.Session() as session:
                        results = executor.map(lambda u: (u, extract_police_teaser(u, session)), uncached_urls)
                        for u, t in results:
                            if t:
                                police_teasers[u] = t
                                police_teasers[get_canonical_url(u)] = t
                                police_teasers[unwrap_and_clean_url(u)] = t
                _save_police_cache()

        seen_urls = set()
        seen_titles = set()
        items = []

        for entry in entries:
            raw_title = getattr(entry, "title", "Kein Titel")
            title = clean_html_text(raw_title)
            if not title or title.lower() == "kein titel":
                continue

            raw_link = getattr(entry, "link", "").strip()
            link = unwrap_and_clean_url(raw_link)
            canon_link = get_canonical_url(link)

            raw_summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
            summary = clean_html_text(raw_summary)

            # Bei Berliner Polizei den nachgeladenen Teaser einsetzen falls summary leer ist
            if (not summary or len(summary) < 5 or not summary.startswith("📍")):
                p_val = (
                    police_teasers.get(link) or
                    police_teasers.get(canon_link) or
                    police_teasers.get(raw_link) or
                    _POLICE_TEASER_CACHE.get(link) or
                    _POLICE_TEASER_CACHE.get(canon_link) or
                    _POLICE_TEASER_CACHE.get(raw_link) or
                    ""
                )
                if not p_val and "berlin.de/polizei" in feed_url:
                    p_val = extract_police_teaser(link)
                if p_val:
                    summary = p_val

            # 1. Stufe: Werbe- und Anzeigen-Filter (Global & quellenspezifisch)
            if filter_ads and is_ad_item(title, summary, custom_ad_keywords):
                continue

            # 2. Stufe: Feed-spezifische Keyword-Filterung
            search_corpus = f"{title} {summary}".lower()
            if norm_exc:
                if any(kw.lower() in search_corpus for kw in norm_exc):
                    continue

            if norm_inc:
                if not any(kw.lower() in search_corpus for kw in norm_inc):
                    continue

            if len(summary) > 320:
                summary = summary[:317] + "..."

            published = getattr(entry, "published", "") or getattr(entry, "updated", "")
            published_parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
            guid = getattr(entry, "id", "") or link

            timestamp = 0.0
            if published_parsed and isinstance(published_parsed, time.struct_time):
                try:
                    timestamp = float(calendar.timegm(published_parsed))
                except Exception:
                    try:
                        timestamp = float(time.mktime(published_parsed))
                    except Exception:
                        pass
            if timestamp == 0.0 and published:
                try:
                    dt = email.utils.parsedate_to_datetime(published.strip())
                    if dt:
                        timestamp = dt.timestamp()
                except Exception:
                    pass
                if timestamp == 0.0:
                    try:
                        dt = datetime.fromisoformat(published.strip().replace("Z", "+00:00"))
                        timestamp = dt.timestamp()
                    except Exception:
                        pass

            # 3. Stufe: Altersprüfung (Artikel älter als max_age_weeks Wochen herausfiltern)
            if max_age_weeks is not None and max_age_weeks > 0 and timestamp > 0.0:
                if is_article_too_old({"timestamp": timestamp}, max_age_weeks=max_age_weeks):
                    continue

            # Duplikatsprüfung innerhalb des Feeds (über Canonical URL & normalisierten Titel)
            norm_title = re.sub(r"[\W_]+", "", title.lower())
            if canon_link and canon_link in seen_urls:
                continue
            if norm_title and len(norm_title) > 12 and norm_title in seen_titles:
                continue

            if canon_link:
                seen_urls.add(canon_link)
            if norm_title and len(norm_title) > 12:
                seen_titles.add(norm_title)

            article = Article(
                title=title,
                link=link,
                summary=summary,
                published=published,
                published_parsed=published_parsed,
                timestamp=timestamp,
                guid=guid,
            )
            items.append(article.to_dict())

        # Artikel nach Datum sortieren (neueste zuerst)
        items.sort(key=lambda x: x.get("timestamp", 0.0), reverse=True)
        return items
    except Exception as e:
        logger.warning("Fehler beim Abrufen von %s: %s", feed_url, e)
        print(f"[Warnung] Fehler beim Abrufen von {feed_url}: {e}")
        return []


def collect_all_news(
    config_path: str = "config/sources.yaml",
    export_rss: bool = True,
    save_to_db: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """Sammelt alle News aus allen konfigurierten Kategorien, bereinigt Duplikate und aktualisiert optional die RSS-Feeds."""
    config = load_sources(config_path)
    settings = config.get("settings", {})
    filter_ads = settings.get("filter_ads", True)
    custom_ad_keywords = settings.get("ad_keywords", [])
    max_age_weeks_raw = settings.get("max_article_age_weeks")
    if max_age_weeks_raw is None:
        max_age_weeks_raw = settings.get("max_age_weeks", DEFAULT_MAX_ARTICLE_AGE_WEEKS)
    try:
        max_age_weeks = int(max_age_weeks_raw) if max_age_weeks_raw is not None else DEFAULT_MAX_ARTICLE_AGE_WEEKS
    except (ValueError, TypeError):
        max_age_weeks = DEFAULT_MAX_ARTICLE_AGE_WEEKS

    collected: dict[str, list[dict[str, Any]]] = {}

    # Archivierte Artikel ermitteln, damit sie nicht erneut gesammelt/angezeigt werden
    try:
        from src.storage import get_storage
        storage_inst = get_storage()
        archived_urls = storage_inst.get_archived_urls()
    except Exception as exc:
        logger.debug("Archivierte URLs konnten für Feed-Filterung nicht geladen werden: %s", exc)
        archived_urls = set()

    # Kategorien alphabetisch sortieren
    categories = sorted(config.get("categories", []), key=lambda c: c.get("name", "").strip().lower())

    # Alle Feed-Aufgaben für paralleles Einlesen vorbereiten
    feed_tasks: list[tuple[str, str, str, list[str], list[str]]] = []
    for cat in categories:
        cat_name = cat.get("name", "Allgemein")
        feeds = sorted(cat.get("feeds", []), key=lambda f: f.get("name", "").strip().lower())
        for feed in feeds:
            url = feed.get("url")
            feed_name = feed.get("name", url)
            inc_kw = feed.get("include_keywords", [])
            exc_kw = feed.get("exclude_keywords", [])
            feed_tasks.append((cat_name, feed_name, url, inc_kw, exc_kw))

    def _fetch_worker(task: tuple[str, str, str, list[str], list[str]]) -> tuple[str, str, str, list[dict[str, Any]]]:
        c_name, f_name, f_url, inc, exc = task
        try:
            items = fetch_feed_items(
                f_url,
                include_keywords=inc,
                exclude_keywords=exc,
                filter_ads=filter_ads,
                custom_ad_keywords=custom_ad_keywords,
                max_age_weeks=max_age_weeks,
            )
        except Exception as e_fetch:
            logger.warning("Fehler beim Einlesen von Feed '%s' (%s): %s", f_name, f_url, e_fetch)
            items = []
        return c_name, f_name, f_url, items

    # Paralleles Einlesen aller Feeds für maximale Performance
    fetched_map: dict[tuple[str, str], tuple[str, list[dict[str, Any]]]] = {}
    if feed_tasks:
        max_workers = min(8, len(feed_tasks))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for c_name, f_name, f_url, items in executor.map(_fetch_worker, feed_tasks):
                fetched_map[(c_name, f_name)] = (f_url, items)

    for cat in categories:
        cat_name = cat.get("name", "Allgemein")
        collected[cat_name] = []
        cat_seen_urls = set()
        cat_seen_titles = set()

        feeds = sorted(cat.get("feeds", []), key=lambda f: f.get("name", "").strip().lower())
        for feed in feeds:
            feed_name = feed.get("name", feed.get("url"))
            f_data = fetched_map.get((cat_name, feed_name))
            if f_data:
                url, items = f_data
            else:
                url = feed.get("url")
                items = []

            for it in items:
                # Zusätzliche Absicherung gegen veraltete Artikel
                if is_article_too_old(it, max_age_weeks=max_age_weeks):
                    continue

                raw_u = (it.get("link") or "").strip()
                canon_u = get_canonical_url(raw_u)

                # Gelesene & archivierte Artikel niemals erneut aufnehmen
                if (raw_u and raw_u in archived_urls) or (canon_u and canon_u in archived_urls):
                    continue

                norm_t = re.sub(r"[\W_]+", "", it.get("title", "").lower())

                # Duplikate innerhalb derselben Kategorie herausfiltern
                if canon_u and canon_u in cat_seen_urls:
                    continue
                if norm_t and len(norm_t) > 12 and norm_t in cat_seen_titles:
                    continue

                if canon_u:
                    cat_seen_urls.add(canon_u)
                if norm_t and len(norm_t) > 12:
                    cat_seen_titles.add(norm_t)

                it["source"] = feed_name
                it["source_url"] = url
                it["category"] = cat_name
                collected[cat_name].append(it)

        # Alle Artikel der Kategorie nach Datum sortieren
        collected[cat_name].sort(key=lambda x: x.get("timestamp", 0.0), reverse=True)

    if export_rss:
        try:
            from src.rss_generator import export_all_rss_feeds
            export_all_rss_feeds(collected, config=config)
        except Exception as e:
            print(f"[Hinweis] RSS-Feed-Export konnte nicht ausgeführt werden: {e}")

    # Automatisch gefundene Artikel in Turso / SQLite persistieren (sofern aktiviert)
    if save_to_db:
        try:
            from src.storage import get_storage
            storage = get_storage()
            flat_items = [it for items in collected.values() for it in items]
            if flat_items:
                storage.save_articles(flat_items)
        except Exception as e_db:
            logger.debug("DB-Persistierung in collect_all_news übersprungen: %s", e_db)

    return collected


def get_pool_state_path(state_path: str = "output/pool_state.json") -> Path:
    """Ermittelt den Pfad zur pool_state.json-Datei und stellt das Verzeichnis sicher."""
    p = Path(state_path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / state_path
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_pool_state(state_path: str = "output/pool_state.json") -> dict[str, Any]:
    """Lädt den gespeicherten Zustand der bekannten Artikel-URLs."""
    p = get_pool_state_path(state_path)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"known_urls": [], "last_count": 0, "last_updated": None}


def save_pool_state(articles_or_urls: Any, state_path: str = "output/pool_state.json") -> dict[str, Any]:
    """Speichert den aktuellen Satz bekannter Artikel-URLs persistent ab."""
    p = get_pool_state_path(state_path)
    urls = []
    if isinstance(articles_or_urls, (list, set)):
        for item in articles_or_urls:
            if isinstance(item, dict):
                u = item.get("link") or item.get("id")
                if u:
                    urls.append(str(u).strip())
            elif isinstance(item, str):
                urls.append(item.strip())
    elif isinstance(articles_or_urls, dict):
        for items in articles_or_urls.values():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        u = item.get("link") or item.get("id")
                        if u:
                            urls.append(str(u).strip())
                    elif isinstance(item, str):
                        urls.append(item.strip())

    # Dubletten entfernen unter Beibehaltung der Reihenfolge
    seen = set()
    deduped = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            deduped.append(u)

    data = {
        "known_urls": deduped,
        "last_count": len(deduped),
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Fehler beim Speichern des Pool-Status: %s", e)
        print(f"[Hinweis] Fehler beim Speichern des Pool-Status: {e}")
    return data


def get_new_articles_count(current_news: dict[str, list[dict[str, Any]]], state_path: str = "output/pool_state.json") -> int:
    """
    Ermittelt, wie viele Artikel neu hinzugekommen sind im Vergleich zum gespeicherten Pool-Zustand.
    Falls noch kein Pool-Zustand existiert, wird der aktuelle Stand als Basis initialisiert (0 neue Artikel).
    """
    p = get_pool_state_path(state_path)
    current_urls = {
        (item.get("link") or item.get("id") or "").strip()
        for items in current_news.values()
        for item in items
        if (item.get("link") or item.get("id"))
    }
    current_urls.discard("")

    if not p.exists():
        save_pool_state(current_news, state_path)
        return 0

    state = load_pool_state(state_path)
    known = set(state.get("known_urls", []))
    if not known:
        save_pool_state(current_news, state_path)
        return 0

    new_urls = current_urls - known
    return len(new_urls)




if __name__ == "__main__":
    news = collect_all_news()
    for cat, items in news.items():
        print(f"\n--- {cat} ({len(items)} Artikel) ---")
        for i in items[:3]:
            print(f"- {i['title']} [{i['source']}]")
