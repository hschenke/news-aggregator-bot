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
import html
import logging
import email.utils
import urllib.parse
from xml.sax.saxutils import escape as xml_escape
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
    items: list[dict[str, Any]],
    self_url: str | None = None,
    language: str = "de",
    category_name: str | None = None,
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


def _sort_article_key(item: dict[str, Any]) -> float:
    """Extrahiert einen Zeitstempel zur Sortierung von Artikeln."""
    ts = item.get("timestamp")
    if ts is not None and isinstance(ts, (int, float)) and ts > 0:
        return float(ts)
    p = item.get("published_parsed")
    if p and isinstance(p, time.struct_time):
        try:
            return time.mktime(p)
        except (ValueError, OverflowError):
            pass
    return 0.0


EXPOSURE_MAX_AGE_SECONDS: int = 24 * 60 * 60  # 24 Stunden


def filter_articles_last_24h(
    news_data: dict[str, list[dict[str, Any]]],
    reference_time: float | None = None,
    max_age_seconds: int = EXPOSURE_MAX_AGE_SECONDS,
) -> dict[str, list[dict[str, Any]]]:
    """
    Filtert Artikel für das RSS-Exposure (Feedly / RSS-Reader) so,
    dass ausschließlich Artikel aus den letzten 24 Stunden enthalten sind.
    """
    now_ts = time.time() if reference_time is None else reference_time
    cutoff_ts = now_ts - max_age_seconds

    filtered_news: dict[str, list[dict[str, Any]]] = {}
    for cat_name, items in news_data.items():
        recent_items = []
        for it in items:
            ts = _sort_article_key(it)
            if ts <= 0:
                try:
                    from src.aggregator import get_article_timestamp
                    ts = get_article_timestamp(it)
                except Exception:
                    pass
            # Nur Artikel aufnehmen, deren Veröffentlichungsdatum innerhalb des Zeitfensters liegt
            if ts >= cutoff_ts:
                recent_items.append(it)
        filtered_news[cat_name] = recent_items
    return filtered_news


def _resolve_feed_urls(
    config: dict[str, Any] | None,
    base_url: str | None,
) -> tuple[str, str, str, str]:
    """Ermittelt Basis-URL, CDN-Präfix, Raw-GitHub-Präfix und Streamlit-Präfix."""
    if not base_url:
        if config:
            base_url = config.get("settings", {}).get("streamlit_app_url")
        if not base_url:
            from src.summarizer import get_streamlit_app_url
            base_url = get_streamlit_app_url()
    clean_base_url = (base_url or "").rstrip("/")

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
    static_http_prefix = f"{clean_base_url}/app/static/rss"
    return clean_base_url, cdn_prefix, raw_prefix, static_http_prefix


