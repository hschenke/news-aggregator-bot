"""
Session state, constants, and data loading module for News Aggregator Bot UI.
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

import streamlit as st

from src.models import Article
from src.aggregator import (
    load_sources,
    collect_all_news,
    get_article_timestamp,
    filter_news_data_by_age,
    DEFAULT_MAX_ARTICLE_AGE_HOURS,
)
from src.storage import get_storage, SqliteStorage

logger = logging.getLogger(__name__)

BERLIN_TZ = ZoneInfo("Europe/Berlin")

TAB_ARTICLES = "articles"
TAB_KI = "ki"
TAB_MANAGE = "manage"
TAB_FEEDLY = "feedly"

TAB_LABELS: dict[str, str] = {
    TAB_ARTICLES: "📋 Artikel",
    TAB_KI: "✨ KI",
    TAB_MANAGE: "⚙️ Verwalten",
    TAB_FEEDLY: "📡 Feedly",
}

VALID_TAB_IDS = set(TAB_LABELS.keys())


def get_local_now() -> datetime:
    """Returns the current datetime in Berlin timezone."""
    return datetime.now(timezone.utc).astimezone(BERLIN_TZ)


def format_local_dt(dt_or_ts: Any, fmt: str = "%d.%m.%Y, %H:%M Uhr") -> str:
    """Formats a timestamp or datetime object in Berlin local time."""
    if not dt_or_ts:
        return ""
    if isinstance(dt_or_ts, (int, float)):
        if dt_or_ts <= 0:
            return ""
        try:
            dt = datetime.fromtimestamp(dt_or_ts, tz=timezone.utc).astimezone(BERLIN_TZ)
            return dt.strftime(fmt)
        except Exception:
            return ""
    if isinstance(dt_or_ts, datetime):
        if dt_or_ts.tzinfo is None:
            dt_or_ts = dt_or_ts.replace(tzinfo=timezone.utc)
        return dt_or_ts.astimezone(BERLIN_TZ).strftime(fmt)
    return str(dt_or_ts)


def init_session_state() -> None:
    """Initializes default Streamlit session state keys if not already present."""
    if "user_feedback" not in st.session_state:
        st.session_state["user_feedback"] = {}
    if "bookmarks" not in st.session_state:
        st.session_state["bookmarks"] = {}
    if "read_urls" not in st.session_state:
        st.session_state["read_urls"] = set()
    if "archived_urls" not in st.session_state:
        try:
            storage = get_storage()
            st.session_state["archived_urls"] = storage.get_archived_urls()
        except Exception as exc:
            logger.debug("Failed to fetch archived URLs: %s", exc)
            st.session_state["archived_urls"] = set()
    if "working_config" not in st.session_state:
        st.session_state["working_config"] = load_sources()
    if "has_unsaved_changes" not in st.session_state:
        st.session_state["has_unsaved_changes"] = False


@st.cache_data(ttl=300, show_spinner=False)
def get_news_data(force_live_fetch: bool = False) -> dict[str, list[dict[str, Any]]]:
    """
    Loads active news articles strictly limited to the last 24 hours.
    Tries fast database loading first; falls back to live RSS ingestion if empty or requested.
    """
    t_start = time.perf_counter()

    if not force_live_fetch:
        try:
            storage = get_storage()
            # Fetch up to 1000 articles from active table
            db_articles = storage.get_articles(limit=1000)
            if db_articles:
                data: dict[str, list[dict[str, Any]]] = {}
                sources_cfg = load_sources()
                configured_categories = {
                    c.get("name", "").strip()
                    for c in sources_cfg.get("categories", [])
                    if c.get("name")
                }

                now_ts = time.time()
                cutoff_24h = now_ts - (DEFAULT_MAX_ARTICLE_AGE_HOURS * 3600.0)

                for art in db_articles:
                    cat = (art.category or "Allgemein").strip()
                    if cat not in configured_categories:
                        continue
                    # Strictly filter to 24h
                    if art.timestamp > 0.0 and art.timestamp < cutoff_24h:
                        continue

                    if cat not in data:
                        data[cat] = []
                    data[cat].append(art.to_dict())

                if any(data.values()):
                    duration = time.perf_counter() - t_start
                    total_articles = sum(len(v) for v in data.values())
                    logger.info(
                        "Loaded %d articles across %d categories from database in %.2fs.",
                        total_articles,
                        len(data),
                        duration,
                    )
                    return data
        except Exception as exc:
            logger.warning("Database load failed (%s). Ingesting live RSS feeds...", exc)

    logger.info("Ingesting configured RSS feeds live...")
    data = collect_all_news(export_rss=True, save_to_db=True)
    # Strictly filter to 24 hours
    data = filter_news_data_by_age(data, max_age_hours=DEFAULT_MAX_ARTICLE_AGE_HOURS)

    duration = time.perf_counter() - t_start
    total_articles = sum(len(v) for v in data.values())
    logger.info(
        "Ingested %d articles across %d categories in %.2fs.",
        total_articles,
        len(data),
        duration,
    )
    return data
