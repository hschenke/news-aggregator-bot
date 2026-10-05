"""
News Aggregator Bot Web-App.
Modular entry point for dashboard, 24h news stream, AI briefings, RSS exposure, and feed management.
"""

from __future__ import annotations

import sys
import os
import time
import copy
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any

import streamlit as st

# Projektverzeichnis zum Suchpfad hinzufügen
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Standardisiertes Streamlit-Logging (stdout, englische Log-Meldungen)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("news_bot.webapp")

from src.models import Article
from src.aggregator import (
    load_sources,
    save_pool_state,
    clean_html_text,
    format_summary_html,
    get_article_timestamp,
    filter_news_data_by_age,
    DEFAULT_MAX_ARTICLE_AGE_HOURS,
    DEFAULT_MAX_ARTICLE_AGE_WEEKS,
)
from src.storage import get_storage
from src.ui.styles import apply_custom_styles, embed_client_script, release_action_overlay
from src.__version__ import get_app_version
from src.ui.auth import (
    is_admin_user,
    render_sidebar_auth,
    COOKIE_AUTH_NAME,
    COOKIE_ADMIN_NAME,
    ROLE_ADMIN,
    ROLE_GUEST,
)
from src.ui.state import (
    init_session_state,
    get_news_data,
    format_local_dt,
    TAB_ARTICLES,
    TAB_KI,
    TAB_MANAGE,
    TAB_FEEDLY,
    TAB_LABELS,
    VALID_TAB_IDS,
)
from src.ui.tabs.articles_tab import (
    render_articles_tab,
    on_article_feedback_change,
    on_article_read_and_archive,
    on_clear_search,
)
from src.ui.tabs.ki_tab import render_ki_tab
from src.ui.tabs.feedly_tab import render_feedly_tab
from src.ui.tabs.manage_tab import render_manage_tab

# Page Configuration
st.set_page_config(
    page_title="News Aggregator Bot | AI Briefing",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="auto",
)

# Custom Styles anwenden
apply_custom_styles()

# Session State initialisieren
init_session_state()

COOKIE_TAB_NAME = "news_bot_active_tab"

TAB_ID_ARTICLES = TAB_ARTICLES
TAB_ID_KI = TAB_KI
TAB_ID_MANAGE = TAB_MANAGE
TAB_ID_FEEDLY = TAB_FEEDLY

TAB_LABEL_ARTICLES = TAB_LABELS[TAB_ARTICLES]
TAB_LABEL_KI = TAB_LABELS[TAB_KI]
TAB_LABEL_MANAGE = TAB_LABELS[TAB_MANAGE]
TAB_LABEL_FEEDLY = TAB_LABELS[TAB_FEEDLY]

TAB_ORDER = [TAB_LABEL_ARTICLES, TAB_LABEL_KI, TAB_LABEL_MANAGE, TAB_LABEL_FEEDLY]


def label_to_tab_id(label: str) -> str:
    """Übersetzt das UI-Label in eine Tab-ID."""
    if "Artikel" in label:
        return TAB_ID_ARTICLES
    if "KI" in label:
        return TAB_ID_KI
    if "Verwalten" in label or "Quellen" in label:
        return TAB_ID_MANAGE
    if "Feedly" in label or "RSS" in label:
        return TAB_ID_FEEDLY
    return TAB_ID_ARTICLES


def tab_id_to_label(tab_id: str) -> str:
    """Übersetzt eine Tab-ID in das entsprechende UI-Label."""
    if tab_id == TAB_ID_KI or tab_id == "briefing":
        return TAB_LABEL_KI
    if tab_id == TAB_ID_MANAGE or tab_id in ["settings", "feeds", "quellen"]:
        return TAB_LABEL_MANAGE
    if tab_id in [TAB_ID_FEEDLY, "rss", "feeds_rss"]:
        return TAB_LABEL_FEEDLY
    return TAB_LABEL_ARTICLES


def get_persisted_active_tab() -> str | None:
    """Liest den zuletzt aktiven Tab aus Request-Cookies oder Session."""
    if hasattr(st, "context") and hasattr(st.context, "cookies"):
        val = st.context.cookies.get(COOKIE_TAB_NAME)
        if val in VALID_TAB_IDS:
            return val
    return None


