import os
import json
import base64
import re
import html
import urllib.parse
import requests
import feedparser
import yaml
import calendar
import email.utils
import time
import concurrent.futures
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path


def get_sources_path(config_path: str = "config/sources.yaml") -> Path:
    """Ermittelt den absoluten Pfad zur sources.yaml-Datei."""
    path = Path(config_path)
    if not path.is_absolute():
        root_path = Path(__file__).resolve().parent.parent / config_path
        if root_path.exists() or not path.exists():
            return root_path
    return path


def get_github_sync_config() -> Dict[str, str]:
    """Liest GitHub Sync Konfiguration aus Umgebungsvariablen oder Streamlit Secrets."""
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    repo = os.getenv("GITHUB_REPO", "hschenke/news-aggregator-bot")
    branch = os.getenv("GITHUB_BRANCH", "main")

    if not token:
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
    config_dict: Dict[str, Any] = None,
    config_path: str = "config/sources.yaml",
    commit_message: str = "chore(config): update sources.yaml and RSS feeds via web dashboard",
    include_rss_feeds: bool = True
) -> Dict[str, Any]:
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


def trigger_rss_update_workflow() -> Dict[str, Any]:
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



def load_sources(config_path: str = "config/sources.yaml") -> Dict[str, Any]:
    """Lädt die Konfiguration aus sources.yaml und garantiert alphabetische Kategoriensortierung."""
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

    return data


def save_sources(
    config: Dict[str, Any],
    config_path: str = "config/sources.yaml",
    sync_github: bool = True
) -> Dict[str, Any]:
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
    max_items: int = None,
    config_path: str = "config/sources.yaml",
    config: Dict[str, Any] = None,
    save_to_disk: bool = True,
    include_keywords: Any = None,
    exclude_keywords: Any = None,
    **kwargs
) -> Dict[str, Any]:
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
    config: Dict[str, Any] = None,
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
    new_name: str = None,
    new_url: str = None,
    new_max_items: int = None,
    new_category: str = None,
    config_path: str = "config/sources.yaml",
    config: Dict[str, Any] = None,
    save_to_disk: bool = True,
    include_keywords: Any = None,
    exclude_keywords: Any = None,
    **kwargs
) -> bool:
    """
    Aktualisiert Name, URL, Keywords und/oder Kategorie eines bestehenden Feeds.
    """
    if config is None:
        config = load_sources(config_path)
    categories = config.get("categories", [])
    updated = False
    feed_to_move = None

    for cat in categories:
        if cat.get("name", "").strip().lower() == category_name.strip().lower():
            feeds = cat.get("feeds", [])
            for f in feeds:
                if f.get("url", "").strip() == old_url.strip():
                    if new_name is not None and new_name.strip():
                        f["name"] = new_name.strip()
                    if new_url is not None and new_url.strip():
                        f["url"] = new_url.strip()
                    f.pop("max_items", None)

                    if include_keywords is not None:
                        norm_inc = normalize_keywords(include_keywords)
                        if norm_inc:
                            f["include_keywords"] = norm_inc
                        else:
                            f.pop("include_keywords", None)

                    if exclude_keywords is not None:
                        norm_exc = normalize_keywords(exclude_keywords)
                        if norm_exc:
                            f["exclude_keywords"] = norm_exc
                        else:
                            f.pop("exclude_keywords", None)

                    updated = True

                    if new_category and new_category.strip().lower() != category_name.strip().lower():
                        feed_to_move = dict(f)
                        cat["feeds"] = [x for x in feeds if x.get("url", "").strip() != old_url.strip()]
                    break
            if updated:
                break

    if updated:
        if feed_to_move and new_category:
            target_cat = None
            for c in categories:
                if c.get("name", "").strip().lower() == new_category.strip().lower():
                    target_cat = c
                    break
            if not target_cat:
                target_cat = {"name": new_category.strip(), "feeds": []}
                categories.append(target_cat)
            target_cat.setdefault("feeds", []).append(feed_to_move)

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
    config: Dict[str, Any] = None,
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
    config: Dict[str, Any] = None,
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
    config: Dict[str, Any] = None,
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
    new_settings: Dict[str, Any],
    config_path: str = "config/sources.yaml",
    config: Dict[str, Any] = None,
    save_to_disk: bool = True,
) -> None:
    """Aktualisiert den settings-Abschnitt in sources.yaml oder im config-Objekt."""
    if config is None:
        config = load_sources(config_path)
    settings = config.setdefault("settings", {})
    settings.update(new_settings)
    if save_to_disk:
        save_sources(config, config_path)


