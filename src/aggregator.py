import os
import base64
import requests
import feedparser
import yaml
from datetime import datetime, timezone
from typing import List, Dict, Any
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
    commit_message: str = "chore(config): update sources.yaml via web dashboard"
) -> Dict[str, Any]:
    """
    Pusht die aktuelle sources.yaml direkt per GitHub Contents API in das Repository.
    Gibt {'success': True, 'commit_url': ...} oder {'success': False, 'error': ...} zurück.
    """
    gh_cfg = get_github_sync_config()
    token = gh_cfg["token"]
    if not token or token.startswith("your_"):
        return {"success": False, "error": "Kein GITHUB_TOKEN hinterlegt."}

    repo = gh_cfg["repo"]
    branch = gh_cfg["branch"]
    rel_path = "config/sources.yaml"

    try:
        if config_dict is not None:
            yaml_content = yaml.dump(config_dict, allow_unicode=True, sort_keys=False, default_flow_style=False)
        else:
            file_path = get_sources_path(config_path)
            with open(file_path, "r", encoding="utf-8") as f:
                yaml_content = f.read()

        url = f"https://api.github.com/repos/{repo}/contents/{rel_path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        # Aktuellen SHA der Datei auf GitHub ermitteln
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
            return {"success": True, "commit_url": html_url, "error": None}
        else:
            return {"success": False, "commit_url": None, "error": f"Status {put_res.status_code}: {put_res.text}"}
    except Exception as e:
        return {"success": False, "commit_url": None, "error": str(e)}


def load_sources(config_path: str = "config/sources.yaml") -> Dict[str, Any]:
    """Lädt die Konfiguration aus sources.yaml."""
    path = get_sources_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Konfigurationsdatei {path} nicht gefunden.")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "categories" not in data:
        data["categories"] = []
    if "settings" not in data:
        data["settings"] = {}
    return data


def save_sources(
    config: Dict[str, Any],
    config_path: str = "config/sources.yaml",
    sync_github: bool = True
) -> Dict[str, Any]:
    """Speichert die Quellenkonfiguration persistent in sources.yaml und synchronisiert mit GitHub (falls konfiguriert)."""
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
    max_items: int = 5,
    config_path: str = "config/sources.yaml",
    config: Dict[str, Any] = None,
    save_to_disk: bool = True,
) -> Dict[str, Any]:
    """
    Fügt einen neuen Feed zu einer Kategorie hinzu oder aktualisiert ihn, falls die URL bereits existiert.
    Speichert die Änderungen in sources.yaml zurück, falls save_to_disk=True.
    """
    category_name = category_name.strip()
    feed_name = feed_name.strip()
    feed_url = feed_url.strip()
    max_items = max(1, int(max_items))

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
        "max_items": max_items,
    }

    if existing_feed:
        existing_feed.update(new_feed_obj)
    else:
        feeds.append(new_feed_obj)

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
) -> bool:
    """
    Aktualisiert Name, URL, max_items und/oder Kategorie eines bestehenden Feeds.
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
                    if new_max_items is not None:
                        f["max_items"] = max(1, int(new_max_items))
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

    if found and save_to_disk:
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



def fetch_feed_items(feed_url: str, max_items: int = 5) -> List[Dict[str, Any]]:
    """Liest einen RSS- oder Atom-Feed ein und gibt relevante Artikel zurück."""
    try:
        parsed = feedparser.parse(feed_url)
        items = []
        for entry in parsed.entries[:max_items]:
            title = getattr(entry, "title", "Kein Titel").strip()
            link = getattr(entry, "link", "").strip()
            summary = getattr(entry, "summary", "")
            
            # Einfache HTML-Tags grob bereinigen falls vorhanden
            if summary:
                import re
                summary = re.sub(r"<[^>]+>", "", summary).strip()
                if len(summary) > 300:
                    summary = summary[:297] + "..."

            published = getattr(entry, "published", "") or getattr(entry, "updated", "")
            published_parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
            guid = getattr(entry, "id", "") or link

            items.append({
                "title": title,
                "link": link,
                "summary": summary,
                "published": published,
                "published_parsed": published_parsed,
                "guid": guid,
            })
        return items
    except Exception as e:
        print(f"[Warnung] Fehler beim Abrufen von {feed_url}: {e}")
        return []


def collect_all_news(config_path: str = "config/sources.yaml", export_rss: bool = True) -> Dict[str, List[Dict[str, Any]]]:
    """Sammelt alle News aus allen konfigurierten Kategorien und aktualisiert optional die RSS-Feeds."""
    config = load_sources(config_path)
    collected: Dict[str, List[Dict[str, Any]]] = {}

    for cat in config.get("categories", []):
        cat_name = cat.get("name", "Allgemein")
        collected[cat_name] = []
        for feed in cat.get("feeds", []):
            url = feed.get("url")
            max_items = feed.get("max_items", 5)
            feed_name = feed.get("name", url)
            
            items = fetch_feed_items(url, max_items)
            for it in items:
                it["source"] = feed_name
                it["source_url"] = url
                it["category"] = cat_name
                collected[cat_name].append(it)

    if export_rss:
        try:
            from src.rss_generator import export_all_rss_feeds
            export_all_rss_feeds(collected, config=config)
        except Exception as e:
            print(f"[Hinweis] RSS-Feed-Export konnte nicht ausgeführt werden: {e}")
                
    return collected



if __name__ == "__main__":
    news = collect_all_news()
    for cat, items in news.items():
        print(f"\n--- {cat} ({len(items)} Artikel) ---")
        for i in items[:3]:
            print(f"- {i['title']} [{i['source']}]")