def persist_active_tab(active_nav_tab: str) -> None:
    """Synchronisiert und speichert den aktiven Tab in Session, Cookie, LocalStorage und URL."""
    st.session_state["active_nav_tab"] = active_nav_tab
    st.session_state["main_tabs_nav"] = tab_id_to_label(active_nav_tab)
    if st.query_params.get("tab") != active_nav_tab:
        st.query_params["tab"] = active_nav_tab

    if st.session_state.get("_synced_active_tab") == active_nav_tab:
        return
    st.session_state["_synced_active_tab"] = active_nav_tab

    embed_client_script(f"""
    (function() {{
        var tab = "{active_nav_tab}";
        try {{
            document.cookie = "{COOKIE_TAB_NAME}=" + encodeURIComponent(tab) + "; path=/; max-age=31536000; SameSite=Lax";
            localStorage.setItem("{COOKIE_TAB_NAME}", tab);
            sessionStorage.setItem("{COOKIE_TAB_NAME}", tab);
        }} catch(e) {{}}

        var syncUrl = function(win) {{
            if (!win || !win.location) return;
            try {{
                var url = new URL(win.location.href);
                if (url.searchParams.get("tab") !== tab) {{
                    url.searchParams.set("tab", tab);
                    win.history.replaceState(null, "", url.toString());
                }}
            }} catch(e) {{}}
        }};
        try {{
            syncUrl(window);
            if (window.parent && window.parent !== window) {{
                syncUrl(window.parent);
            }}
        }} catch(e) {{}}
    }})();
    """)


def get_sources_config() -> dict[str, Any]:
    """Liest die Konfiguration unzensiert von der Festplatte."""
    try:
        return load_sources()
    except Exception:
        return {}


# Gespeicherten Stand laden und Arbeitsentwurf im session_state verwalten
saved_sources_config = get_sources_config()
if "working_sources_config" not in st.session_state:
    st.session_state["working_sources_config"] = copy.deepcopy(saved_sources_config)
    st.session_state["last_loaded_saved_config"] = copy.deepcopy(saved_sources_config)
    st.session_state["has_unsaved_changes"] = False

working_config = st.session_state["working_sources_config"]

# Berechtigungsstatus ermitteln
is_admin = is_admin_user()

# URL Query-Parameter
qp_category = st.query_params.get("category", "").strip()
qp_feed = st.query_params.get("feed", "").strip()
qp_tab = (st.query_params.get("tab") or "").strip().lower()

# Tab Navigation bestimmen:
# Wenn Gast (z. B. Klick aus E-Mail ohne Admin-Login): STRIKT nur Artikel-Tab verfügbar!
if not is_admin:
    active_nav_tab = TAB_ID_ARTICLES
    persist_active_tab(active_nav_tab)
else:
    if "pending_nav_tab" in st.session_state:
        active_nav_tab = st.session_state.pop("pending_nav_tab")
        persist_active_tab(active_nav_tab)
    elif qp_category or qp_feed:
        active_nav_tab = TAB_ID_ARTICLES
        persist_active_tab(active_nav_tab)
    elif "main_tabs_nav" in st.session_state:
        active_nav_tab = label_to_tab_id(st.session_state["main_tabs_nav"])
        persist_active_tab(active_nav_tab)
    else:
        persisted_tab = get_persisted_active_tab()
        if persisted_tab:
            active_nav_tab = persisted_tab
        elif qp_tab in ["ki", "briefing", "ai"]:
            active_nav_tab = TAB_ID_KI
        elif qp_tab in ["rss", "feeds_rss", "feedly"]:
            active_nav_tab = TAB_ID_FEEDLY
        elif qp_tab in ["manage", "settings", "feeds", "quellen"]:
            active_nav_tab = TAB_ID_MANAGE
        else:
            active_nav_tab = TAB_ID_ARTICLES
        persist_active_tab(active_nav_tab)

# Daten laden (fest 24 Stunden)
# Performance-Optimierung: Wenn der Verwalten-Tab aktiv ist, werden keine Artikeldaten benötigt -> 0 DB-Calls!
if active_nav_tab in (TAB_ID_ARTICLES, TAB_ID_KI, TAB_ID_FEEDLY):
    if "cached_news_data" not in st.session_state:
        st.session_state["cached_news_data"] = get_news_data(force_live_fetch=False)
    news_data = st.session_state["cached_news_data"]
else:
    news_data = {}

# ----------------- SIDEBAR -----------------
app_version = get_app_version()
st.sidebar.markdown(
    f"""
    <div class="sidebar-header-container">
        <h2 class="sidebar-header-title">🤖&nbsp;News Bot</h2>
        <span class="sidebar-version-badge">{app_version}</span>
    </div>
    """,
    unsafe_allow_html=True,
)
st.sidebar.caption("24h Newsfeed")

# Navigation in Sidebar
active_cls_art = "active-nav-tab" if active_nav_tab == TAB_ID_ARTICLES else ""
active_cls_ki = "active-nav-tab" if active_nav_tab == TAB_ID_KI else ""
active_cls_man = "active-nav-tab" if active_nav_tab == TAB_ID_MANAGE else ""
active_cls_fdl = "active-nav-tab" if active_nav_tab == TAB_ID_FEEDLY else ""