def test_feed_connection(feed_url: str, timeout: int = 8) -> Dict[str, Any]:
    """Testet die Erreichbarkeit und Validität einer Feed-URL."""
    feed_url = feed_url.strip()
    if not feed_url:
        return {"success": False, "error": "URL ist leer."}

    if not (feed_url.startswith("http://") or feed_url.startswith("https://")):
        return {"success": False, "error": "URL muss mit http:// oder https:// beginnen."}

    try:
        import urllib.request
        req = urllib.request.Request(
            feed_url,
            headers={"User-Agent": "NewsAggregatorBot/1.0 (+https://github.com)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        parsed = feedparser.parse(data)

        entries = getattr(parsed, "entries", [])
        feed_title = parsed.feed.get("title", "Unbekannter Titel") if hasattr(parsed, "feed") else "Unbekannter Titel"

        if not entries and hasattr(parsed, "bozo") and parsed.bozo:
            bozo_exc = getattr(parsed, "bozo_exception", "Unbekannter Parsing-Fehler")
            return {"success": False, "error": f"Fehler beim Parsen des Feeds: {bozo_exc}"}

        latest_title = entries[0].get("title", "Kein Titel") if entries else "Keine Artikel vorhanden"
        return {
            "success": True,
            "title": feed_title,
            "item_count": len(entries),
            "latest_title": latest_title,
            "error": None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}



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


def normalize_keywords(kw: Any) -> List[str]:
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
    r"\bdeal(?:s)? des tages\b",
    r"^rabatt-aktion\b",
]


def is_ad_item(title: str, summary: str = "", custom_ad_keywords: Optional[List[str]] = None) -> bool:
    """Prüft, ob ein Artikel Werbung, Anzeige, gesponsertes Angebot oder Deal ist."""
    t_clean = (title or "").strip().lower()
    s_clean = (summary or "").strip().lower()

    for pat in DEFAULT_AD_PATTERNS:
        if re.search(pat, t_clean, re.IGNORECASE):
            return True

    if custom_ad_keywords:
        for kw in custom_ad_keywords:
            k = kw.strip().lower()
            if k and (k in t_clean or k in s_clean):
                return True

    return False


def extract_police_teaser(url: str, session: Optional[requests.Session] = None) -> str:
    """Extrahiert den Teaser-Text und Ereignisort einer Berliner Polizeimeldung aus dem HTML-Body."""
    if not url or "berlin.de/polizei" not in url:
        return ""
    try:
        s = session or requests
        r = s.get(
            url,
            timeout=4.0,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NewsAggregatorBot/1.0"}
        )
        if r.status_code == 200:
            m = re.search(r'<p>\s*<strong>Nr\.\s*\d+</strong><br>(.*?)</p>', r.text, re.DOTALL)
            if m:
                clean = clean_html_text(m.group(1))
                if len(clean) > 320:
                    clean = clean[:317] + "..."
                return clean
    except Exception:
        pass
    return ""


def fetch_feed_items(
    feed_url: str,
    max_items: int = None,
    include_keywords: Optional[List[str]] = None,
    exclude_keywords: Optional[List[str]] = None,
    filter_ads: bool = True,
    custom_ad_keywords: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Liest einen RSS- oder Atom-Feed ein, bereinigt HTML-Tags, filtert Werbung & Keywords, dedupliziert und sortiert nach Datum."""
    try:
        parsed = feedparser.parse(feed_url)
        entries = getattr(parsed, "entries", [])
        if max_items is not None and max_items > 0:
            entries = entries[:max_items]

        norm_inc = normalize_keywords(include_keywords)
        norm_exc = normalize_keywords(exclude_keywords)

        # Spezialbehandlung für Berliner Polizei: RSS liefert standardmäßig leere description (<description><![CDATA[]]></description>)
        # Wir laden Teaser & Ort parallel im Hintergrund nach (Dauer ca. 0.4s)
        police_teasers = {}
        if "berlin.de/polizei" in feed_url:
            urls_to_fetch = [unwrap_and_clean_url(getattr(e, "link", "")) for e in entries if getattr(e, "link", "")]
            urls_to_fetch = [u for u in urls_to_fetch if u]
            if urls_to_fetch:
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                    with requests.Session() as session:
                        results = executor.map(lambda u: (u, extract_police_teaser(u, session)), urls_to_fetch)
                        for u, t in results:
                            if t:
                                police_teasers[u] = t

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
            if (not summary or len(summary) < 5) and link in police_teasers:
                summary = police_teasers[link]

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

            items.append({
                "title": title,
                "link": link,
                "summary": summary,
                "published": published,
                "published_parsed": published_parsed,
                "timestamp": timestamp,
                "guid": guid,
            })

        # Artikel nach Datum sortieren (neueste zuerst)
        items.sort(key=lambda x: x.get("timestamp", 0.0), reverse=True)
        return items
    except Exception as e:
        print(f"[Warnung] Fehler beim Abrufen von {feed_url}: {e}")
        return []


def collect_all_news(config_path: str = "config/sources.yaml", export_rss: bool = True) -> Dict[str, List[Dict[str, Any]]]:
    """Sammelt alle News aus allen konfigurierten Kategorien, bereinigt Duplikate und aktualisiert optional die RSS-Feeds."""
    config = load_sources(config_path)
    settings = config.get("settings", {})
    filter_ads = settings.get("filter_ads", True)
    custom_ad_keywords = settings.get("ad_keywords", [])

    collected: Dict[str, List[Dict[str, Any]]] = {}

    # Kategorien alphabetisch sortieren
    categories = sorted(config.get("categories", []), key=lambda c: c.get("name", "").strip().lower())

    for cat in categories:
        cat_name = cat.get("name", "Allgemein")
        collected[cat_name] = []
        cat_seen_urls = set()
        cat_seen_titles = set()

        # Feeds alphabetisch sortieren
        feeds = sorted(cat.get("feeds", []), key=lambda f: f.get("name", "").strip().lower())
        for feed in feeds:
            url = feed.get("url")
            feed_name = feed.get("name", url)
            inc_kw = feed.get("include_keywords", [])
            exc_kw = feed.get("exclude_keywords", [])

            items = fetch_feed_items(
                url,
                include_keywords=inc_kw,
                exclude_keywords=exc_kw,
                filter_ads=filter_ads,
                custom_ad_keywords=custom_ad_keywords,
            )
            for it in items:
                canon_u = get_canonical_url(it.get("link", ""))
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
                
    return collected


def get_pool_state_path(state_path: str = "output/pool_state.json") -> Path:
    """Ermittelt den Pfad zur pool_state.json-Datei und stellt das Verzeichnis sicher."""
    p = Path(state_path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / state_path
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_pool_state(state_path: str = "output/pool_state.json") -> Dict[str, Any]:
    """Lädt den gespeicherten Zustand der bekannten Artikel-URLs."""
    p = get_pool_state_path(state_path)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"known_urls": [], "last_count": 0, "last_updated": None}


def save_pool_state(articles_or_urls: Any, state_path: str = "output/pool_state.json") -> Dict[str, Any]:
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
        print(f"[Hinweis] Fehler beim Speichern des Pool-Status: {e}")
    return data


def get_new_articles_count(current_news: Dict[str, List[Dict[str, Any]]], state_path: str = "output/pool_state.json") -> int:
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