def _export_category_feeds(
    news_data: dict[str, list[dict[str, Any]]],
    categories_cfg: list[dict[str, Any]],
    cat_dir: Path,
    cdn_prefix: str,
    raw_prefix: str,
    base_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Erzeugt die XML-Feeds für alle bekannten Kategorien."""
    all_articles: list[dict[str, Any]] = []
    category_registry: list[dict[str, Any]] = []

    if categories_cfg:
        known_cat_names = {c.get("name", "").strip() for c in categories_cfg if c.get("name", "").strip()}
    else:
        known_cat_names = {k.strip() for k in news_data.keys() if k.strip()}

    for cat_name in sorted(list(known_cat_names), key=lambda x: x.strip().lower()):
        if not cat_name:
            continue
        cat_items = sorted(news_data.get(cat_name, []), key=_sort_article_key, reverse=True)
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

    return all_articles, category_registry


def _export_source_feeds(
    news_data: dict[str, list[dict[str, Any]]],
    categories_cfg: list[dict[str, Any]],
    feed_dir: Path,
    cdn_prefix: str,
    raw_prefix: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """Erzeugt die XML-Feeds für alle einzelnen Quell-Feeds."""
    items_by_source: dict[str, list[dict[str, Any]]] = {}
    for items_list in news_data.values():
        for item in items_list:
            src = item.get("source", "Unbekannt")
            items_by_source.setdefault(src, []).append(item)

    feed_registry: list[dict[str, Any]] = []
    seen_feed_slugs: set[str] = set()
    sorted_cfg_cats = sorted(categories_cfg, key=lambda c: c.get("name", "").strip().lower())
    for cat in sorted_cfg_cats:
        cat_name = cat.get("name", "Allgemein")
        sorted_feeds = sorted(cat.get("feeds", []), key=lambda f: f.get("name", "").strip().lower())
        for f in sorted_feeds:
            f_name = f.get("name", "Unbenannt")
            f_url = f.get("url", "")
            f_slug = slugify(f"{cat_name}-{f_name}")
            if f_slug in seen_feed_slugs:
                f_slug = slugify(f"{cat_name}-{f_name}-{seen_feed_slugs}")
            seen_feed_slugs.add(f_slug)

            f_items = sorted(items_by_source.get(f_name, []), key=_sort_article_key, reverse=True)
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
    return feed_registry


def _export_global_feed(
    all_articles: list[dict[str, Any]],
    rss_root: Path,
    cdn_prefix: str,
    raw_prefix: str,
    base_url: str,
) -> dict[str, Any]:
    """Erzeugt den globalen Gesamt-Feed (all.xml)."""
    sorted_all_articles = sorted(all_articles, key=_sort_article_key, reverse=True)
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

    return {
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


def _get_briefing_registry(
    rss_root: Path,
    cdn_prefix: str,
    raw_prefix: str,
    base_url: str,
) -> dict[str, Any] | None:
    """Liest die Metadaten des briefing.xml Feeds aus, falls vorhanden."""
    briefing_file = rss_root / "briefing.xml"
    if not briefing_file.exists():
        return None
    try:
        xml_content = briefing_file.read_text(encoding="utf-8")
        item_count = xml_content.count("<item>")

        # Automatische Migration für Altdaten: Falls noch das alte 1-Item-Email-Format vorliegt
        if item_count == 1 and ("<h2>" in xml_content or "<li" in xml_content):
            try:
                migrated = export_briefing_rss(xml_content, base_url=base_url)
                if migrated and migrated.get("item_count", 0) > 1:
                    return migrated
            except Exception as e_mig:
                logger.debug("Alte briefing.xml konnte nicht automatisch migriert werden: %s", e_mig)

        return {
            "title": "Tägliches KI-Briefing",
            "slug": "briefing",
            "filename": "briefing.xml",
            "file_path": str(briefing_file),
            "url": f"{cdn_prefix}/briefing.xml",
            "cdn_url": f"{cdn_prefix}/briefing.xml",
            "raw_url": f"{raw_prefix}/briefing.xml",
            "app_url": f"{base_url}/?tab=ki",
            "item_count": item_count,
            "xml_preview": xml_content,
        }
    except Exception:
        return None


def export_all_rss_feeds(
    news_data: dict[str, list[dict[str, Any]]],
    config: dict[str, Any] | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
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

    base_url, cdn_prefix, raw_prefix, static_http_prefix = _resolve_feed_urls(config, base_url)
    categories_cfg = config.get("categories", []) if config else []

    # RSS Exposure (Feedly): Nur Artikel der letzten 24 Stunden in die Feeds aufnehmen
    exposure_news = filter_articles_last_24h(news_data)

    all_articles, category_registry = _export_category_feeds(
        exposure_news, categories_cfg, cat_dir, cdn_prefix, raw_prefix, base_url
    )
    feed_registry = _export_source_feeds(
        exposure_news, categories_cfg, feed_dir, cdn_prefix, raw_prefix, base_url
    )
    all_registry = _export_global_feed(
        all_articles, rss_root, cdn_prefix, raw_prefix, base_url
    )
    briefing_registry = _get_briefing_registry(
        rss_root, cdn_prefix, raw_prefix, base_url
    )

    return {
        "all": all_registry,
        "briefing": briefing_registry,
        "categories": category_registry,
        "feeds": feed_registry,
        "updated_at": datetime.now().strftime("%d.%m.%Y, %H:%M:%S Uhr"),
        "base_url": base_url,
        "static_http_prefix": static_http_prefix,
    }


def extract_briefing_articles(
    briefing_content: str,
    known_categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Extrahiert alle von der KI kuratierten Artikel-Links (Top 5 pro Kategorie)
    samt Titel, Kategorie und prägnanter KI-Zusammenfassung aus dem Briefing-Text
    (unterstützt Markdown und HTML).
    """
    if not briefing_content or not str(briefing_content).strip():
        return []

    from src.summarizer import _strip_executive_summaries
    clean_text = _strip_executive_summaries(briefing_content)

    articles: list[dict[str, Any]] = []
    current_cat: str = "Allgemein"
    current_article: dict[str, Any] | None = None
    seen_links: set[str] = set()

    def _normalize_category_header(header_line: str) -> str:
        raw = re.sub(r"^[#\s]+", "", header_line).strip()
        cleaned = re.sub(r"^[^\w\s&]+", "", raw).strip()
        cleaned = html.unescape(cleaned)
        if known_categories:
            for kc in known_categories:
                if kc.lower() == cleaned.lower() or kc.lower() in cleaned.lower() or cleaned.lower() in kc.lower():
                    return kc
        return cleaned or "Allgemein"

    def _is_internal_or_app_link(url: str, title: str) -> bool:
        lower_u = url.lower()
        lower_t = title.lower()
        if "streamlit.app" in lower_u or "localhost" in lower_u or "127.0.0.1" in lower_u:
            return True
        if lower_t in ("streamlit app", "app", "feed", "feeds", "weiterlesen", "link"):
            return True
        if lower_u.startswith("feed://") or lower_u.endswith(".xml"):
            return True
        return False

    for line in clean_text.splitlines():
        line_str = line.strip()
        if not line_str:
            continue

        # Kategorie-Überschrift (## oder ###)
        if line_str.startswith("##"):
            current_cat = _normalize_category_header(line_str)
            current_article = None
            continue

        # Infoboxen oder Quicklinks (> ...)
        if line_str.startswith(">"):
            current_article = None
            continue

        # Artikel-Zeile mit Markdown-Link: [Titel](URL)
        link_match = re.search(
            r"\[([^\]]+)\]\((https?://.*?)\)(?=\*{0,2}(?:\s*[:–—\-\(]|\s*$))(.*)",
            line_str,
        )
        if link_match:
            raw_title, raw_url, rest = link_match.groups()
            clean_title = html.unescape(raw_title.strip().strip("*").strip("_").strip())
            clean_url = raw_url.strip()

            if _is_internal_or_app_link(clean_url, clean_title):
                current_article = None
                continue

            rest_cleaned = re.sub(r"^\*+", "", rest).strip()
            article_summary = html.unescape(re.sub(r"^[:–—\-]\s*", "", rest_cleaned).strip())

            if clean_url not in seen_links:
                seen_links.add(clean_url)
                current_article = {
                    "category": current_cat,
                    "title": clean_title,
                    "link": clean_url,
                    "summary": article_summary,
                }
                articles.append(current_article)
            else:
                current_article = None
            continue

        # Mehrzeilige Zusammenfassungen (Fortsetzungszeilen)
        if current_article and not line_str.startswith(("-", "*", "#", ">")):
            if not re.match(r"^\d+\.\s+", line_str):
                current_article["summary"] = (current_article["summary"] + " " + html.unescape(line_str)).strip()

    # Fallback für reines HTML (falls briefing_markdown z. B. aus XML CDATA oder HTML-Export stammt)
    if not articles and ("<li" in briefing_content or "<h2" in briefing_content):
        sections = re.split(r"<h[23][^>]*>(.*?)</h[23]>", briefing_content, flags=re.IGNORECASE)
        if len(sections) > 1:
            for i in range(1, len(sections), 2):
                cat_raw = html.unescape(re.sub(r"<[^>]+>", "", sections[i]).strip())
                cat_name = _normalize_category_header(cat_raw)
                sec_html = sections[i + 1]
                li_matches = re.findall(r"<li[^>]*>(.*?)</li>", sec_html, flags=re.DOTALL | re.IGNORECASE)
                for li in li_matches:
                    a_match = re.search(
                        r"<a\s+[^>]*href=[\"'](https?://[^\"']+)[\"'][^>]*>(.*?)</a>(.*)",
                        li,
                        flags=re.DOTALL | re.IGNORECASE,
                    )
                    if a_match:
                        url, title_html, rest_html = a_match.groups()
                        title_clean = html.unescape(re.sub(r"<[^>]+>", "", title_html).strip())
                        summary_clean = html.unescape(re.sub(r"<[^>]+>", "", rest_html).strip())
                        summary_clean = re.sub(r"^[:–—\-]\s*", "", summary_clean).strip()

                        if _is_internal_or_app_link(url, title_clean):
                            continue

                        if url not in seen_links:
                            seen_links.add(url)
                            articles.append({
                                "category": cat_name,
                                "title": title_clean,
                                "link": url,
                                "summary": summary_clean,
                            })

    return articles


def export_briefing_rss(
    briefing_markdown: str,
    base_url: str | None = None,
    briefing_date_str: str | None = None,
    news_data: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """
    Erstellt oder aktualisiert den KI-Briefing RSS-Feed (static/rss/briefing.xml).
    Enthält alle von der KI kuratierten Top-Artikel (Top 5 Links pro Kategorie)
    als separate RSS-Einträge mit Original-Link und KI-Zusammenfassung.
    """
    rss_root = get_static_rss_dir()
    briefing_file_path = rss_root / "briefing.xml"

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

    cdn_url = f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/static/rss/briefing.xml"
    raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/static/rss/briefing.xml"

    if not base_url:
        from src.summarizer import get_streamlit_app_url
        base_url = get_streamlit_app_url()
    base_url = (base_url or "").rstrip("/")

    today_str = briefing_date_str or datetime.now().strftime("%d.%m.%Y")
    today_iso = datetime.now().strftime("%Y-%m-%d")

    # Extrahiere alle von der KI ausgewählten Artikel-Links
    extracted_articles = extract_briefing_articles(briefing_markdown)

    # Metadaten-Lookup aufbauen (Quelle, Veröffentlichungsdatum, Feed-URL)
    metadata_lookup: dict[str, dict[str, Any]] = {}
    if news_data:
        for items_list in news_data.values():
            for it in items_list:
                l = (it.get("link") or "").strip()
                if l:
                    metadata_lookup[l] = it
                    metadata_lookup[l.rstrip("/")] = it

    storage_inst = None
    try:
        from src.storage import get_storage
        storage_inst = get_storage()
    except Exception:
        pass

    def _find_article_meta(url: str) -> dict[str, Any] | None:
        meta = metadata_lookup.get(url) or metadata_lookup.get(url.rstrip("/"))
        if meta:
            return meta
        if storage_inst:
            try:
                db_art = storage_inst.get_article(url) or storage_inst.get_article(url.rstrip("/"))
                if db_art:
                    return {
                        "source": db_art.source,
                        "source_url": db_art.source_url,
                        "published_parsed": getattr(db_art, "published_parsed", None),
                        "timestamp": db_art.timestamp,
                        "guid": getattr(db_art, "guid", None),
                    }
            except Exception:
                pass
        return None

    feed_items: list[dict[str, Any]] = []

    if extracted_articles:
        for art in extracted_articles:
            link = art["link"]
            category = art.get("category") or "Allgemein"
            art_title = art.get("title") or "Kein Titel"
            ai_summary = art.get("summary") or ""

            # Präfix [Kategorie] im Titel für sofortigen Kontext im RSS-Reader
            if category and category != "Allgemein" and not art_title.startswith(f"[{category}]"):
                display_title = f"[{category}] {art_title}"
            else:
                display_title = art_title

            meta = _find_article_meta(link)
            pub_date = format_rfc822(datetime.now(timezone.utc))
            source_name = "KI-Briefing"
            source_url = base_url
            guid = link

            if meta:
                if meta.get("published_parsed") or meta.get("published"):
                    pub_date = format_rfc822(meta.get("published_parsed") or meta.get("published"))
                elif meta.get("timestamp"):
                    pub_date = format_rfc822(meta.get("timestamp"))
                if meta.get("source"):
                    source_name = meta["source"]
                if meta.get("source_url"):
                    source_url = meta["source_url"]
                if meta.get("guid"):
                    guid = meta["guid"]

            # Prägnante Zusammenfassung als HTML-Absatz
            if ai_summary:
                desc_html = f"<p>{ai_summary}</p>"
            else:
                desc_html = f"<p>Kuratiert im KI-Briefing ({today_str}).</p>"

            feed_items.append({
                "title": display_title,
                "link": link,
                "guid": guid,
                "published": pub_date,
                "summary": desc_html,
                "category": category,
                "source": source_name,
                "source_url": source_url,
            })
    else:
        # Fallback: Falls keine einzelnen Links extrahierbar waren, vollständigen Text abbilden
        try:
            import markdown
            briefing_html = markdown.markdown(briefing_markdown)
        except Exception:
            briefing_html = briefing_markdown.replace("\n", "<br/>")

        feed_items.append({
            "title": f"News Bot — KI-Briefing ({today_str})",
            "link": f"{base_url}/?tab=ki",
            "guid": f"briefing-{today_iso}",
            "published": format_rfc822(datetime.now(timezone.utc)),
            "summary": briefing_html,
            "category": "KI-Briefing",
            "source": "News Aggregator Bot AI",
            "source_url": base_url,
        })

    briefing_xml = generate_rss_xml(
        title="News Bot — Tägliches KI-Briefing",
        link=f"{base_url}/?tab=ki",
        description="Die von der Gemini KI kuratierten Top-Nachrichten aus allen Kategorien.",
        items=feed_items,
        self_url=cdn_url,
        category_name="KI-Briefing",
    )
    briefing_file_path.write_text(briefing_xml, encoding="utf-8")

    return {
        "title": "Tägliches KI-Briefing",
        "slug": "briefing",
        "filename": "briefing.xml",
        "file_path": str(briefing_file_path),
        "url": cdn_url,
        "cdn_url": cdn_url,
        "raw_url": raw_url,
        "app_url": f"{base_url}/?tab=ki",
        "item_count": len(feed_items),
        "xml_preview": briefing_xml,
    }
