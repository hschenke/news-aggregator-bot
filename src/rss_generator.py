"""
Modul zur Erzeugung und Bereitstellung von RSS 2.0 Feeds für den News Aggregator Bot.
Ermöglicht das Bereitstellen von:
- Gesamt-Feed (alle aggregierten Artikel über alle Kategorien)
- Kategorie-Feeds (für jede einzelne Kategorie)
- Einzel-Feeds (für jeden spezifischen RSS-Quell-Feed)
Dateien werden im statischen Verzeichnis von Streamlit abgelegt (static/rss/...)
und können so direkt über HTTP von RSS-Readern (NetNewsWire, Feedly, Thunderbird, etc.)
abonniert werden.
"""

import os
import re
import time
import email.utils
import urllib.parse
from xml.sax.saxutils import escape as xml_escape
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional


def slugify(text: str) -> str:
    """Wandelt einen Text in einen sauberen, URL-tauglichen Slug um (inkl. deutscher Umlaute)."""
    text = (text or "").strip()
    replacements = {
        "ä": "ae", "ö": "oe", "ü": "ue",
        "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
        "ß": "ss", "&": "und"
    }
    for search, replace in replacements.items():
        text = text.replace(search, replace)
    text = re.sub(r"[^a-zA-Z0-9_\-\s]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-").lower()
    return text or "feed"


def format_rfc822(date_input: Any = None) -> str:
    """Formatiert verschiedene Datums-Eingaben (struct_time, float, datetime, str) in valides RFC-822."""
    if date_input is None:
        return email.utils.formatdate(time.time(), usegmt=True)

    if isinstance(date_input, (int, float)):
        return email.utils.formatdate(date_input, usegmt=True)

    if isinstance(date_input, time.struct_time):
        try:
            ts = time.mktime(date_input)
            return email.utils.formatdate(ts, usegmt=True)
        except Exception:
            return email.utils.formatdate(time.time(), usegmt=True)

    if isinstance(date_input, datetime):
        if date_input.tzinfo is None:
            date_input = date_input.replace(tzinfo=timezone.utc)
        return email.utils.format_datetime(date_input)

    if isinstance(date_input, str) and date_input.strip():
        # Falls bereits im RFC-Format vorliegt
        s = date_input.strip()
        try:
            parsed = email.utils.parsedate_to_datetime(s)
            if parsed:
                return email.utils.format_datetime(parsed)
        except Exception:
            pass

    return email.utils.formatdate(time.time(), usegmt=True)


def get_static_rss_dir() -> Path:
    """Gibt das absolute Verzeichnis für statische RSS-Feeds zurück."""
    root_dir = Path(__file__).resolve().parent.parent
    static_dir = root_dir / "static" / "rss"
    static_dir.mkdir(parents=True, exist_ok=True)
    return static_dir


def generate_rss_xml(
    title: str,
    link: str,
    description: str,
    items: List[Dict[str, Any]],
    self_url: Optional[str] = None,
    language: str = "de",
    category_name: Optional[str] = None,
) -> str:
    """
    Erstellt ein standardkonformes RSS 2.0 XML Dokument mit Atom Self-Link.
    """
    now_rfc = format_rfc822()
    safe_title = xml_escape(title)
    safe_link = xml_escape(link)
    safe_desc = xml_escape(description)
    safe_lang = xml_escape(language or "de")

    atom_link_tag = ""
    if self_url:
        safe_self_url = xml_escape(self_url)
        atom_link_tag = f'\n    <atom:link href="{safe_self_url}" rel="self" type="application/rss+xml" />'

    items_xml_list = []
    for item in items:
        item_title = xml_escape(item.get("title", "Kein Titel").strip())
        item_link = xml_escape(item.get("link", "").strip())
        raw_guid = item.get("guid") or item.get("link") or f"{title}_{item_title}"
        safe_guid = xml_escape(str(raw_guid).strip())
        
        # Datumsermittlung
        pub_raw = item.get("published_parsed") or item.get("published")
        item_pub_date = format_rfc822(pub_raw)

        # Bereinigte Zusammenfassung in CDATA einbetten
        raw_summary = item.get("summary", "") or ""
        # CDATA-Endmarkierungen entschärfen
        safe_summary = raw_summary.replace("]]>", "]]&gt;")
        
        item_cat = xml_escape(item.get("category") or category_name or "")
        cat_tag = f"\n      <category>{item_cat}</category>" if item_cat else ""
        
        item_source = xml_escape(item.get("source") or "")
        source_url = xml_escape(item.get("source_url") or "")
        if item_source:
            if source_url:
                source_tag = f'\n      <source url="{source_url}">{item_source}</source>'
            else:
                source_tag = f'\n      <source>{item_source}</source>'
        else:
            source_tag = ""

        item_xml = f"""    <item>
      <title>{item_title}</title>
      <link>{item_link}</link>
      <guid isPermaLink="false">{safe_guid}</guid>
      <pubDate>{item_pub_date}</pubDate>{cat_tag}{source_tag}
      <description><![CDATA[{safe_summary}]]></description>
    </item>"""
        items_xml_list.append(item_xml)

    items_block = "\n".join(items_xml_list)

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{safe_title}</title>
    <link>{safe_link}</link>
    <description>{safe_desc}</description>
    <language>{safe_lang}</language>
    <lastBuildDate>{now_rfc}</lastBuildDate>
    <generator>News Aggregator Bot RSS Engine</generator>{atom_link_tag}
{items_block}
  </channel>