if is_admin:
    st.sidebar.markdown(f"""
    <div class="custom-nav-container">
        <button type="button" class="custom-nav-btn {active_cls_art}" data-tab-id="{TAB_ID_ARTICLES}">📋 Artikel</button>
        <button type="button" class="custom-nav-btn {active_cls_ki}" data-tab-id="{TAB_ID_KI}">✨ KI</button>
        <button type="button" class="custom-nav-btn {active_cls_man}" data-tab-id="{TAB_ID_MANAGE}">⚙️ Verwalten</button>
        <button type="button" class="custom-nav-btn {active_cls_fdl}" data-tab-id="{TAB_ID_FEEDLY}">📡 Feedly</button>
    </div>
    """, unsafe_allow_html=True)
else:
    # Gäste / Klick aus E-Mail: Nur Artikel verfügbar, andere ausgegraut / deaktiviert
    st.sidebar.markdown(f"""
    <div class="custom-nav-container">
        <button type="button" class="custom-nav-btn {active_cls_art}" data-tab-id="{TAB_ID_ARTICLES}">📋 Artikel</button>
        <button type="button" class="custom-nav-btn disabled-nav-btn" disabled title="Admin erforderlich">✨ KI 🔒</button>
        <button type="button" class="custom-nav-btn disabled-nav-btn" disabled title="Admin erforderlich">⚙️ Verwalten 🔒</button>
        <button type="button" class="custom-nav-btn disabled-nav-btn" disabled title="Admin erforderlich">📡 Feedly 🔒</button>
    </div>
    """, unsafe_allow_html=True)

# Client-seitiger Click Handler & Tab-Synchronisation für Navigation
embed_client_script(f"""
(function() {{
    var setActiveTabClient = function(tabId, tabIdx) {{
        if (!tabId) return;
        var sideBtns = document.querySelectorAll('.custom-nav-btn');
        for (var i = 0; i < sideBtns.length; i++) {{
            if (sideBtns[i].getAttribute('data-tab-id') === tabId) {{
                sideBtns[i].classList.add('active-nav-tab');
            }} else {{
                sideBtns[i].classList.remove('active-nav-tab');
            }}
        }}
        var tabs = document.querySelectorAll('[data-testid="stTabs"] [data-testid="stTab"]');
        if (tabs && tabs[tabIdx]) {{
            tabs[tabIdx].click();
        }}
    }};
    window._newsBotSetActiveTabClient = setActiveTabClient;

    document.addEventListener('click', function(evt) {{
        var btn = evt.target && evt.target.closest ? evt.target.closest('.custom-nav-btn:not(.disabled-nav-btn)') : null;
        if (!btn) return;
        var tabId = btn.getAttribute('data-tab-id');
        if (!tabId) return;

        var tabMap = {{ "articles": 0, "ki": 1, "manage": 2, "feedly": 3 }};
        var idx = tabMap[tabId] !== undefined ? tabMap[tabId] : 0;
        setActiveTabClient(tabId, idx);
    }}, true);
}})();
""")

def get_effective_last_update_ts(pool_data: dict[str, list[dict[str, Any]]]) -> float | None:
    """
    Ermittelt den verbindlichen, aktuellsten Zeitstempel des Datenbestands.
    Berücksichtigt manuellen Refresh, Metadaten in der Datenbank, den morgendlichen
    GitHub-Actions-Digest-Run (neuestes Briefing) sowie die neuesten Artikel-Timestamps.
    """
    manual_ts = st.session_state.get("last_refresh_timestamp")
    if manual_ts:
        return float(manual_ts)

    best_ts: float | None = None
    try:
        storage = get_storage()
        val = storage.get_metadata("last_feed_refresh_time")
        if val:
            best_ts = float(val)

        # Prüfen, ob das neueste KI-Briefing (z. B. morgendlicher GitHub Actions Run) neuer ist
        latest_briefing = storage.get_latest_briefing()
        if latest_briefing and latest_briefing.get("created_at"):
            b_iso = str(latest_briefing["created_at"])
            b_dt = datetime.fromisoformat(b_iso.replace("Z", "+00:00"))
            b_ts = b_dt.timestamp()
            if best_ts is None or b_ts > best_ts:
                best_ts = b_ts
                # Einmalig in Metadaten sichern für schnelle Folgezugriffe
                try:
                    storage.set_metadata("last_feed_refresh_time", str(b_ts))
                except Exception:
                    pass
    except Exception as exc:
        logger.debug("Fehler beim Ermitteln des Speicher-Timestamps: %s", exc)

    # Vergleich mit dem neuesten Artikel-Timestamp im Pool
    pool = pool_data or st.session_state.get("cached_news_data", {})
    if pool:
        max_art_ts = max((art.get("timestamp", 0.0) for arts in pool.values() for art in arts), default=0.0)
        if max_art_ts > 0.0 and (best_ts is None or max_art_ts > best_ts):
            best_ts = max_art_ts

    return best_ts


