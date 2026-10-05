"""
News Aggregator Orchestrator für den News Aggregator Bot.
Sammelt und verarbeitet Nachrichten aus konfigurierten RSS/Atom-Quellen,
orchestriert Filterung, Deduplizierung, paralleles Parsing und Static Feed Exports.

Dieses Modul dient zugleich als abwärtskompatible Fassade für:
- src.filters: Text-Bereinigung, URL-Kanonisierung, Werbe- und Altersfilter
- src.feed_fetcher: Raw HTTP-Feed-Download, Typ-Erkennung und Verbindungstests
- src.sources_manager: sources.yaml Konfiguration, CRUD und GitHub-Synchronisation
- src.police_scraper: Ereignisort- und Teaser-Extraktion für Berliner Polizeimeldungen
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser
import requests  # Erforderlich für Abwärtskompatibilität und Test-Mocking

from src.models import Article
from src.exceptions import NewsAggregatorError, ConfigurationError, FeedFetchError

# Re-Exports aus Submodulen für 100% Abwärtskompatibilität
from src.filters import (
    DEFAULT_AD_PATTERNS,
    DEFAULT_MAX_ARTICLE_AGE_HOURS,
    DEFAULT_MAX_ARTICLE_AGE_SECONDS,
    DEFAULT_ARCHIVE_RETENTION_DAYS,
    DEFAULT_MAX_ARTICLE_AGE_WEEKS,
    SECONDS_PER_HOUR,
    SECONDS_PER_DAY,
    SECONDS_PER_WEEK,
    clean_html_text,
    format_summary_html,
    unwrap_and_clean_url,
    get_canonical_url,
    normalize_keywords,
    is_ad_item,
    get_article_timestamp,
    is_article_too_old,
    filter_articles_by_age,
    filter_news_data_by_age,
)

from src.feed_fetcher import (
    FEED_REQUEST_HEADERS_READER,
    FEED_REQUEST_HEADERS_BOT,
    FEED_REQUEST_HEADERS_BROWSER,
    determine_stream_type,
    autodiscover_rss_feeds,
    fetch_feed_raw,
    test_feed_connection,
)

from src.police_scraper import (
    _POLICE_TEASER_CACHE,
    _POLICE_CACHE_FILE,
    _load_police_cache,
    _save_police_cache,
    extract_police_teaser,
)

from src.sources_manager import (
    get_streamlit_app_url,
    get_sources_path,
    get_github_sync_config,
    sync_sources_to_github,
    trigger_rss_update_workflow,
    purge_jsdelivr_cache,
    reconcile_prompt_templates,
    load_sources,
    save_sources,
    add_feed,
    delete_feed,
    update_feed,
    rename_category,
    add_category,
    delete_category,
    update_settings,
)

logger = logging.getLogger(__name__)


def fetch_feed_items(
    feed_url: str,
    max_items: int | None = None,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    filter_ads: bool = True,
    custom_ad_keywords: list[str] | None = None,
    max_age_hours: float | None = DEFAULT_MAX_ARTICLE_AGE_HOURS,
    max_age_weeks: int | float | None = None,
) -> list[dict[str, Any]]:
    """Liest einen RSS- oder Atom-Feed ein, bereinigt HTML-Tags, filtert Werbung & Keywords, dedupliziert und sortiert nach Datum."""
    try:
        # fetch_feed_raw über Modulnamespace aufrufen (wichtig für Unittest-Mocks)
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

            # Bereinigung störender Navigations- und Header-Artefakte in Teasern (z. B. all-ai.de)
            if summary and ("kurzfassung" in summary.lower() or summary.startswith("GPT-Images")):
                summary = re.sub(
                    r"^(?:GPT-Images-[\d\.]+\s*)?(?:Kurzfassung\s*[▾▿▸]\s*Quellen\s*[▾▿▸]\s*)?",
                    "",
                    summary,
                    flags=re.IGNORECASE,
                ).strip()

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

            timestamp = get_article_timestamp(entry)

            # 3. Stufe: Altersprüfung (Artikel älter als 24 Stunden herausfiltern)
            if timestamp > 0.0 and is_article_too_old({"timestamp": timestamp}, max_age_hours=max_age_hours, max_age_weeks=max_age_weeks):
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
    # load_sources über Modulnamespace aufrufen (wichtig für Unittest-Mocks)
    config = load_sources(config_path)
    settings = config.get("settings", {})
    filter_ads = settings.get("filter_ads", True)
    custom_ad_keywords = settings.get("ad_keywords", [])
    max_age_hours = DEFAULT_MAX_ARTICLE_AGE_HOURS

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
            # fetch_feed_items über Modulnamespace aufrufen (wichtig für Unittest-Mocks)
            items = fetch_feed_items(
                f_url,
                include_keywords=inc,
                exclude_keywords=exc,
                filter_ads=filter_ads,
                custom_ad_keywords=custom_ad_keywords,
                max_age_hours=max_age_hours,
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
                # Zusätzliche Absicherung gegen veraltete Artikel (strikt 24 Stunden)
                if is_article_too_old(it, max_age_hours=max_age_hours):
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
            storage.set_metadata("last_feed_refresh_time", str(time.time()))
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


__all__ = [
    # Core Orchestration
    "fetch_feed_items",
    "collect_all_news",
    "get_pool_state_path",
    "load_pool_state",
    "save_pool_state",
    "get_new_articles_count",
    # Filters & Sanitization
    "clean_html_text",
    "format_summary_html",
    "unwrap_and_clean_url",
    "get_canonical_url",
    "normalize_keywords",
    "is_ad_item",
    "get_article_timestamp",
    "is_article_too_old",
    "filter_articles_by_age",
    "filter_news_data_by_age",
    "DEFAULT_AD_PATTERNS",
    "DEFAULT_MAX_ARTICLE_AGE_HOURS",
    "DEFAULT_MAX_ARTICLE_AGE_SECONDS",
    "DEFAULT_ARCHIVE_RETENTION_DAYS",
    "DEFAULT_MAX_ARTICLE_AGE_WEEKS",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "SECONDS_PER_WEEK",
    # Feed Fetcher
    "determine_stream_type",
    "autodiscover_rss_feeds",
    "fetch_feed_raw",
    "test_feed_connection",
    "FEED_REQUEST_HEADERS_READER",
    "FEED_REQUEST_HEADERS_BOT",
    "FEED_REQUEST_HEADERS_BROWSER",
    # Police Scraper
    "_POLICE_TEASER_CACHE",
    "_POLICE_CACHE_FILE",
    "_load_police_cache",
    "_save_police_cache",
    "extract_police_teaser",
    # Sources Manager
    "get_streamlit_app_url",
    "get_sources_path",
    "get_github_sync_config",
    "sync_sources_to_github",
    "trigger_rss_update_workflow",
    "purge_jsdelivr_cache",
    "reconcile_prompt_templates",
    "load_sources",
    "save_sources",
    "add_feed",
    "delete_feed",
    "update_feed",
    "rename_category",
    "add_category",
    "delete_category",
    "update_settings",
    # Exceptions
    "NewsAggregatorError",
    "ConfigurationError",
    "FeedFetchError",
    # Requests für Mock-Kompatibilität
    "requests",
]


if __name__ == "__main__":
    news = collect_all_news()
    for cat, items in news.items():
        print(f"\n--- {cat} ({len(items)} Artikel) ---")
        for i in items[:3]:
            print(f"- {i['title']} [{i['source']}]")
