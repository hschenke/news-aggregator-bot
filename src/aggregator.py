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


def save_sources(config: Dict[str, Any], config_path: str = "config/sources.yaml") -> None:
    """Speichert die Quellenkonfiguration persistent in sources.yaml."""
    path = get_sources_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def add_feed(
    category_name: str,
    feed_name: str,
    feed_url: str,
    max_items: int = 5,
    config_path: str = "config/sources.yaml",
) -> Dict[str, Any]:
    """
    Fügt einen neuen Feed zu einer Kategorie hinzu oder aktualisiert ihn, falls die URL bereits existiert.
    Speichert die Änderungen direkt in sources.yaml zurück.
    """
    category_name = category_name.strip()
    feed_name = feed_name.strip()
    feed_url = feed_url.strip()
    max_items = max(1, int(max_items))

    if not category_name or not feed_name or not feed_url:
        raise ValueError("Kategorie, Feed-Name und Feed-URL dürfen nicht leer sein.")

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

    save_sources(config, config_path)
    return config


def delete_feed(
    category_name: str,
    feed_url: str,
    delete_empty_category: bool = False,
    config_path: str = "config/sources.yaml",
) -> bool:
    """
    Löscht einen Feed anhand seiner Kategorie und URL aus sources.yaml.
    Gibt True zurück, wenn der Feed gefunden und gelöscht wurde.
    """
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
        save_sources(config, config_path)

    return found


def update_feed(
    category_name: str,
    old_url: str,
    new_name: str = None,
    new_url: str = None,
    new_max_items: int = None,
    config_path: str = "config/sources.yaml",
) -> bool:
    """
    Aktualisiert Name, URL und/oder max_items eines bestehenden Feeds und spiegelt dies in sources.yaml zurück.
    """
    config = load_sources(config_path)
    categories = config.get("categories", [])
    updated = False

    for cat in categories:
        if cat.get("name", "").strip().lower() == category_name.strip().lower():
            for f in cat.get("feeds", []):
                if f.get("url", "").strip() == old_url.strip():
                    if new_name is not None and new_name.strip():
                        f["name"] = new_name.strip()
                    if new_url is not None and new_url.strip():
                        f["url"] = new_url.strip()
                    if new_max_items is not None:
                        f["max_items"] = max(1, int(new_max_items))
                    updated = True
                    break
            if updated:
                break

    if updated:
        save_sources(config, config_path)

    return updated


def add_category(
    category_name: str,
    config_path: str = "config/sources.yaml",
) -> bool:
    """Fügt eine neue Kategorie ohne Feeds hinzu, falls sie noch nicht existiert."""
    category_name = category_name.strip()
    if not category_name:
        raise ValueError("Kategoriename darf nicht leer sein.")

    config = load_sources(config_path)
    categories = config.setdefault("categories", [])

    for cat in categories:
        if cat.get("name", "").strip().lower() == category_name.lower():
            return False  # existiert bereits

    categories.append({"name": category_name, "feeds": []})
    save_sources(config, config_path)
    return True


def delete_category(
    category_name: str,
    config_path: str = "config/sources.yaml",
) -> bool:
    """Löscht eine komplette Kategorie inklusive aller Feeds aus sources.yaml."""
    config = load_sources(config_path)
    categories = config.get("categories", [])
    initial_len = len(categories)
    config["categories"] = [
        c for c in categories if c.get("name", "").strip().lower() != category_name.strip().lower()
    ]
    if len(config["categories"]) < initial_len:
        save_sources(config, config_path)
        return True
    return False


def update_settings(
    new_settings: Dict[str, Any],
    config_path: str = "config/sources.yaml",
) -> None:
    """Aktualisiert den settings-Abschnitt in sources.yaml (z.B. max_articles_per_category)."""
    config = load_sources(config_path)
    settings = config.setdefault("settings", {})
    settings.update(new_settings)
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



def fetch_feed_items(feed_url: str, max_items: int = 5) -> List[Dict[str, str]]:
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

            items.append({
                "title": title,
                "link": link,
                "summary": summary
            })
        return items
    except Exception as e:
        print(f"[Warnung] Fehler beim Abrufen von {feed_url}: {e}")
        return []


def collect_all_news(config_path: str = "config/sources.yaml") -> Dict[str, List[Dict[str, str]]]:
    """Sammelt alle News aus allen konfigurierten Kategorien."""
    config = load_sources(config_path)
    collected: Dict[str, List[Dict[str, str]]] = {}

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
                collected[cat_name].append(it)
                
    return collected


if __name__ == "__main__":
    news = collect_all_news()
    for cat, items in news.items():
        print(f"\n--- {cat} ({len(items)} Artikel) ---")
        for i in items[:3]:
            print(f"- {i['title']} [{i['source']}]")