# Button: Feeds neu laden (nur im Administrator-Modus verfügbar)
if is_admin:
    st.sidebar.markdown("---")
    if "sidebar_refresh_notice" in st.session_state:
        st.sidebar.success(st.session_state.pop("sidebar_refresh_notice"))

    if st.sidebar.button(
        "🔄 Feeds neu laden",
        key="sb_btn_refresh_feeds",
        help="Liest alle RSS-Feeds ein und aktualisiert die Datenbank.",
        use_container_width=True,
    ):
        logger.info("Live feed refresh requested. Clearing cache and fetching feeds...")
        st.cache_data.clear()
        st.session_state.pop("cached_news_data", None)
        with st.spinner("Lese alle RSS-Feeds aus dem Internet ein..."):
            fresh_news = get_news_data(force_live_fetch=True)
            st.session_state["cached_news_data"] = fresh_news
            now_ts = time.time()
            st.session_state["last_refresh_timestamp"] = now_ts
            try:
                get_storage().set_metadata("last_feed_refresh_time", str(now_ts))
            except Exception:
                pass
        st.session_state["sidebar_refresh_notice"] = "Feeds erfolgreich aktualisiert!"
        st.rerun()

    # Zuletzt aktualisiert Info in der Sidebar (Bild 1)
    sidebar_sync_ts = get_effective_last_update_ts(news_data)
    formatted_sidebar_sync = format_local_dt(sidebar_sync_ts) if sidebar_sync_ts else ""
    if formatted_sidebar_sync:
        st.sidebar.caption(f"🕒 Letzte Aktualisierung: {formatted_sidebar_sync}")

# Sidebar Auth Bereich (Login / Logout)
render_sidebar_auth(is_admin)

# ----------------- HAUPTBEREICH & TABS -----------------
# Haupttitel & Subheader-Statuszeile (Bild 2: unter Daily News)
st.title("📰 Daily News", anchor=False)

last_update_ts = get_effective_last_update_ts(news_data)
date_str = format_local_dt(last_update_ts) if last_update_ts else format_local_dt(time.time())
total_count = sum(len(v) for v in news_data.values()) if news_data else 0
if total_count == 0 and "cached_news_data" in st.session_state:
    total_count = sum(len(v) for v in st.session_state["cached_news_data"].values())

item_label = "1 Artikel verfügbar" if total_count == 1 else f"{total_count} Artikel verfügbar"
st.caption(f"🕒 Stand: {date_str} · {item_label}")

default_tab_label = tab_id_to_label(active_nav_tab)
if default_tab_label not in TAB_ORDER:
    default_tab_label = TAB_ORDER[0]

if is_admin:
    tab_articles, tab_ki, tab_manage, tab_feedly = st.tabs(
        TAB_ORDER,
        default=default_tab_label,
        key="main_tabs_nav",
    )
else:
    # Andere Tabs mit Schloss-Symbol
    locked_tab_labels = [TAB_LABEL_ARTICLES, f"{TAB_LABEL_KI} 🔒", f"{TAB_LABEL_MANAGE} 🔒", f"{TAB_LABEL_FEEDLY} 🔒"]
    tab_articles, tab_ki, tab_manage, tab_feedly = st.tabs(
        locked_tab_labels,
        default=TAB_LABEL_ARTICLES,
        key="main_tabs_nav",
    )

with tab_articles:
    render_articles_tab(news_data, working_config)

with tab_ki:
    if is_admin:
        render_ki_tab(news_data, is_admin=True)
    else:
        st.subheader("🧠 KI-Briefing")
        st.info("🔒 Das KI-Briefing und die Generierung stehen nach der Administrator-Anmeldung in der linken Leiste bereit.")

with tab_manage:
    if is_admin:
        render_manage_tab(working_config, is_admin=True)
    else:
        st.subheader("⚙️ Quellen & Feeds verwalten")
        st.info("🔒 Die Verwaltung von Quellen und Einstellungen erfordert Administrator-Rechte. Bitte melde dich in der linken Navigationsleiste an.")

with tab_feedly:
    if is_admin:
        render_feedly_tab(news_data, working_config, is_admin=True)
    else:
        st.subheader("📡 RSS Exposure")
        st.info("🔒 Die RSS-Feeds und Feedly-Integration sind im Administrator-Modus verfügbar. Bitte melde dich in der linken Navigationsleiste an.")

# Release loading overlay and re-enable action buttons on render completion
release_action_overlay()