</rss>
"""
    return xml_content.strip()


def export_all_rss_feeds(
    news_data: Dict[str, List[Dict[str, Any]]],
    config: Optional[Dict[str, Any]] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Erzeugt alle RSS-Dateien im Verzeichnis static/rss/ und liefert ein Verzeichnis (Registry) zurück.
    Erstellte Feeds:
    1. Gesamt-Feed: static/rss/all.xml
    2. Kategorie-Feeds: static/rss/kategorien/<cat_slug>.xml
    3. Einzel-Feeds: static/rss/feeds/<feed_slug>.xml
    """
    rss_root = get_static_rss_dir()
    cat_dir = rss_root / "kategorien"
    feed_dir = rss_root / "feeds"
    cat_dir.mkdir(parents=True, exist_ok=True)
    feed_dir.mkdir(parents=True, exist_ok=True)

    # Basis-URL ermitteln
    if not base_url:
        if config:
            base_url = config.get("settings", {}).get("streamlit_app_url")
        if not base_url:
            from src.summarizer import get_streamlit_app_url
            base_url = get_streamlit_app_url()
    base_url = (base_url or "").rstrip("/")

    # Streamlit serviert Dateien unter /app/static/...
    static_http_prefix = f"{base_url}/app/static/rss"

    # GitHub / CDN URLs für 100%ige Verfügbarkeit (ohne Streamlit Cloud Standby)
    repo = "hschenke/news-aggregator-bot"
    branch = "main"
    try:
        from src.aggregator import get_github_sync_config
        gh_cfg = get_github_sync_config()
        if gh_cfg.get("repo"):
            repo = gh_cfg["repo"]
        if gh_cfg.get("branch"):
            branch = gh_cfg["branch"]
    except Exception:
        pass

    cdn_prefix = f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/static/rss"
    raw_prefix = f"https://raw.githubusercontent.com/{repo}/{branch}/static/rss"

    all_articles: List[Dict[str, Any]] = []
    category_registry = []
    feed_registry = []

    # 1. Kategorie-Feeds erstellen
    categories_cfg = config.get("categories", []) if config else []
    
    # Alle Kategorien durchgehen (sowohl aus config als auch aus geladenen news_data)
    known_cat_names = set(news_data.keys())
    for c in categories_cfg:
        known_cat_names.add(c.get("name", "").strip())

    for cat_name in sorted(list(known_cat_names)):
        if not cat_name:
            continue
        cat_items = news_data.get(cat_name, [])
        all_articles.extend(cat_items)

        cat_slug = slugify(cat_name)
        cat_filename = f"{cat_slug}.xml"
        cat_file_path = cat_dir / cat_filename
        cat_cdn_url = f"{cdn_prefix}/kategorien/{cat_filename}"
        cat_raw_url = f"{raw_prefix}/kategorien/{cat_filename}"
        cat_param = urllib.parse.quote_plus(cat_name)
        cat_app_view_url = f"{base_url}/?category={cat_param}"

        cat_xml = generate_rss_xml(
            title=f"News Bot — {cat_name}",
            link=cat_app_view_url,
            description=f"Aggregierte Nachrichten für die Kategorie '{cat_name}' aus dem News Aggregator Bot.",
            items=cat_items,
            self_url=cat_cdn_url,
            category_name=cat_name,
        )
        cat_file_path.write_text(cat_xml, encoding="utf-8")

        # Anzahl konfigurierter Feeds in dieser Kategorie ermitteln
        cfg_feed_count = 0
        for c in categories_cfg:
            if c.get("name", "").strip().lower() == cat_name.lower():
                cfg_feed_count = len(c.get("feeds", []))
                break

        category_registry.append({
            "name": cat_name,
            "slug": cat_slug,
            "filename": f"kategorien/{cat_filename}",
            "file_path": str(cat_file_path),
            "url": cat_cdn_url,
            "cdn_url": cat_cdn_url,
            "raw_url": cat_raw_url,
            "app_url": cat_app_view_url,
            "item_count": len(cat_items),
            "feed_count": cfg_feed_count or len(set(i.get("source", "") for i in cat_items if i.get("source"))),
            "xml_preview": cat_xml,
        })



    # 2. Einzelne Feeds erstellen (nach Quell-Feed gegliedert)
    # Gruppierung aller geladenen Artikel nach Source
    items_by_source: Dict[str, List[Dict[str, Any]]] = {}
    for items_list in news_data.values():
        for item in items_list:
            src = item.get("source", "Unbekannt")
            items_by_source.setdefault(src, []).append(item)

    # Feeds aus config abgleichen
    seen_feed_slugs = set()
    for cat in categories_cfg:
        cat_name = cat.get("name", "Allgemein")
        for f in cat.get("feeds", []):
            f_name = f.get("name", "Unbenannt")
            f_url = f.get("url", "")
            f_slug = slugify(f"{cat_name}-{f_name}")
            if f_slug in seen_feed_slugs:
                f_slug = slugify(f"{cat_name}-{f_name}-{seen_feed_slugs}")
            seen_feed_slugs.add(f_slug)

            f_items = items_by_source.get(f_name, [])
            f_filename = f"{f_slug}.xml"
            f_file_path = feed_dir / f_filename
            f_cdn_url = f"{cdn_prefix}/feeds/{f_filename}"
            f_raw_url = f"{raw_prefix}/feeds/{f_filename}"
            c_param = urllib.parse.quote_plus(cat_name)
            f_param = urllib.parse.quote_plus(f_name)
            f_app_view_url = f"{base_url}/?category={c_param}&feed={f_param}"

            f_xml = generate_rss_xml(
                title=f"News Bot — {f_name} ({cat_name})",
                link=f_app_view_url,
                description=f"RSS-Feed für die Quelle '{f_name}' (Kategorie: {cat_name}).",
                items=f_items,
                self_url=f_cdn_url,
                category_name=cat_name,
            )
            f_file_path.write_text(f_xml, encoding="utf-8")

            feed_registry.append({
                "name": f_name,
                "category": cat_name,
                "slug": f_slug,
                "original_url": f_url,
                "filename": f"feeds/{f_filename}",
                "file_path": str(f_file_path),
                "url": f_cdn_url,
                "cdn_url": f_cdn_url,
                "raw_url": f_raw_url,
                "app_url": f_app_view_url,
                "item_count": len(f_items),
                "xml_preview": f_xml,
            })

    # 3. Gesamt-Feed erstellen (Alle Nachrichten)
    # Sortieren nach Datum (falls vorhanden) oder beibehalten
    def sort_key(it):
        p = it.get("published_parsed")
        if p and isinstance(p, time.struct_time):
            try:
                return time.mktime(p)
            except Exception:
                pass
        return 0.0

    sorted_all_articles = sorted(all_articles, key=sort_key, reverse=True)
    all_filename = "all.xml"
    all_file_path = rss_root / all_filename
    all_cdn_url = f"{cdn_prefix}/{all_filename}"
    all_raw_url = f"{raw_prefix}/{all_filename}"

    all_xml = generate_rss_xml(
        title="News Bot — Alle Nachrichten (Gesamt-Feed)",
        link=base_url,
        description="Alle aggregierten Nachrichten aus sämtlichen Kategorien und Quellen im News Aggregator Bot.",
        items=sorted_all_articles,
        self_url=all_cdn_url,
    )
    all_file_path.write_text(all_xml, encoding="utf-8")

    all_registry = {
        "title": "Alle Nachrichten (Gesamt-Feed)",
        "slug": "all",
        "filename": all_filename,
        "file_path": str(all_file_path),
        "url": all_cdn_url,
        "cdn_url": all_cdn_url,
        "raw_url": all_raw_url,
        "app_url": base_url,
        "item_count": len(sorted_all_articles),
        "xml_preview": all_xml,
    }



    return {
        "all": all_registry,
        "categories": category_registry,
        "feeds": feed_registry,
        "updated_at": datetime.now().strftime("%d.%m.%Y, %H:%M:%S Uhr"),
        "base_url": base_url,
        "static_http_prefix": static_http_prefix,
    }
