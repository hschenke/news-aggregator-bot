import feedparser
import yaml
from datetime import datetime, timezone
from typing import List, Dict, Any
from pathlib import Path


def load_sources(config_path: str = "config/sources.yaml") -> Dict[str, Any]:
    path = Path(config_path)
    if not path.is_absolute() and not path.exists():
        # Fallback auf Projekt-Root basierend auf Dateipfad
        root_path = Path(__file__).resolve().parent.parent / config_path
        if root_path.exists():
            path = root_path
    if not path.exists():
        raise FileNotFoundError(f"Konfigurationsdatei {config_path} nicht gefunden.")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
