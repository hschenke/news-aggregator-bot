import streamlit as st
import sys
import os
import logging
import hmac
import hashlib
import time
import copy
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# Projekt-Root zum Python-Pfad hinzufügen
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Streamlit Konsole Logging (INFO auf sys.stdout für Streamlit Cloud "Manage app")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("news_bot.webapp")

from src.aggregator import (
    collect_all_news,
    load_sources,
    save_sources,
    add_feed,
    delete_feed,
    update_feed,
    add_category,
    rename_category,
    delete_category,
    update_settings,
    test_feed_connection,
    get_sources_path,
    get_github_sync_config,
    sync_sources_to_github,
    trigger_rss_update_workflow,
    get_new_articles_count,
    save_pool_state,
    clean_html_text,
    format_summary_html,
    DEFAULT_MAX_ARTICLE_AGE_WEEKS,
    is_article_too_old,
    filter_articles_by_age,
    filter_news_data_by_age,
    get_article_timestamp,
)
from src.summarizer import (
    summarize_news_with_gemini,
    get_configured_api_key,
    get_streamlit_app_url,
    DEFAULT_MAIN_PROMPT_TEMPLATE,
    DEFAULT_DIRECTIVES,
    AVAILABLE_GEMINI_MODELS,
)
from src.rss_generator import export_all_rss_feeds
from src.action_buffer import get_action_buffer, DEFAULT_BUFFER_INTERVAL_MINUTES
from src.__version__ import get_app_version

action_buffer = get_action_buffer()

try:
    import zoneinfo
    BERLIN_TZ = zoneinfo.ZoneInfo("Europe/Berlin")
except Exception:
    from datetime import timezone, timedelta
    BERLIN_TZ = timezone(timedelta(hours=2))

def get_local_now() -> datetime:
    """Gibt die aktuelle Zeit in der Zeitzone Europe/Berlin zurück."""
    return datetime.now(BERLIN_TZ)

def format_local_dt(dt_or_ts: Any, fmt: str = "%d.%m.%Y, %H:%M Uhr") -> str:
    """Formatiert einen Zeitstempel oder Datetime verlässlich in Europe/Berlin."""
    if dt_or_ts is None:
        return ""
    if isinstance(dt_or_ts, (int, float)):
        if dt_or_ts <= 0:
            return ""
        try:
            from datetime import timezone
            dt = datetime.fromtimestamp(dt_or_ts, tz=timezone.utc).astimezone(BERLIN_TZ)
            return dt.strftime(fmt)
        except Exception:
            return ""
    if isinstance(dt_or_ts, datetime):
        if dt_or_ts.tzinfo is None:
            from datetime import timezone
            dt_or_ts = dt_or_ts.replace(tzinfo=timezone.utc)
        return dt_or_ts.astimezone(BERLIN_TZ).strftime(fmt)
    return str(dt_or_ts)

try:
    from streamlit_cookies_controller import CookieController
    cookie_controller = CookieController(key="news_bot_auth_cookie_ctrl")
except Exception:
    cookie_controller = None

COOKIE_AUTH_NAME = "news_bot_session"
COOKIE_EXPIRY_DAYS = 7
COOKIE_TAB_NAME = "news_bot_active_tab"

# Page Configuration
st.set_page_config(
    page_title="News Aggregator Bot | AI Briefing",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="auto",
)

# Custom Styling (Kompakt & Mobile-optimiert)
st.markdown("""
<style>
    /* Haupt-Container mit ausreichend Abstand zur fixierten Streamlit-Headerleiste */
    .block-container {
        padding-top: 3.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.25rem !important;
        padding-right: 1.25rem !important;
        max-width: 1250px;
    }
    /* Unsichtbare Hilfs-Iframes und Script-Container vollständig ausblenden */
    [data-testid="stIFrame"]:has(iframe[height="0"]),
    [data-testid="stIFrame"]:has(iframe[height="1"]),
    [data-testid="stCustomComponentV1"]:has(iframe[height="0"]),
    iframe[height="0"], iframe[height="1"],
    iframe[width="0"], iframe[width="1"] {
        display: none !important;
        height: 0 !important;
        width: 0 !important;
        border: none !important;
        margin: 0 !important;
        padding: 0 !important;
        visibility: hidden !important;
        position: absolute !important;
        pointer-events: none !important;
    }
    /* Header-Anchor-Links (Kettensymbol / Link-Icon bei Hover) komplett ausblenden */
    [data-testid="stHeaderActionElements"],
    .stMarkdown a.anchor-link,
    a.header-anchor,
    h1 a, h2 a, h3 a, h4 a, h5 a, h6 a {
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
        opacity: 0 !important;
        width: 0 !important;
        height: 0 !important;
    }
    /* Skeleton-Ladeplatzhalter sanft ausblenden, damit kein grauer Kasten aufblitzt */
    [data-testid="stSkeleton"],
    [data-testid="stSkeletonElement"],
    .stSkeleton {
        display: none !important;
        opacity: 0 !important;
        visibility: hidden !important;
    }
    /* Verhindert das 1-3 sekündige Ergrauen / Verblassen der UI bei Interaktionen und Reruns */
    [data-stale="true"],
    [data-testid="stElementContainer"][data-stale="true"],
    [data-testid="stVerticalBlockBorderWrapper"][data-stale="true"],
    [data-testid="stVerticalBlock"][data-stale="true"],
    [data-testid="stHorizontalBlock"][data-stale="true"],
    .stApp [data-stale="true"],
    .stApp div[data-stale="true"] {
        opacity: 1 !important;
        transition: none !important;
        filter: none !important;
    }
    /* Buttons und Feedback-Daumen während Reruns nicht ausgrauen oder abschwächen */
    [data-testid="stFeedback"] button:disabled,
    [data-testid="stFeedback"] button[data-disabled="true"],
    [data-testid="stFeedback"] button[disabled],
    div[class*="st-key-read_"] button:disabled,
    div[class*="st-key-read_"] button[data-disabled="true"],
    div[class*="st-key-read_"] button[disabled] {
        opacity: 1 !important;
        cursor: pointer !important;
    }
    /* Verhindert Ergrauen der gesamten App bei Script-Ausführung */
    .stApp[data-test-script-state="running"] [data-testid="stVerticalBlockBorderWrapper"],
    .stApp[data-test-script-state="running"] [data-testid="stElementContainer"],
    .stApp[data-test-script-state="running"] [data-testid="stFeedback"],
    .stApp[data-test-script-state="running"] div[class*="st-key-read_"] {
        opacity: 1 !important;
        filter: none !important;
    }
    /* Sperrt Buttons während laufender Ausführung (z. B. Speichern / Sync), um Mehrfach-Klicks zu verhindern */
    .stApp[data-test-script-state="running"] button,
    .stApp[data-test-script-state="running"] .stButton > button {
        pointer-events: none !important;
        cursor: wait !important;
    }
    /* Card Container & Text-Wrapping: verhindert Überlauf auf Mobile & Desktop */
    [data-testid="stVerticalBlockBorderWrapper"] {
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        overflow-wrap: anywhere !important;
        word-break: break-word !important;
        overflow: hidden !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] * {
        scrollbar-width: none !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] *::-webkit-scrollbar {
        display: none !important;
        width: 0 !important;
        height: 0 !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] > div {
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] a,
    [data-testid="stVerticalBlockBorderWrapper"] p,
    [data-testid="stVerticalBlockBorderWrapper"] div {
        overflow-wrap: anywhere !important;
        word-break: break-word !important;
    }

    /* Feedback- & Read-Zeile innerhalb der Card */
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        justify-content: space-between !important;
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        margin-top: 0.65rem !important;
        overflow: hidden !important;
        scrollbar-width: none !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        min-width: 0 !important;
        height: auto !important;
        overflow: visible !important;
    }
    /* Daumen ganz links */
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child,
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child {
        flex: 1 1 auto !important;
        width: auto !important;
        justify-content: flex-start !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: flex-start !important;
        width: 100% !important;
        gap: 0 !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stFeedback"] {
        display: inline-flex !important;
        align-items: center !important;
        margin: 0 !important;
        margin-right: auto !important;
        padding: 0 !important;
    }

    /* Haken ganz rechts */
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child,
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child {
        flex: 1 1 auto !important;
        width: auto !important;
        margin-left: auto !important;
        justify-content: flex-end !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: flex-end !important;
        width: 100% !important;
        gap: 0 !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child .stButton,
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child div[class*="st-key-read_"] {
        display: inline-flex !important;
        justify-content: flex-end !important;
        align-items: center !important;
        margin-left: auto !important;
        margin-right: 0 !important;
        width: auto !important;
    }

    /* Gelesen-Symbol Styling: Randlos, transparent, dezent wie st.feedback - ohne Skalierung gegen Scrollbalken */
    div[class*="st-key-read_"] {
        display: inline-flex !important;
        justify-content: flex-end !important;
        align-items: center !important;
        margin: 0 !important;
        margin-left: auto !important;
        padding: 0 !important;
        width: auto !important;
    }
    div[class*="st-key-read_"] button {
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        padding: 0 !important;
        min-height: 2rem !important;
        height: 2rem !important;
        width: 2rem !important;
        min-width: 2rem !important;
        max-width: 2rem !important;
        max-height: 2rem !important;
        border-radius: 50% !important;
        color: #94a3b8 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        line-height: 1 !important;
        margin: 0 !important;
        margin-left: auto !important;
        transition: background-color 0.15s ease-in-out, color 0.15s ease-in-out !important;
        overflow: hidden !important;
    }
    div[class*="st-key-read_"] button:hover {
        background-color: rgba(34, 197, 94, 0.15) !important;
        color: #16a34a !important;
    }
    div[class*="st-key-read_"] button:active,
    div[class*="st-key-read_"] button:focus {
        background-color: rgba(34, 197, 94, 0.22) !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        color: #16a34a !important;
    }
    div[class*="st-key-read_"] button [data-testid="stIconMaterial"] {
        font-size: 1.25rem !important;
        line-height: 1 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    @media (max-width: 768px) {
        .block-container {
            padding-top: 3.25rem !important;
            padding-bottom: 1.5rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
        h1 {
            font-size: 1.3rem !important;
            margin-top: 0.2rem !important;
            margin-bottom: 0.1rem !important;
            line-height: 1.2 !important;
        }
        h2 {
            font-size: 1.2rem !important;
            margin-top: 0.35rem !important;
            margin-bottom: 0.2rem !important;
        }
        h3 {
            font-size: 1.05rem !important;
            margin-top: 0.3rem !important;
            margin-bottom: 0.15rem !important;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 2px !important;
        }
        .stTabs [data-baseweb="tab"] {
            padding: 0.3rem 0.5rem !important;
            font-size: 0.82rem !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"] > div {
            padding: 0.6rem !important;
        }
        [data-testid="stVerticalBlock"] {
            gap: 0.4rem !important;
        }
        hr {
            margin: 0.5rem 0 !important;
        }
        /* Mobile: Spalten in horizontalen Dropdown-Blöcken auf volle Breite umbrechen */
        [data-testid="stExpander"]:has(.st-key-sel_articles_category) [data-testid="stHorizontalBlock"]:not(:has(.st-key-input_search_query)) > [data-testid="stColumn"],
        [data-testid="stExpander"]:has(.st-key-sel_articles_category) [data-testid="stHorizontalBlock"]:not(:has(.st-key-input_search_query)) > [data-testid="column"] {
            min-width: 100% !important;
            flex: 1 1 100% !important;
            width: 100% !important;
            max-width: 100% !important;
            box-sizing: border-box !important;
        }
        /* Card-Columns innerhalb von Expandern auf Mobile auf 100% Breite stacken */
        [data-testid="stExpander"] [data-testid="stColumn"]:has([data-testid="stVerticalBlockBorderWrapper"]),
        [data-testid="stExpander"] [data-testid="column"]:has([data-testid="stVerticalBlockBorderWrapper"]) {
            min-width: 100% !important;
            width: 100% !important;
            flex: 1 1 100% !important;
            max-width: 100% !important;
            box-sizing: border-box !important;
        }
        /* Feedback-Daumen & Gelesen-Symbol innerhalb der Card AUF MOBILE IMMER in 1 Zeile bündig halten */
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            align-items: center !important;
            justify-content: space-between !important;
            width: 100% !important;
            gap: 0.4rem !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"] {
            display: flex !important;
            flex-direction: row !important;
            align-items: center !important;
            min-width: 0 !important;
            max-width: none !important;
            width: auto !important;
            flex: 0 0 auto !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child,
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child {
            flex: 1 1 auto !important;
            justify-content: flex-start !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child,
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child {
            flex: 0 0 auto !important;
            margin-left: auto !important;
            justify-content: flex-end !important;
        }
        /* Suchleiste auf Mobile: Eingabefeld, ✕ und Go in einer Zeile bündig halten */
        [data-testid="stHorizontalBlock"]:has(.st-key-input_search_query) {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            align-items: flex-end !important;
            width: 100% !important;
            max-width: 100% !important;
            gap: 0.35rem !important;
            box-sizing: border-box !important;
        }
        [data-testid="stHorizontalBlock"]:has(.st-key-input_search_query) > [data-testid="stColumn"]:has(.st-key-input_search_query),
        [data-testid="stHorizontalBlock"]:has(.st-key-input_search_query) > [data-testid="column"]:has(.st-key-input_search_query) {
            min-width: 0 !important;
            flex: 1 1 0 !important;
            width: auto !important;
        }
        [data-testid="stHorizontalBlock"]:has(.st-key-input_search_query) > [data-testid="stColumn"]:has(.st-key-btn_search_clear),
        [data-testid="stHorizontalBlock"]:has(.st-key-input_search_query) > [data-testid="column"]:has(.st-key-btn_search_clear) {
            min-width: 2.5rem !important;
            max-width: 2.75rem !important;
            flex: 0 0 2.5rem !important;
            width: 2.5rem !important;
        }
        [data-testid="stHorizontalBlock"]:has(.st-key-input_search_query) > [data-testid="stColumn"]:has(.st-key-btn_search_go),
        [data-testid="stHorizontalBlock"]:has(.st-key-input_search_query) > [data-testid="column"]:has(.st-key-btn_search_go) {
            min-width: 3.25rem !important;
            max-width: 3.5rem !important;
            flex: 0 0 3.25rem !important;
            width: 3.25rem !important;
        }
    }
    /* Buttons in der Suchleiste sauber ausrichten */
    .st-key-btn_search_clear button {
        font-weight: 700 !important;
        padding-left: 0.25rem !important;
        padding-right: 0.25rem !important;
    }
    .st-key-btn_search_go button {
        font-weight: 600 !important;
        padding-left: 0.4rem !important;
        padding-right: 0.4rem !important;
    }
    /* Bewertungs-Daumen kompakt & direkt unterm Text platzieren */
    [data-testid="stFeedback"] {
        margin-top: 0.25rem !important;
        margin-bottom: 0 !important;
        padding: 0 !important;
    }
    [data-testid="stFeedback"] button {
        padding: 0.25rem 0.45rem !important;
        min-height: 2rem !important;
        border-radius: 8px !important;
        transition: all 0.15s ease-in-out !important;
    }
    /* Nicht ausgewählter Button: dezent & Outline */
    [data-testid="stFeedback"] button[data-testid="stFeedbackButton"]:not([data-testid="stFeedbackButtonActive"]):not([aria-checked="true"]) {
        color: #94a3b8 !important;
        background-color: transparent !important;
    }
    [data-testid="stFeedback"] button[data-testid="stFeedbackButton"]:not([data-testid="stFeedbackButtonActive"]):not([aria-checked="true"]) span {
        font-variation-settings: 'FILL' 0, 'wght' 400 !important;
    }
    [data-testid="stFeedback"] button:hover:not(:disabled) {
        background-color: rgba(128, 128, 128, 0.12) !important;
    }

    /* Ausgewählter Like-Button (Daumen hoch): Komplett ausgefülltes Icon & grüner Akzent */
    [data-testid="stFeedback"] button[data-testid="stFeedbackButtonActive"][aria-label*="up" i],
    [data-testid="stFeedback"] button[aria-checked="true"][aria-label*="up" i] {
        color: #16a34a !important;
        background-color: rgba(22, 163, 74, 0.18) !important;
        border: 1px solid rgba(22, 163, 74, 0.4) !important;
    }
    [data-testid="stFeedback"] button[data-testid="stFeedbackButtonActive"][aria-label*="up" i] span,
    [data-testid="stFeedback"] button[aria-checked="true"][aria-label*="up" i] span,
    [data-testid="stFeedback"] button[data-testid="stFeedbackButtonActive"][aria-label*="up" i] [data-testid="stIconMaterial"],
    [data-testid="stFeedback"] button[aria-checked="true"][aria-label*="up" i] [data-testid="stIconMaterial"] {
        font-variation-settings: 'FILL' 1, 'wght' 700 !important;
        color: #16a34a !important;
    }

    /* Ausgewählter Dislike-Button (Daumen runter): Komplett ausgefülltes Icon & roter Akzent */
    [data-testid="stFeedback"] button[data-testid="stFeedbackButtonActive"][aria-label*="down" i],
    [data-testid="stFeedback"] button[aria-checked="true"][aria-label*="down" i] {
        color: #dc2626 !important;
        background-color: rgba(220, 38, 38, 0.18) !important;
        border: 1px solid rgba(220, 38, 38, 0.4) !important;
    }
    [data-testid="stFeedback"] button[data-testid="stFeedbackButtonActive"][aria-label*="down" i] span,
    [data-testid="stFeedback"] button[aria-checked="true"][aria-label*="down" i] span,
    [data-testid="stFeedback"] button[data-testid="stFeedbackButtonActive"][aria-label*="down" i] [data-testid="stIconMaterial"],
    [data-testid="stFeedback"] button[aria-checked="true"][aria-label*="down" i] [data-testid="stIconMaterial"] {
        font-variation-settings: 'FILL' 1, 'wght' 700 !important;
        color: #dc2626 !important;
    }
    /* Infobox & Zitate Styling */
    blockquote {
        margin: 0.75rem 0 !important;
        padding: 0.65rem 1.1rem !important;
        background-color: rgba(59, 130, 246, 0.07) !important;
        border-left: 4px solid #3b82f6 !important;
        border-radius: 6px !important;
        font-size: 0.95rem !important;
        line-height: 1.55 !important;
    }
    /* Sidebar Navigation ausgewogene Abstände & saubere Bereichstrennung */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.45rem !important;
    }
    [data-testid="stSidebar"] .stButton {
        margin-top: 0 !important;
        margin-bottom: 0.15rem !important;
    }
    [data-testid="stSidebar"] .stButton button,
    [data-testid="stSidebar"] button[data-testid^="stBaseButton"] {
        padding-top: 0.35rem !important;
        padding-bottom: 0.35rem !important;
        padding-left: 0.65rem !important;
        padding-right: 0.65rem !important;
        min-height: 2.25rem !important;
        line-height: 1.2 !important;
        font-size: 0.88rem !important;
        border-radius: 0.45rem !important;
    }
    /* Aktives Tab im linken Navigationsbereich immer blau hervorheben */
    [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"],
    [data-testid="stSidebar"] button[kind="primary"] {
        background-color: #2563EB !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        border: 1px solid #1d4ed8 !important;
        box-shadow: 0 1px 3px rgba(37, 99, 235, 0.3) !important;
    }
    [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"],
    [data-testid="stSidebar"] button[kind="secondary"] {
        background-color: transparent !important;
        border: 1px solid rgba(128, 128, 128, 0.22) !important;
        color: var(--text-color) !important;
    }
    [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover,
    [data-testid="stSidebar"] button[kind="secondary"]:hover {
        background-color: rgba(37, 99, 235, 0.08) !important;
        border-color: #2563EB !important;
        color: #2563EB !important;
    }
    /* Client-seitige Sidebar-Navigation (100% 0ms Reaktionszeit ohne Server-Roundtrip) */
    .custom-nav-container {
        display: flex !important;
        flex-direction: column !important;
        gap: 0.45rem !important;
        margin-top: 0 !important;
        margin-bottom: 0.25rem !important;
        width: 100% !important;
    }
    .custom-nav-btn {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: 100% !important;
        padding-top: 0.35rem !important;
        padding-bottom: 0.35rem !important;
        padding-left: 0.65rem !important;
        padding-right: 0.65rem !important;
        min-height: 2.25rem !important;
        line-height: 1.2 !important;
        font-size: 0.88rem !important;
        font-weight: 500 !important;
        border-radius: 0.45rem !important;
        border: 1px solid rgba(128, 128, 128, 0.22) !important;
        background-color: transparent !important;
        color: var(--text-color) !important;
        cursor: pointer !important;
        transition: all 0.15s ease-in-out !important;
        font-family: inherit !important;
        text-align: center !important;
        box-sizing: border-box !important;
        user-select: none !important;
    }
    .custom-nav-btn:hover {
        background-color: rgba(37, 99, 235, 0.08) !important;
        border-color: #2563EB !important;
        color: #2563EB !important;
    }
    .custom-nav-btn.active-nav-tab {
        background-color: #2563EB !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        border: 1px solid #1d4ed8 !important;
        box-shadow: 0 1px 3px rgba(37, 99, 235, 0.3) !important;
    }
    /* Trennlinien über volle Breite mit angenehmem Abstand nach oben & unten */
    [data-testid="stSidebar"] hr,
    [data-testid="stSidebar"] [data-testid="stDivider"] {
        border: none !important;
        border-top: 1px solid rgba(128, 128, 128, 0.28) !important;
        margin-top: 0.85rem !important;
        margin-bottom: 0.85rem !important;
        margin-left: -1rem !important;
        margin-right: -1rem !important;
        width: calc(100% + 2rem) !important;
        display: block !important;
    }
    [data-testid="stSidebar"] div[data-testid="stMarkdownContainer"]:has(hr) {
        margin: 0 !important;
        padding: 0 !important;
    }
    [data-testid="stSidebar"] [data-testid="stAlert"] {
        padding: 0.35rem 0.6rem !important;
        margin-top: 0.2rem !important;
        margin-bottom: 0.35rem !important;
        font-size: 0.82rem !important;
    }
    /* Kompakte KPI Chips-Leiste */
    .kpi-container {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
        align-items: center;
        margin-top: 0.2rem;
        margin-bottom: 0.65rem;
    }
    .kpi-chip {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.22rem 0.6rem;
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 9999px;
        font-size: 0.8rem;
        color: var(--text-color);
        white-space: nowrap;
    }
    .kpi-chip strong {
        font-weight: 600;
    }
    .kpi-chip.kpi-pool {
        background-color: rgba(37, 99, 235, 0.12);
        border-color: rgba(37, 99, 235, 0.35);
        color: #2563eb;
    }
    .metric-card {
        background-color: var(--secondary-background-color);
        padding: 0.75rem 1rem;
        border-radius: 0.75rem;
        border: 1px solid rgba(128, 128, 128, 0.2);
    }
    .article-card {
        padding: 0.85rem;
        border-radius: 0.6rem;
        border: 1px solid rgba(128, 128, 128, 0.2);
        margin-bottom: 0.65rem;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .badge {
        display: inline-block;
        padding: 0.2rem 0.55rem;
        font-size: 0.75rem;
        font-weight: 600;
        border-radius: 9999px;
        background-color: rgba(37, 99, 235, 0.15);
        color: #2563eb;
    }
    .login-container {
        max-width: 420px;
        margin: 2rem auto;
        padding: 1.5rem;
        background-color: var(--secondary-background-color);
        border-radius: 1rem;
        border: 1px solid rgba(128, 128, 128, 0.2);
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
</style>
""", unsafe_allow_html=True)


# --- Passwort-Schutz & Login-Persistenz ---
try:
    from src.auth import (
        get_configured_app_password,
        generate_readonly_auth_token,
        generate_admin_auth_token,
        verify_admin_token,
        get_auth_role,
        ROLE_ADMIN,
        ROLE_READONLY,
        COOKIE_AUTH_NAME,
        COOKIE_ADMIN_NAME,
        COOKIE_EXPIRY_DAYS,
    )
except ImportError:
    import importlib
    import src.auth
    importlib.reload(src.auth)
    from src.auth import (
        get_configured_app_password,
        generate_readonly_auth_token,
        generate_admin_auth_token,
        verify_admin_token,
        get_auth_role,
        ROLE_ADMIN,
        ROLE_READONLY,
        COOKIE_AUTH_NAME,
        COOKIE_ADMIN_NAME,
        COOKIE_EXPIRY_DAYS,
    )


def embed_client_script(js_code: str) -> None:
    """Führt Hilfsskripte (z. B. Cookie/Storage-Sync) modern und unsichtbar via st.html aus (Chrome & Firefox)."""
    html_wrapper = (
        f"<div style='display:none !important;width:0 !important;height:0 !important;"
        f"margin:0 !important;padding:0 !important;overflow:hidden !important;border:none !important;'>"
        f"<script>{js_code}</script></div>"
    )
    st.html(html_wrapper, unsafe_allow_javascript=True)


def set_admin_session_cookie(expected_password: str) -> str:
    """Erstellt ein 24h-Admin-Token und speichert es in Cookie, LocalStorage und Session."""
    admin_token = generate_admin_auth_token(expected_password)
    st.session_state["authenticated"] = True
    st.session_state["auth_role"] = ROLE_ADMIN
    st.query_params["auth"] = admin_token
    embed_client_script(f"""
    (function() {{
        var seconds = 86400; // 24 Stunden
        var d = new Date();
        d.setTime(d.getTime() + (seconds * 1000));
        var expires = "expires=" + d.toUTCString();
        var cookieStr = "{COOKIE_ADMIN_NAME}=" + encodeURIComponent("{admin_token}") + "; " + expires + "; path=/; SameSite=Lax; Secure";
        try {{
            localStorage.setItem("{COOKIE_ADMIN_NAME}", "{admin_token}");
            document.cookie = cookieStr;
            if (window.parent && window.parent !== window) {{
                window.parent.localStorage.setItem("{COOKIE_ADMIN_NAME}", "{admin_token}");
                window.parent.document.cookie = cookieStr;
            }}
        }} catch(e) {{}}
    }})();
    """)
    if cookie_controller:
        try:
            cookie_controller.set(
                COOKIE_ADMIN_NAME,
                admin_token,
                max_age=86400.0,
                expires=datetime.now() + timedelta(days=1),
                same_site="lax"
            )
        except Exception:
            pass
    return admin_token


def check_password() -> bool:
    """
    Überprüft das App-Passwort mit rollenbasierter Persistenz:
    1. Bereits in session_state authentifiziert
    2. 24h-Admin-Cookie im Request-Header oder Cookie-Controller
    3. URL Query Parameter ?auth=... oder ?token=... (Admin- oder Readonly-Token)
    4. HTTP-Cookie im Request-Header für Read-Only
    5. Client-seitiges Auto-Login via localStorage (Admin zuerst, dann Read-Only)
    6. Passwort-Eingabe über Login-Formular
    """
    expected_password = get_configured_app_password()
    if not expected_password:
        st.session_state["authenticated"] = True
        st.session_state["auth_role"] = ROLE_ADMIN
        return True  # Kein Passwort konfiguriert -> freier Admin-Zugang

    # 1. Bereits in dieser Sitzung authentifiziert?
    if st.session_state.get("authenticated", False):
        return True

    # 2. Prüfen auf 24h-Admin-Cookie im Request Header (st.context.cookies)
    if hasattr(st, "context") and hasattr(st.context, "cookies"):
        admin_cookie = st.context.cookies.get(COOKIE_ADMIN_NAME)
        if admin_cookie and verify_admin_token(admin_cookie, expected_password):
            st.session_state["authenticated"] = True
            st.session_state["auth_role"] = ROLE_ADMIN
            return True

    # 3. Fallback über cookie_controller für Admin-Cookie
    if cookie_controller:
        try:
            admin_ctrl = cookie_controller.get(COOKIE_ADMIN_NAME)
            if admin_ctrl and verify_admin_token(admin_ctrl, expected_password):
                st.session_state["authenticated"] = True
                st.session_state["auth_role"] = ROLE_ADMIN
                return True
        except Exception:
            pass

    # 4. URL Query Parameter prüfen (?auth=... oder ?token=...)
    url_auth = st.query_params.get("auth") or st.query_params.get("token")
    if url_auth:
        role = get_auth_role(url_auth, expected_password)
        if role:
            st.session_state["authenticated"] = True
            st.session_state["auth_role"] = role
            return True

    # 5. Read-Only HTTP Cookie im Request Header prüfen (st.context.cookies)
    if hasattr(st, "context") and hasattr(st.context, "cookies"):
        token_from_cookie = st.context.cookies.get(COOKIE_AUTH_NAME)
        if token_from_cookie:
            role = get_auth_role(token_from_cookie, expected_password)
            if role:
                st.session_state["authenticated"] = True
                st.session_state["auth_role"] = role
                return True

    # 6. Fallback über cookie_controller für Read-Only Cookie
    if cookie_controller:
        try:
            token_from_ctrl = cookie_controller.get(COOKIE_AUTH_NAME)
            if token_from_ctrl:
                role = get_auth_role(token_from_ctrl, expected_password)
                if role:
                    st.session_state["authenticated"] = True
                    st.session_state["auth_role"] = role
                    return True
        except Exception:
            pass

    # 7. Client-seitiges Auto-Login: Falls im localStorage ein Admin- oder Read-Token liegt,
    # wird die Seite sofort automatisch mit ?auth=TOKEN neu geladen!
    embed_client_script(f"""
    (function() {{
        try {{
            var adminStored = localStorage.getItem("{COOKIE_ADMIN_NAME}");
            if (!adminStored) {{
                var matchAdmin = document.cookie.match(new RegExp('(^|;\\\\s*)' + '{COOKIE_ADMIN_NAME}' + '=([^;]*)'));
                if (matchAdmin) adminStored = decodeURIComponent(matchAdmin[2]);
            }}
            if (adminStored && !window.location.search.includes("auth=")) {{
                var url = new URL(window.location.href);
                url.searchParams.set("auth", adminStored);
                window.location.replace(url.href);
                return;
            }}

            var stored = localStorage.getItem("{COOKIE_AUTH_NAME}");
            if (!stored) {{
                var match = document.cookie.match(new RegExp('(^|;\\\\s*)' + '{COOKIE_AUTH_NAME}' + '=([^;]*)'));
                if (match) stored = decodeURIComponent(match[2]);
            }}
            if (stored && !window.location.search.includes("auth=")) {{
                var url = new URL(window.location.href);
                url.searchParams.set("auth", stored);
                window.location.replace(url.href);
            }}
        }} catch(e) {{}}
    }})();
    """)

    # 8. Nicht angemeldet: Login-Formular anzeigen
    login_area = st.empty()
    with login_area.container():
        st.markdown("""
            <div style='text-align: center; margin-top: 2rem;'>
                <h2>🔒 Zugriff geschützt</h2>
                <p style='color: gray;'>Diese App ist privat. Bitte gib das Passwort ein, um fortzufahren.</p>
            </div>
        """, unsafe_allow_html=True)

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                password_input = st.text_input("Passwort / PIN", type="password", placeholder="••••••••")
                submit = st.form_submit_button("Anmelden", use_container_width=True, type="primary")

                if submit:
                    if password_input == expected_password:
                        # Erfolgreiche Admin-Anmeldung -> 24h Admin-Cookie & Token hinterlegen!
                        set_admin_session_cookie(expected_password)
                        st.session_state["just_logged_in"] = True
                        login_area.empty()
                        with login_area.container():
                            st.markdown("""
                                <div style='text-align: center; margin-top: 3.5rem; padding: 2rem;'>
                                    <div style='font-size: 2.5rem; margin-bottom: 0.8rem;'>⏳</div>
                                    <h3 style='color: #1e293b; margin-bottom: 0.5rem;'>Anmeldung erfolgreich!</h3>
                                    <p style='color: #64748b; font-size: 0.95rem;'>Lade Dashboard und aktuelle Nachrichten...</p>
                                </div>
                            """, unsafe_allow_html=True)
                        st.rerun()
                    else:
                        role = get_auth_role(password_input, expected_password)
                        if role == ROLE_READONLY:
                            st.session_state["authenticated"] = True
                            st.session_state["auth_role"] = ROLE_READONLY
                            st.session_state["just_logged_in"] = True
                            login_area.empty()
                            with login_area.container():
                                st.markdown("""
                                    <div style='text-align: center; margin-top: 3.5rem; padding: 2rem;'>
                                        <div style='font-size: 2.5rem; margin-bottom: 0.8rem;'>⏳</div>
                                        <h3 style='color: #1e293b; margin-bottom: 0.5rem;'>Anmeldung erfolgreich!</h3>
                                        <p style='color: #64748b; font-size: 0.95rem;'>Lade Dashboard und aktuelle Nachrichten...</p>
                                    </div>
                                """, unsafe_allow_html=True)
                            st.rerun()
                        else:
                            st.error("Falsches Passwort. Bitte erneut versuchen.")

    return False


if not check_password():
    st.stop()

# Visueller Lade-Übergang nach Login
init_loader_placeholder = st.empty()
if st.session_state.pop("just_logged_in", False):
    with init_loader_placeholder.container():
        st.markdown("""
            <div style='text-align: center; margin-top: 3.5rem; padding: 2rem;'>
                <div style='font-size: 2.5rem; margin-bottom: 0.8rem;'>⏳</div>
                <h3 style='color: #1e293b; margin-bottom: 0.5rem;'>Seite lädt...</h3>
                <p style='color: #64748b; font-size: 0.95rem;'>Dashboard und aktuelle Nachrichten werden aufbereitet...</p>
            </div>
        """, unsafe_allow_html=True)


# --- Caching Data Loading ---
@st.cache_data(ttl=86400, show_spinner=False)  # 24h Cache; Aktualisierung via 'Feeds neu laden' oder morgendlichen GitHub Run
def get_news_data(force_live_fetch: bool = False):
    """
    Lädt News-Artikel schnell aus der Datenbank (Turso Cloud DB / lokales SQLite-Archiv).
    Verhindert langwieriges RSS-Scraping beim Starten oder Einloggen der App.
    Nur bei komplett leerer Datenbank oder wenn explizit 'force_live_fetch=True'
    übergeben wird (z. B. bei Klick auf 'Feeds neu laden'), werden RSS-Feeds live aus dem Web geladen.
    """
    t0 = time.time()
    if not force_live_fetch:
        try:
            from src.storage import get_storage
            storage = get_storage()
            db_articles = storage.get_articles(limit=5000)
            if db_articles:
                data: dict[str, list[dict[str, Any]]] = {}
                sources_cfg = get_sources_config()
                valid_cat_names = {
                    c.get("name", "").strip()
                    for c in sources_cfg.get("categories", [])
                    if c.get("name", "").strip()
                }
                for art in db_articles:
                    title = (art.title or "").strip()
                    url = (art.link or "").strip()
                    # Test- und Dummy-Artikel ausschließen (z. B. Title 1 / test-1)
                    if not title or (title.startswith("Title ") and "example.com" in url) or "example.com/test-" in url:
                        continue
                    cat = (art.category or "").strip()
                    # Nur konfigurierte Kategorien übernehmen
                    if valid_cat_names and cat not in valid_cat_names:
                        continue
                    if not cat:
                        continue
                    data.setdefault(cat, []).append(art.to_dict())
                duration = time.time() - t0
                total_articles = sum(len(items) for items in data.values())
                logger.info("⚡ [Streamlit] %d Artikel über %d Kategorien blitzschnell aus Datenbank in %.2fs geladen.", total_articles, len(data), duration)
                return data
        except Exception as exc:
            logger.warning("Laden aus Datenbank fehlgeschlagen (%s). Fallback auf RSS-Einlesen...", exc)

    logger.info("📡 [Streamlit] Lese alle RSS-Feeds frisch aus dem Internet ein...")
    t0 = time.time()
    data = collect_all_news(save_to_db=True)
    duration = time.time() - t0
    total_articles = sum(len(items) for items in data.values())
    logger.info("✅ [Streamlit] %d Artikel über %d Kategorien in %.2fs geladen.", total_articles, len(data), duration)
    return data

def get_sources_config():
    """Liest die Konfiguration direkt und unzensiert/ungecacht von der Festplatte."""
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
else:
    # Wenn sich sources.yaml auf der Festplatte/GitHub geändert hat und der Nutzer keine ungespeicherten Änderungen hat:
    if st.session_state.get("last_loaded_saved_config") != saved_sources_config:
        if not st.session_state.get("has_unsaved_changes", False) and st.session_state.get("working_sources_config") == st.session_state.get("last_loaded_saved_config"):
            st.session_state["working_sources_config"] = copy.deepcopy(saved_sources_config)
            st.session_state["last_loaded_saved_config"] = copy.deepcopy(saved_sources_config)

working_config = st.session_state["working_sources_config"]

# Aktions-Puffer Intervall aus Konfiguration synchronisieren und Timer sicherstellen
sync_interval_cfg = working_config.get("settings", {}).get("batch_sync_interval_minutes", DEFAULT_BUFFER_INTERVAL_MINUTES)
try:
    action_buffer.set_interval_minutes(int(sync_interval_cfg))
except Exception:
    action_buffer.set_interval_minutes(DEFAULT_BUFFER_INTERVAL_MINUTES)
action_buffer.start_periodic_timer()

def harvest_global_settings():
    """Übernimmt ggf. im Formular eingetragene globale Einstellungen in den Arbeitsentwurf."""
    settings = st.session_state["working_sources_config"].setdefault("settings", {})
    settings.pop("max_articles_per_category", None)
    if "input_setting_lang" in st.session_state:
        settings["language"] = str(st.session_state["input_setting_lang"])
    if "input_setting_style" in st.session_state:
        settings["summary_style"] = str(st.session_state["input_setting_style"])
    if "input_setting_sync_interval" in st.session_state:
        try:
            val_mins = int(st.session_state["input_setting_sync_interval"])
            settings["batch_sync_interval_minutes"] = val_mins
            action_buffer.set_interval_minutes(val_mins)
        except (ValueError, TypeError):
            settings["batch_sync_interval_minutes"] = DEFAULT_BUFFER_INTERVAL_MINUTES
    if "input_setting_app_url" in st.session_state:
        settings["streamlit_app_url"] = str(st.session_state["input_setting_app_url"]).strip()
    if "input_setting_max_age_weeks" in st.session_state:
        try:
            settings["max_article_age_weeks"] = int(st.session_state["input_setting_max_age_weeks"])
        except (ValueError, TypeError):
            settings["max_article_age_weeks"] = DEFAULT_MAX_ARTICLE_AGE_WEEKS
    if "input_setting_filter_ads" in st.session_state:
        settings["filter_ads"] = bool(st.session_state["input_setting_filter_ads"])
    if "input_setting_ad_keywords" in st.session_state:
        raw_kws = str(st.session_state["input_setting_ad_keywords"])
        settings["ad_keywords"] = [k.strip() for k in raw_kws.split(",") if k.strip()]
    if "input_ki_prompt_directives" in st.session_state:
        settings["custom_prompt_directives"] = str(st.session_state["input_ki_prompt_directives"]).strip()
    if "input_ki_main_prompt" in st.session_state:
        settings["custom_main_prompt"] = str(st.session_state["input_ki_main_prompt"]).strip()

def perform_save_all():
    """Speichert den gesamten Arbeitsentwurf persistent in sources.yaml und synchronisiert mit GitHub."""
    harvest_global_settings()
    cfg_to_save = st.session_state.get("working_sources_config", {})
    # Immer im Tab Verwalten bleiben
    st.session_state["pending_nav_tab"] = "manage"
    st.query_params["tab"] = "manage"
    with st.spinner("💾 Speichere Konfiguration & synchronisiere mit GitHub / CDN... Bitte kurz warten."):
        try:
            # RSS-Feeds vor dem Push frisch aufbereiten, damit sie sofort aktuell auf GitHub/CDN landen
            try:
                cached_news = get_news_data()
                app_base = cfg_to_save.get("settings", {}).get("streamlit_app_url") or get_streamlit_app_url()
                export_all_rss_feeds(cached_news, config=cfg_to_save, base_url=app_base)
            except Exception as e_rss:
                logger.warning("Lokaler RSS-Feed Export vor Save übersprungen: %s", e_rss)

            gh_res = save_sources(cfg_to_save, sync_github=True)
            st.cache_data.clear()
            fresh_cfg = load_sources()
            st.session_state["working_sources_config"] = copy.deepcopy(fresh_cfg)
            st.session_state["last_loaded_saved_config"] = copy.deepcopy(fresh_cfg)
            st.session_state["has_unsaved_changes"] = False
            if gh_res.get("success"):
                st.session_state["save_feedback"] = ("success", "Alle Änderungen erfolgreich in `config/sources.yaml` und auf dem RSS-CDN gespeichert!")
                st.toast("Gespeichert & mit GitHub / CDN synchronisiert!", icon="🚀")
            else:
                err = gh_res.get("error")
                if err and "Kein GITHUB_TOKEN" not in err:
                    st.session_state["save_feedback"] = ("warning", f"In `sources.yaml` gespeichert, aber GitHub-Sync fehlgeschlagen: {err}")
                else:
                    st.session_state["save_feedback"] = ("success", "Alle Änderungen erfolgreich in `config/sources.yaml` gespeichert!")
                    st.toast("In sources.yaml gespeichert!", icon="💾")
            st.rerun()
        except Exception as e:
            st.error(f"Fehler beim Speichern: {e}")

def perform_discard_all():
    """Verwirft alle ungespeicherten Änderungen und setzt auf den Stand der sources.yaml zurück."""
    st.cache_data.clear()
    fresh_cfg = load_sources()
    st.session_state["working_sources_config"] = copy.deepcopy(fresh_cfg)
    st.session_state["last_loaded_saved_config"] = copy.deepcopy(fresh_cfg)
    st.session_state["has_unsaved_changes"] = False
    st.session_state["pending_nav_tab"] = "manage"
    st.query_params["tab"] = "manage"
    st.session_state.pop("last_edited_category", None)
    for k in list(st.session_state.keys()):
        if (
            k.startswith("edit_name_")
            or k.startswith("edit_url_")
            or k.startswith("edit_inc_")
            or k.startswith("edit_exc_")
            or k.startswith("edit_cat_")
            or k.startswith("edit_custom_cat_")
            or k.startswith("top_edit_")
            or k.startswith("top_custom_")
            or k.startswith("input_setting_")
        ):
            del st.session_state[k]
    st.toast("Alle Änderungen verworfen. Gespeicherter Stand wiederhergestellt.", icon="↩️")
    st.rerun()

has_unsaved_changes = bool(
    st.session_state.get("has_unsaved_changes", False) or
    (working_config != saved_sources_config)
)


# --- Sidebar ---
app_version = get_app_version()
st.sidebar.markdown(
    f"<div style='display:flex; align-items:center; margin-top:0.2rem; margin-bottom:0.35rem;'>"
    f"<h2 style='margin:0; font-size:1.35rem; line-height:1.2; font-weight:700;'>📰 News Bot</h2>"
    f"<span style='margin-left:10px; font-size:0.72rem; font-weight:600; padding:2px 8px; border-radius:6px; background:rgba(37, 99, 235, 0.1); border:1px solid rgba(37, 99, 235, 0.25); color:#2563eb; letter-spacing:0.02em; display:inline-block; line-height:1.2;'>{app_version}</span>"
    f"</div>",
    unsafe_allow_html=True,
)

# GitHub-Synchronisation Statusanzeige in der Navigationsleiste
gh_cfg = get_github_sync_config()
if gh_cfg.get("token"):
    st.sidebar.markdown(
        f"<div style='display:flex; align-items:center; gap:5px; font-size:0.8rem; color:#10b981; margin-bottom:0.5rem;'>"
        f"<span>🐙</span><span><b>GitHub-Sync aktiv</b> ({gh_cfg['branch']})</span>"
        f"</div>",
        unsafe_allow_html=True
    )

# API-Key Management
configured_key = get_configured_api_key()
user_api_key = None

if configured_key:
    # Verbunden: Kein Text für maximale Kompaktheit
    user_api_key = configured_key
else:
    # Nur anzeigen, wenn keine Verbindung möglich ist (in Rot)
    st.sidebar.error("❌ Keine Gemini API-Verbindung", icon="🔴")
    user_api_key = st.sidebar.text_input(
        "Gemini API-Key eingeben:",
        type="password",
        help="Erstelle einen kostenlosen Key auf https://aistudio.google.com/ oder hinterlege ihn in Streamlit Secrets.",
    )

# Model Selection
selected_model = st.sidebar.selectbox(
    "KI-Modell",
    options=AVAILABLE_GEMINI_MODELS,
    index=0,
    help="Gemini 3.8 Flash ist das neueste Modell. Bei hoher Auslastung federt die Fallback-Kette automatisch bis 3.5 ab.",
)

st.sidebar.markdown("---")

# Refresh Button
if st.sidebar.button("🔄 Feeds neu laden", use_container_width=True, help="Liest alle RSS-Feeds frisch ein"):
    logger.info("🔄 [Streamlit] Nutzer klickte 'Feeds neu laden'. Lese alle RSS-Feeds frisch ein...")
    st.cache_data.clear()
    with st.spinner("Lese alle RSS-Feeds frisch aus dem Internet ein..."):
        get_news_data(force_live_fetch=True)
    st.toast("Feeds wurden frisch eingelesen & in Datenbank gesichert!", icon="📰")
    st.rerun()

try:
    from src.storage import get_turso_config
    _t_url, _t_key = get_turso_config()
    if _t_url and _t_key:
        st.sidebar.caption("🗄️ Cloud-DB: **Turso aktiv**")
    else:
        st.sidebar.caption("📁 DB: **Lokaler Modus**")
except Exception:
    pass

st.sidebar.markdown("---")

qp_category = st.query_params.get("category", "").strip()
qp_feed = st.query_params.get("feed", "").strip()
qp_tab = (st.query_params.get("tab") or st.query_params.get("page") or st.query_params.get("view") or "").strip().lower()

# Tab identifier constants
TAB_ID_ARTICLES = "articles"
TAB_ID_KI = "ki"
TAB_ID_MANAGE = "manage"
TAB_ID_FEEDLY = "feedly"

# Tab Labels (Feste Reihenfolge: Artikel, KI, Verwalten, Feedly)
TAB_LABEL_ARTICLES = "📋 Artikel"
TAB_LABEL_KI = "✨ KI"
manage_suffix = " 🔴" if has_unsaved_changes else ""
TAB_LABEL_MANAGE = f"⚙️ Verwalten{manage_suffix}"
TAB_LABEL_FEEDLY = "📡 Feedly"

TAB_ORDER = [TAB_LABEL_ARTICLES, TAB_LABEL_KI, TAB_LABEL_MANAGE, TAB_LABEL_FEEDLY]

def label_to_tab_id(label: str) -> str:
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
    if tab_id == TAB_ID_KI or tab_id == "briefing":
        return TAB_LABEL_KI
    if tab_id == TAB_ID_MANAGE or tab_id in ["settings", "feeds", "quellen"]:
        return TAB_LABEL_MANAGE
    if tab_id in [TAB_ID_FEEDLY, "rss", "feeds_rss"]:
        return TAB_LABEL_FEEDLY
    return TAB_LABEL_ARTICLES

VALID_TAB_IDS = {TAB_ID_ARTICLES, TAB_ID_KI, TAB_ID_MANAGE, TAB_ID_FEEDLY}

def get_persisted_active_tab() -> str | None:
    """Liest den zuletzt aktiven Nav-Tab aus den HTTP-Cookies aus."""
    if hasattr(st, "context") and hasattr(st.context, "cookies"):
        try:
            val = st.context.cookies.get(COOKIE_TAB_NAME)
            if val in VALID_TAB_IDS:
                return val
        except Exception:
            pass
    if cookie_controller:
        try:
            val = cookie_controller.get(COOKIE_TAB_NAME)
            if val in VALID_TAB_IDS:
                return val
        except Exception:
            pass
    return None

def persist_active_tab(active_nav_tab: str) -> None:
    """Synchronisiert und speichert den aktiven Tab in Session, Cookie, LocalStorage und Browser-URL."""
    st.session_state["active_nav_tab"] = active_nav_tab
    st.session_state["main_tabs_nav"] = tab_id_to_label(active_nav_tab)
    if st.query_params.get("tab") != active_nav_tab:
        st.query_params["tab"] = active_nav_tab

    # Nur synchronisieren, wenn sich der Tab geändert hat oder beim Erstaufruf dieser Session
    if st.session_state.get("_synced_active_tab") == active_nav_tab:
        return
    st.session_state["_synced_active_tab"] = active_nav_tab

    if cookie_controller:
        try:
            cookie_controller.set(
                COOKIE_TAB_NAME,
                active_nav_tab,
                max_age=31536000.0,
                expires=datetime.now() + timedelta(days=365),
                same_site="lax"
            )
        except Exception:
            pass

    embed_client_script(f"""
    (function() {{
        var tab = "{active_nav_tab}";
        try {{
            document.cookie = "{COOKIE_TAB_NAME}=" + encodeURIComponent(tab) + "; path=/; max-age=31536000; SameSite=Lax";
            localStorage.setItem("{COOKIE_TAB_NAME}", tab);
            sessionStorage.setItem("{COOKIE_TAB_NAME}", tab);
            if (window.parent && window.parent !== window) {{
                try {{
                    window.parent.document.cookie = "{COOKIE_TAB_NAME}=" + encodeURIComponent(tab) + "; path=/; max-age=31536000; SameSite=Lax";
                    window.parent.localStorage.setItem("{COOKIE_TAB_NAME}", tab);
                    window.parent.sessionStorage.setItem("{COOKIE_TAB_NAME}", tab);
                }} catch(e) {{}}
            }}
        }} catch(e) {{}}

        // Browser-URL synchronisieren (iframe-resilient für Streamlit Cloud & Standalone)
        var syncUrl = function(win, targetTab) {{
            if (!win || !win.location) return;
            var t = targetTab || tab;
            try {{
                var url = new URL(win.location.href);
                if (url.searchParams.get("tab") !== t) {{
                    url.searchParams.set("tab", t);
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

        var setActiveTabClient = function(tabId, tabIdx) {{
            if (!tabId) return;
            // 1. Sidebar-Buttons synchronisieren (Klasse active-nav-tab umschalten)
            var sideBtns = document.querySelectorAll('.custom-nav-btn');
            for (var i = 0; i < sideBtns.length; i++) {{
                if (sideBtns[i].getAttribute('data-tab-id') === tabId) {{
                    sideBtns[i].classList.add('active-nav-tab');
                }} else {{
                    sideBtns[i].classList.remove('active-nav-tab');
                }}
            }}

            // 2. Den echten Streamlit-Tab im DOM anklicken, falls noch nicht aktiv (0ms clientseitig)
            var tabs = document.querySelectorAll('[data-testid="stTabs"] [data-testid="stTab"]');
            if (tabs && tabs[tabIdx]) {{
                var isSelected = tabs[tabIdx].getAttribute('aria-selected') === 'true' || tabs[tabIdx].classList.contains('active');
                if (!isSelected) {{
                    tabs[tabIdx].click();
                }}
            }}

            // 3. Cookie & LocalStorage & URL History sofort synchronisieren (ohne Server-Roundtrip!)
            try {{
                var cStr = "{COOKIE_TAB_NAME}=" + encodeURIComponent(tabId) + "; path=/; max-age=31536000; SameSite=Lax";
                document.cookie = cStr;
                localStorage.setItem("{COOKIE_TAB_NAME}", tabId);
                sessionStorage.setItem("{COOKIE_TAB_NAME}", tabId);
                if (window.parent && window.parent !== window) {{
                    try {{
                        window.parent.document.cookie = cStr;
                        window.parent.localStorage.setItem("{COOKIE_TAB_NAME}", tabId);
                        window.parent.sessionStorage.setItem("{COOKIE_TAB_NAME}", tabId);
                    }} catch(pe) {{}}
                }}
            }} catch(err) {{}}

            try {{
                syncUrl(window, tabId);
                if (window.parent && window.parent !== window) {{
                    syncUrl(window.parent, tabId);
                }}
            }} catch(err) {{}}
        }};
        window._newsBotSetActiveTabClient = setActiveTabClient;

        // Sofortiges 0-ms-Tab-Sync bei Klick im Frontend (Top-Tabs sowie linke Sidebar-Buttons)
        if (!window._newsBotTabClickListenerInstalled) {{
            window._newsBotTabClickListenerInstalled = true;
            document.addEventListener("click", function(evt) {{
                // Klick auf linken Sidebar-Navigationsbutton
                var sideBtn = evt.target && evt.target.closest ? evt.target.closest('.custom-nav-btn') : null;
                if (sideBtn) {{
                    var tabId = sideBtn.getAttribute('data-tab-id');
                    var tabIdx = parseInt(sideBtn.getAttribute('data-tab-idx') || '0', 10);
                    setActiveTabClient(tabId, tabIdx);
                    return;
                }}

                // Klick auf oberen Streamlit-Tab
                var tabBtn = evt.target && evt.target.closest ? evt.target.closest('[data-testid="stTab"], [data-baseweb="tab"], button[role="tab"]') : null;
                if (tabBtn && !tabBtn.classList.contains('custom-nav-btn')) {{
                    var tabs = Array.from(document.querySelectorAll('[data-testid="stTabs"] [data-testid="stTab"]'));
                    var idx = tabs.indexOf(tabBtn);
                    var txt = tabBtn.innerText || tabBtn.textContent || "";
                    var tabId = "articles";
                    if (txt.indexOf("KI") !== -1 && txt.indexOf("API") === -1) {{
                        tabId = "ki";
                        if (idx === -1) idx = 1;
                    }} else if (txt.indexOf("Verwalten") !== -1 || txt.indexOf("Quellen") !== -1) {{
                        tabId = "manage";
                        if (idx === -1) idx = 2;
                    }} else if (txt.indexOf("Feedly") !== -1 || txt.indexOf("RSS") !== -1) {{
                        tabId = "feedly";
                        if (idx === -1) idx = 3;
                    }} else if (txt.indexOf("Artikel") !== -1) {{
                        tabId = "articles";
                        if (idx === -1) idx = 0;
                    }}
                    if (idx === -1) idx = 0;
                    setActiveTabClient(tabId, idx);
                    return;
                }}
            }}, true);
        }}

        // Sicherstellen, dass nach Reload/F5 aktiver Tab und Sidebar exakt synchron stehen
        setTimeout(function() {{
            var tabs = document.querySelectorAll('[data-testid="stTabs"] [data-testid="stTab"]');
            var sideBtns = document.querySelectorAll('.custom-nav-btn');
            var tIdx = 0;
            if (tab === "ki") tIdx = 1;
            else if (tab === "manage") tIdx = 2;
            else if (tab === "feedly") tIdx = 3;
            if (tabs && tabs[tIdx]) {{
                var isSelected = tabs[tIdx].getAttribute('aria-selected') === 'true' || tabs[tIdx].classList.contains('active');
                if (!isSelected) {{
                    tabs[tIdx].click();
                }}
            }}
            for (var j = 0; j < sideBtns.length; j++) {{
                if (sideBtns[j].getAttribute('data-tab-id') === tab) {{
                    sideBtns[j].classList.add('active-nav-tab');
                }} else {{
                    sideBtns[j].classList.remove('active-nav-tab');
                }}
            }}
        }}, 60);
    }})();
    """)

# Aktiven Nav-Tab ermitteln & synchronisieren
if "pending_nav_tab" in st.session_state:
    target_tab_id = st.session_state.pop("pending_nav_tab")
    active_nav_tab = target_tab_id
    persist_active_tab(active_nav_tab)
elif qp_category or qp_feed:
    # E-Mail Deeplinks führen immer zu den Artikeln
    active_nav_tab = TAB_ID_ARTICLES
    persist_active_tab(active_nav_tab)
elif "main_tabs_nav" in st.session_state:
    # Der Benutzer hat direkt einen Tab in st.tabs angeklickt -> dessen Wahl respektieren!
    active_nav_tab = label_to_tab_id(st.session_state["main_tabs_nav"])
    persist_active_tab(active_nav_tab)
else:
    # Erstaufruf bzw. Browser F5-Refresh (st.session_state ist neu/leer):
    # 1. Bevorzugt den zuletzt gemerkten aktiven Tab aus dem Cookie übernehmen (bleibt beim F5-Refresh exakt am selben Tab)
    persisted_tab = get_persisted_active_tab()
    if persisted_tab:
        active_nav_tab = persisted_tab
    # 2. Fallback: Query-Param aus der URL prüfen
    elif qp_tab in ["ki", "briefing", "ai"]:
        active_nav_tab = TAB_ID_KI
    elif qp_tab in ["rss", "feeds_rss", "feedly"]:
        active_nav_tab = TAB_ID_FEEDLY
    elif qp_tab in ["manage", "settings", "feeds", "quellen"]:
        active_nav_tab = TAB_ID_MANAGE
    else:
        active_nav_tab = TAB_ID_ARTICLES
    persist_active_tab(active_nav_tab)

def navigate_to(tab_name: str):
    st.session_state["pending_nav_tab"] = tab_name
    st.session_state["active_nav_tab"] = tab_name
    st.session_state["main_tabs_nav"] = tab_id_to_label(tab_name)
    st.query_params["tab"] = tab_name
    for k in ["page", "view", "category", "feed"]:
        if k in st.query_params:
            del st.query_params[k]
    if tab_name == TAB_ID_ARTICLES:
        st.session_state["sel_articles_category"] = "Alle Kategorien"
    st.rerun()

manage_btn_label = TAB_LABEL_MANAGE

active_class_articles = "active-nav-tab" if active_nav_tab == TAB_ID_ARTICLES else ""
active_class_ki = "active-nav-tab" if active_nav_tab == TAB_ID_KI else ""
active_class_manage = "active-nav-tab" if active_nav_tab == TAB_ID_MANAGE else ""
active_class_feedly = "active-nav-tab" if active_nav_tab == TAB_ID_FEEDLY else ""

st.sidebar.markdown(f"""
<div class="custom-nav-container" data-testid="stSidebarNavCustom">
    <button type="button" class="custom-nav-btn {active_class_articles}" data-tab-id="{TAB_ID_ARTICLES}" data-tab-idx="0">📋 Artikel</button>
    <button type="button" class="custom-nav-btn {active_class_ki}" data-tab-id="{TAB_ID_KI}" data-tab-idx="1">✨ KI</button>
    <button type="button" class="custom-nav-btn {active_class_manage}" data-tab-id="{TAB_ID_MANAGE}" data-tab-idx="2">{manage_btn_label}</button>
    <button type="button" class="custom-nav-btn {active_class_feedly}" data-tab-id="{TAB_ID_FEEDLY}" data-tab-idx="3">📡 Feedly</button>
</div>
""", unsafe_allow_html=True)

# Unsaved changes status & buttons in sidebar
if has_unsaved_changes and (st.session_state.get("auth_role") == ROLE_ADMIN or not get_configured_app_password()):
    st.sidebar.markdown("---")
    st.sidebar.warning("⚠️ **Ungespeicherte Änderungen!**")
    if st.sidebar.button("💾 Alle Änderungen speichern", type="primary", use_container_width=True, key="sb_save_all_btn"):
        perform_save_all()
    if st.sidebar.button("↩️ Änderungen verwerfen", use_container_width=True, key="sb_discard_all_btn"):
        perform_discard_all()

# Optional: Status & Logout-Button bei aktivem Passwortschutz
if get_configured_app_password():
    st.sidebar.markdown("---")
    current_role = st.session_state.get("auth_role", ROLE_READONLY)
    if current_role == ROLE_ADMIN:
        st.sidebar.markdown(
            '<div style="display:flex; align-items:center; gap:8px; padding:6px 10px; border-radius:6px; background:rgba(34, 197, 94, 0.12); border:1px solid rgba(34, 197, 94, 0.28); font-size:0.83rem; font-weight:600; color:#16a34a; margin-top:0.25rem; margin-bottom:0.55rem;">'
            '<span>🛡️</span><span>Admin (Vollzugriff)</span>'
            '</div>',
            unsafe_allow_html=True
        )
    else:
        st.sidebar.markdown(
            '<div style="display:flex; align-items:center; gap:8px; padding:6px 10px; border-radius:6px; background:rgba(59, 130, 246, 0.09); border:1px solid rgba(59, 130, 246, 0.28); font-size:0.83rem; font-weight:600; color:#2563eb; margin-top:0.25rem; margin-bottom:0.55rem;">'
            '<span>👁️</span><span>Lese-Modus (E-Mail)</span>'
            '</div>',
            unsafe_allow_html=True
        )
        with st.sidebar.popover("🔑 Admin-Freischaltung", use_container_width=True):
            st.caption("Passwort eingeben, um Feeds & Einstellungen bearbeiten zu können:")
            side_admin_pw = st.text_input("App-Passwort:", type="password", key="sidebar_admin_pw_input")
            if st.button("Als Admin aktivieren", type="primary", key="sidebar_admin_unlock_btn", use_container_width=True):
                expected_pw = get_configured_app_password()
                if side_admin_pw == expected_pw:
                    set_admin_session_cookie(expected_pw)
                    st.toast("Admin-Modus aktiviert!", icon="🛡️")
                    st.rerun()
                else:
                    st.error("Falsches Passwort.")

    if st.sidebar.button("🚪 Abmelden", use_container_width=True):
        st.session_state["authenticated"] = False
        st.session_state["auth_role"] = None
        if "auth" in st.query_params:
            del st.query_params["auth"]
        if "token" in st.query_params:
            del st.query_params["token"]
        embed_client_script(f"""
        (function() {{
            try {{
                localStorage.removeItem("{COOKIE_AUTH_NAME}");
                localStorage.removeItem("{COOKIE_ADMIN_NAME}");
                document.cookie = "{COOKIE_AUTH_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; SameSite=Lax; Secure";
                document.cookie = "{COOKIE_ADMIN_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; SameSite=Lax; Secure";
                if (window.parent && window.parent !== window) {{
                    window.parent.localStorage.removeItem("{COOKIE_AUTH_NAME}");
                    window.parent.localStorage.removeItem("{COOKIE_ADMIN_NAME}");
                    window.parent.document.cookie = "{COOKIE_AUTH_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; SameSite=Lax; Secure";
                    window.parent.document.cookie = "{COOKIE_ADMIN_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; SameSite=Lax; Secure";
                }}
            }} catch(e) {{}}
        }})();
        """)
        if cookie_controller:
            try:
                cookie_controller.remove(COOKIE_AUTH_NAME)
                cookie_controller.remove(COOKIE_ADMIN_NAME)
            except Exception:
                pass
        st.toast("Erfolgreich abgemeldet.", icon="🔒")
        st.rerun()

# --- Main Layout & Data Loading ---
news_data = get_news_data()

# Ausfiltern aller gelesenen/archivierten Artikel
if "archived_urls" not in st.session_state:
    try:
        from src.storage import get_storage
        _storage = get_storage()
        st.session_state["archived_urls"] = _storage.get_archived_urls()
    except Exception as exc:
        logger.debug("Archivierte URLs konnten nicht geladen werden: %s", exc)
        st.session_state["archived_urls"] = set()

archived_urls_set = st.session_state.get("archived_urls", set())
if archived_urls_set:
    news_data = {
        cat: [it for it in items if (it.get("link") or "").strip() not in archived_urls_set]
        for cat, items in news_data.items()
    }

# Altersfilterung gemäß globalen Einstellungen anwenden (Standard: 20 Wochen)
current_settings = working_config.get("settings", {})
max_age_weeks_setting = current_settings.get("max_article_age_weeks")
if max_age_weeks_setting is None:
    max_age_weeks_setting = current_settings.get("max_age_weeks", DEFAULT_MAX_ARTICLE_AGE_WEEKS)
try:
    active_max_age_weeks = int(max_age_weeks_setting) if max_age_weeks_setting is not None else DEFAULT_MAX_ARTICLE_AGE_WEEKS
except (ValueError, TypeError):
    active_max_age_weeks = DEFAULT_MAX_ARTICLE_AGE_WEEKS

news_data = filter_news_data_by_age(news_data, max_age_weeks=active_max_age_weeks)

# Nutzer-Bewertungen (Likes / Dislikes) aus der Datenbank laden & in Artikel einbetten
if "feedback_map" not in st.session_state:
    try:
        from src.storage import get_storage
        _storage = get_storage()
        st.session_state["feedback_map"] = _storage.get_feedback_map()
    except Exception as exc:
        st.session_state["feedback_map"] = {}

current_fb_map = st.session_state.get("feedback_map", {})
liked_articles_count = 0
for cat_items in news_data.values():
    for it in cat_items:
        it_url = it.get("link", "").strip()
        if it_url in current_fb_map:
            it["feedback"] = current_fb_map[it_url]
        if it.get("feedback") == 1:
            liked_articles_count += 1

# Kennzahlen berechnen
total_categories = len(news_data)
total_articles = sum(len(items) for items in news_data.values())
total_feeds = sum(len(c.get("feeds", [])) for c in working_config.get("categories", []))

# Neue Artikel im Pool ermitteln
new_pool_articles = get_new_articles_count(news_data)

init_loader_placeholder.empty()

st.title("📰 Daily News Briefing", anchor=False)
st.caption(f"Aktualisiert: {get_local_now().strftime('%d.%m.%Y, %H:%M Uhr')}")

# KPI Row (Kompakt & Mobile-optimiert)
engine_short = selected_model.replace("gemini-", "").replace("-flash-lite", " Flash-Lite").replace("-flash", " Flash")

# Pool-Badge: Blaues Highlight NUR wenn tatsächlich neue Artikel hinzugekommen sind
if new_pool_articles > 0:
    pool_chip_html = f'<span class="kpi-chip kpi-pool" title="{new_pool_articles} neue Artikel seit dem letzten Briefing">📄 <strong>{total_articles}</strong> Artikel im Pool (+{new_pool_articles} neu)</span>'
else:
    pool_chip_html = f'<span class="kpi-chip">📄 <strong>{total_articles}</strong> Artikel im Pool</span>'

liked_chip_html = f'<span class="kpi-chip" style="background-color:rgba(34, 197, 94, 0.12); border-color:rgba(34, 197, 94, 0.35); color:#16a34a;" title="{liked_articles_count} Artikel geliked (werden im KI-Briefing bevorzugt)">⭐ <strong>{liked_articles_count}</strong> Favoriten</span>' if liked_articles_count > 0 else ""

archived_count = len(archived_urls_set)
archived_chip_html = f'<span class="kpi-chip" style="background-color:rgba(100, 116, 139, 0.12); border-color:rgba(100, 116, 139, 0.35); color:#64748b;" title="{archived_count} Artikel als gelesen archiviert">📦 <strong>{archived_count}</strong> Gelesen</span>' if archived_count > 0 else ""

buf_interval_mins = action_buffer.get_interval_minutes()
p_reads, p_fb = action_buffer.get_pending_counts()
tot_pending_actions = p_reads + p_fb
if tot_pending_actions > 0:
    buffer_chip_html = f'<span class="kpi-chip" style="background-color:rgba(234, 179, 8, 0.15); border-color:rgba(234, 179, 8, 0.4); color:#b45309;" title="{tot_pending_actions} Aktionen im Puffer (Auto-Sync alle {buf_interval_mins} Min.)">📥 <strong>{tot_pending_actions}</strong> im Puffer</span>'
else:
    buffer_chip_html = f'<span class="kpi-chip" style="background-color:rgba(241, 245, 249, 0.8); border-color:rgba(203, 213, 225, 0.6); color:#64748b;" title="Aktions-Puffer aktiv (Auto-Sync alle {buf_interval_mins} Min.)">📥 <strong>Puffer synchron</strong></span>'

chips = [
    f'<span class="kpi-chip">📌 <strong>{total_categories}</strong> Kategorien</span>',
    f'<span class="kpi-chip">📡 <strong>{total_feeds}</strong> Feeds</span>',
    pool_chip_html,
]
if liked_chip_html:
    chips.append(liked_chip_html)
if archived_chip_html:
    chips.append(archived_chip_html)
chips.append(buffer_chip_html)
chips.append(f'<span class="kpi-chip">🤖 <strong>{engine_short}</strong></span>')

st.html(f'<div class="kpi-container">{"".join(chips)}</div>')

if new_pool_articles > 0:
    st.sidebar.markdown("---")
    if st.sidebar.button(
        "✓ Neue Artikel als gesehen markieren",
        use_container_width=True,
        key="sb_btn_mark_seen",
        help="Markiert alle aktuellen Artikel im Pool als bekannt/gelesen und setzt den Zähler '+X neu' auf 0 zurück (ohne ein neues KI-Briefing generieren zu müssen)."
    ):
        save_pool_state(news_data)
        st.toast("Pool-Status aktualisiert – alle neuen Artikel als gesehen markiert!", icon="✅")
        st.rerun()

is_admin = st.session_state.get("auth_role") == ROLE_ADMIN or not get_configured_app_password()

# Tabs in fester Reihenfolge: Artikel, KI, Verwalten, Feedly
default_tab_label = tab_id_to_label(active_nav_tab)
if default_tab_label not in TAB_ORDER:
    default_tab_label = TAB_ORDER[0]

tab_articles, tab_ki, tab_manage, tab_feedly = st.tabs(
    TAB_ORDER,
    default=default_tab_label,
    key="main_tabs_nav",
)

# ----------------- TAB: Artikel -----------------
with tab_articles:
    def get_article_timestamp(it: dict) -> float:
        ts = it.get("timestamp")
        if ts is not None and isinstance(ts, (int, float)) and ts > 0:
            return float(ts)
        p = it.get("published_parsed")
        if p and isinstance(p, time.struct_time):
            try:
                import calendar
                return float(calendar.timegm(p))
            except Exception:
                pass
        pub = it.get("published", "") or it.get("updated", "")
        if pub and isinstance(pub, str):
            try:
                import email.utils
                dt = email.utils.parsedate_to_datetime(pub.strip())
                if dt:
                    return dt.timestamp()
            except Exception:
                pass
            try:
                dt = datetime.fromisoformat(pub.strip().replace("Z", "+00:00"))
                return dt.timestamp()
            except Exception:
                pass
        return 0.0

    def format_article_date(it: dict) -> str:
        ts = get_article_timestamp(it)
        if ts > 0:
            formatted = format_local_dt(ts)
            if formatted:
                return formatted
        pub = it.get("published", "") or it.get("updated", "")
        if pub:
            return str(pub)[:30]
        return ""

    # 1. State initialisieren: Default ist IMMER "Alle Kategorien"
    for legacy_k in ["articles_selected_cat", "sel_articles_cat_widget"]:
        if legacy_k in st.session_state:
            del st.session_state[legacy_k]

    if "sel_articles_category" not in st.session_state:
        st.session_state["sel_articles_category"] = "Alle Kategorien"
    if "articles_cat_feed_memory" not in st.session_state:
        st.session_state["articles_cat_feed_memory"] = {}

    # Checkboxen Persistenz über Query Params (bleibt über Browser-Reloads / F5 erhalten)
    qp_exp_cats = st.query_params.get("exp_cats")
    qp_exp_feeds = st.query_params.get("exp_feeds")
    qp_sort = st.query_params.get("sort")

    # Standardmäßig beim ersten Aufruf IMMER alles zugeklappt lassen
    if "chk_expand_cats" not in st.session_state:
        st.session_state["chk_expand_cats"] = True if qp_exp_cats == "1" else False
    if "chk_expand_feeds" not in st.session_state:
        st.session_state["chk_expand_feeds"] = True if qp_exp_feeds == "1" else False

    # Sortierung: Standard ist AN (Älteste zuerst), Zustand über Cookies/LocalStorage/URL merken
    if "chk_sort_oldest" not in st.session_state:
        cookie_sort = None
        if hasattr(st, "context") and hasattr(st.context, "cookies"):
            try:
                cookie_sort = st.context.cookies.get("news_bot_sort_oldest")
            except Exception:
                pass
        if qp_sort == "newest":
            st.session_state["chk_sort_oldest"] = False
        elif qp_sort == "oldest":
            st.session_state["chk_sort_oldest"] = True
        elif cookie_sort == "0":
            st.session_state["chk_sort_oldest"] = False
        elif cookie_sort == "1":
            st.session_state["chk_sort_oldest"] = True
        else:
            # Standard ist AN: älteste zuerst
            st.session_state["chk_sort_oldest"] = True

    def on_toggle_expand_cats():
        val = bool(st.session_state.get("chk_expand_cats", False))
        if val:
            st.query_params["exp_cats"] = "1"
        else:
            if "exp_cats" in st.query_params:
                del st.query_params["exp_cats"]
            st.session_state["persisted_open_categories"] = set()

    def on_toggle_expand_feeds():
        val = bool(st.session_state.get("chk_expand_feeds", False))
        if val:
            st.query_params["exp_feeds"] = "1"
        else:
            if "exp_feeds" in st.query_params:
                del st.query_params["exp_feeds"]
            st.session_state["persisted_open_feeds"] = set()

    def on_toggle_sort():
        val = bool(st.session_state.get("chk_sort_oldest", True))
        st.query_params["sort"] = "oldest" if val else "newest"
        cookie_val = "1" if val else "0"
        embed_client_script(f"""
        (function() {{
            try {{
                document.cookie = "news_bot_sort_oldest={cookie_val}; path=/; max-age=31536000; SameSite=Lax";
                localStorage.setItem("news_bot_sort_oldest", "{cookie_val}");
                if (window.parent && window.parent !== window) {{
                    window.parent.document.cookie = "news_bot_sort_oldest={cookie_val}; path=/; max-age=31536000; SameSite=Lax";
                    window.parent.localStorage.setItem("news_bot_sort_oldest", "{cookie_val}");
                }}
            }} catch(e) {{}}
        }})();
        """)

    def on_article_feedback_change(article_url: str, widget_key: str, article_title: str = "") -> None:
        widget_val = st.session_state.get(widget_key)
        # st.feedback('thumbs'): 1 = Like, 0 = Dislike, None = unselected/neutral
        if widget_val == 1:
            new_fb = 1
        elif widget_val == 0:
            new_fb = -1
        else:
            new_fb = 0

        # 1. Feedback-Map in session_state aktualisieren
        if "feedback_map" not in st.session_state:
            st.session_state["feedback_map"] = {}
        st.session_state["feedback_map"][article_url] = new_fb

        # 2. In news_data aktualisieren
        for cat_items in news_data.values():
            for it in cat_items:
                if it.get("link", "").strip() == article_url:
                    it["feedback"] = new_fb

        # 3. Im Aktions-Puffer sammeln (Bulk-Persistenz nach Intervall oder Klick)
        action_buffer.queue_feedback(article_url, new_fb, article_title)

    def on_article_read_and_archive(article_item: dict[str, Any], category: str = "", feed_name: str = "") -> None:
        """
        Markiert einen Artikel als gelesen, entfernt ihn sofort aus der aktiven Ansicht
        und reiht ihn in den Aktions-Puffer ein (Bulk-Persistenz im Hintergrund nach Intervall oder Klick).
        Hält die betreffende Kategorie und den betreffenden Feed offen, damit die
        verbleibenden Cards nahtlos an Ort und Stelle nachrücken.
        """
        item_url = (article_item.get("link") or "").strip()
        if not item_url:
            return

        # 1. Sofort in session_state aufnehmen
        if "archived_urls" not in st.session_state:
            st.session_state["archived_urls"] = set()
        st.session_state["archived_urls"].add(item_url)

        # 2. Aus news_data im Memory entfernen (sofortiges Nachrücken der Cards)
        for cat_name, cat_items in list(news_data.items()):
            news_data[cat_name] = [it for it in cat_items if (it.get("link") or "").strip() != item_url]

        # 3. Kategorie & Feed im Session-Zustand merken & Scroll-Position vormerken
        if category:
            if "persisted_open_categories" not in st.session_state:
                st.session_state["persisted_open_categories"] = set()
            st.session_state["persisted_open_categories"].add(category)
        if feed_name:
            if "persisted_open_feeds" not in st.session_state:
                st.session_state["persisted_open_feeds"] = set()
            st.session_state["persisted_open_feeds"].add(feed_name)
            feed_slug = "".join(c if c.isalnum() else "_" for c in feed_name)
            st.session_state["last_read_feed_slug"] = feed_slug

        # 4. In Aktions-Puffer einreihen
        action_buffer.queue_read(article_item)

    def on_clear_search():
        st.session_state["input_search_query"] = ""
        st.session_state["sel_articles_rating"] = "Alle Bewertungen"

    # 1. Alle bekannten Kategorien (aus Konfiguration) ermitteln
    configured_cats = [
        c.get("name", "").strip()
        for c in working_config.get("categories", [])
        if c.get("name", "").strip()
    ]
    known_cats_set = set(configured_cats) if configured_cats else {k.strip() for k in news_data.keys() if k.strip()}
    sorted_all_categories = sorted(list(known_cats_set), key=lambda x: x.strip().lower())
    category_options = ["Alle Kategorien"] + sorted_all_categories

    # Wenn Deeplink-Parameter vorhanden sind, diese in die Session übernehmen
    if qp_category:
        for c in sorted_all_categories:
            if c.strip().lower() == qp_category.lower():
                st.session_state["sel_articles_category"] = c
                if qp_feed:
                    st.session_state["articles_cat_feed_memory"][c] = qp_feed
                    st.session_state[f"sel_feed_for_{c}"] = qp_feed
                break

    if st.session_state["sel_articles_category"] not in category_options:
        st.session_state["sel_articles_category"] = "Alle Kategorien"

    current_cat = st.session_state.get("sel_articles_category", "Alle Kategorien")

    # 2. Alle Feeds für die aktuelle Kategorie ermitteln (Konfiguration + geladene Artikel)
    feed_sources_set = set()
    if current_cat != "Alle Kategorien":
        for c in working_config.get("categories", []):
            if c.get("name", "").strip().lower() == current_cat.strip().lower():
                for f in c.get("feeds", []):
                    fname = f.get("name", "").strip()
                    if fname:
                        feed_sources_set.add(fname)
                break
        cat_items_pre = news_data.get(current_cat, [])
        feed_sources_set.update({item.get("source") for item in cat_items_pre if item.get("source")})
    else:
        for items in news_data.values():
            feed_sources_set.update({item.get("source") for item in items if item.get("source")})
        for c in working_config.get("categories", []):
            for f in c.get("feeds", []):
                fname = f.get("name", "").strip()
                if fname:
                    feed_sources_set.add(fname)

    # Falls Deeplink qp_feed angegeben ist: case-insensitives Matching auf bekannten Feed
    qp_feed_canonical = None
    if qp_feed:
        for f in feed_sources_set:
            if f.strip().lower() == qp_feed.lower():
                qp_feed_canonical = f
                break
        if not qp_feed_canonical:
            qp_feed_canonical = qp_feed
            feed_sources_set.add(qp_feed_canonical)

    feed_options = ["Alle Feeds"] + sorted(list(feed_sources_set), key=lambda x: x.strip().lower())

    feed_widget_key = f"sel_feed_for_{current_cat}"
    remembered_feed = st.session_state["articles_cat_feed_memory"].get(current_cat, "Alle Feeds")
    if qp_feed_canonical and current_cat != "Alle Kategorien":
        remembered_feed = qp_feed_canonical

    if remembered_feed not in feed_options:
        remembered_feed = "Alle Feeds"

    if feed_widget_key not in st.session_state or (qp_feed_canonical and st.session_state.get(feed_widget_key) != qp_feed_canonical):
        st.session_state[feed_widget_key] = remembered_feed

    # Zusammenklappbarer Filter- & Suchbereich (Mobile-optimiert)
    filter_summary_items = []
    if current_cat != "Alle Kategorien":
        filter_summary_items.append(f"📁 {current_cat}")
    curr_selected_feed = st.session_state.get(feed_widget_key, "Alle Feeds")
    if curr_selected_feed != "Alle Feeds":
        filter_summary_items.append(f"📡 {curr_selected_feed}")
    curr_rating = st.session_state.get("sel_articles_rating", "Alle Bewertungen")
    if curr_rating == "Nur Favoriten 👍":
        filter_summary_items.append("⭐ Nur Favoriten")
    elif curr_rating == "Nur Irrelevante 👎":
        filter_summary_items.append("👎 Nur Irrelevante")
    active_search_text = st.session_state.get("input_search_query", "").strip()
    if active_search_text:
        filter_summary_items.append(f"🔍 '{active_search_text}'")

    is_filtering = bool(
        current_cat != "Alle Kategorien"
        or curr_selected_feed != "Alle Feeds"
        or curr_rating != "Alle Bewertungen"
        or active_search_text
    )

    # Filterbox: Beim Aufruf über E-Mail Deeplinks und standardmäßig immer zugeklappt lassen!
    # Die aktiven Filter sieht der Nutzer direkt in der Zeile darunter.
    with st.expander("🔍 Filter & Suche", expanded=False, key="expander_filter_search"):
        # 1. Filter-Dropdowns: Kategorie, Feed & Bewertung
        filter_col_cat, filter_col_feed, filter_col_rating = st.columns([1.2, 1.2, 1.0])
        with filter_col_cat:
            selected_cat = st.selectbox(
                "Kategorie:",
                options=category_options,
                key="sel_articles_category"
            )
            if qp_category and selected_cat.strip().lower() != qp_category.lower():
                if "category" in st.query_params:
                    del st.query_params["category"]
                if "feed" in st.query_params:
                    del st.query_params["feed"]

        with filter_col_feed:
            selected_feed = st.selectbox(
                "Feed / Quelle:",
                options=feed_options,
                key=feed_widget_key
            )
            st.session_state["articles_cat_feed_memory"][selected_cat] = selected_feed
            if qp_feed and selected_feed.strip().lower() != qp_feed.lower():
                if "feed" in st.query_params:
                    del st.query_params["feed"]

        with filter_col_rating:
            selected_rating = st.selectbox(
                "Bewertung:",
                options=["Alle Bewertungen", "Nur Favoriten 👍", "Nur Irrelevante 👎"],
                key="sel_articles_rating"
            )

        # 2. Suchleiste: Textfeld, Reset-Button (✕) und Go-Button
        col_s_input, col_s_clear, col_s_go = st.columns([6, 0.7, 0.9], vertical_alignment="bottom")
        with col_s_input:
            search_query = st.text_input(
                "🔍 Suche:",
                placeholder="z. B. AI, Apple, Wirtschaft...",
                key="input_search_query",
            )
        with col_s_clear:
            st.button(
                "✕",
                key="btn_search_clear",
                type="secondary",
                use_container_width=True,
                on_click=on_clear_search,
                help="Suche zurücksetzen",
            )
        with col_s_go:
            st.button(
                "Go",
                key="btn_search_go",
                type="primary",
                use_container_width=True,
                help="Suche ausführen",
            )

        c_tog1, c_tog2, c_tog3 = st.columns(3)
        with c_tog1:
            expand_cats = st.checkbox("📂 Kategorien auf", key="chk_expand_cats", on_change=on_toggle_expand_cats, help="Alle Kategorien aufklappen")
        with c_tog2:
            expand_feeds = st.checkbox("📡 Feeds auf", key="chk_expand_feeds", on_change=on_toggle_expand_feeds, help="Alle Feeds innerhalb der Kategorien aufklappen")
        with c_tog3:
            sort_oldest = st.checkbox("⏳ Älteste zuerst", key="chk_sort_oldest", on_change=on_toggle_sort, help="Standard: Älteste Artikel zuerst (chronologisch). Deaktivieren, um die neuesten Artikel zuerst anzuzeigen.")

    is_filtering = bool(
        (selected_cat and selected_cat != "Alle Kategorien")
        or (selected_feed and selected_feed != "Alle Feeds")
        or (selected_rating and selected_rating != "Alle Bewertungen")
        or (search_query and search_query.strip())
    )

    if filter_summary_items:
        st.caption(f"⚡ Aktive Filter: **{' • '.join(filter_summary_items)}**")

    # Aktions-Puffer Status & Manuelle Synchronisierung
    pending_reads, pending_fb = action_buffer.get_pending_counts()
    total_pending = pending_reads + pending_fb
    buf_interval = action_buffer.get_interval_minutes()

    with st.container(border=True):
        col_buf_txt, col_buf_btn = st.columns([3.5, 1.5], vertical_alignment="center")
        with col_buf_txt:
            if total_pending > 0:
                parts = []
                if pending_reads > 0:
                    parts.append(f"**{pending_reads}** als gelesen vorgemerkt")
                if pending_fb > 0:
                    parts.append(f"**{pending_fb}** Bewertungen")
                summary_str = " • ".join(parts)
                st.markdown(f"📥 **Aktions-Puffer aktiv:** {summary_str}")
                st.caption(f"Automatischer Bulk-Sync alle {buf_interval} Minuten aktiv.")
            else:
                st.markdown("📥 **Aktions-Puffer:** Alle Aktionen mit Datenbank synchronisiert (0 vorgemerkt)")
                st.caption(f"Automatischer Bulk-Sync alle {buf_interval} Minuten aktiv.")
        with col_buf_btn:
            sync_btn_disabled = (total_pending == 0)
            if st.button(
                "💾 Jetzt synchronisieren",
                key="btn_sync_buffer_now",
                type="primary" if total_pending > 0 else "secondary",
                use_container_width=True,
                disabled=sync_btn_disabled,
                help="Schreibt alle gepufferten Aktionen sofort dauerhaft in die Datenbank" if total_pending > 0 else "Keine ausstehenden Aktionen im Puffer",
            ):
                with st.spinner("Synchronisiere Puffer mit Datenbank..."):
                    arch_n, fb_n = action_buffer.flush()
                    st.toast(f"Puffer synchronisiert: {arch_n} archiviert, {fb_n} Feedback gespeichert!", icon="💾")
                    st.rerun()

    col_stat_placeholder = st.empty()

    descending_sort = not bool(st.session_state.get("chk_sort_oldest", True))

    def get_sort_key(it: dict) -> float:
        ts = get_article_timestamp(it)
        if descending_sort:
            return ts if ts > 0 else -1.0
        else:
            return ts if ts > 0 else float("inf")

    displayed_count = 0
    categories_rendered = 0
    rendered_element_keys: set[str] = set()

    for category in sorted_all_categories:
        if selected_cat != "Alle Kategorien" and category != selected_cat:
            continue

        cat_items = news_data.get(category, [])

        # Artikel filtern nach Feed, Bewertung und Suche
        cat_matching = []
        for item in cat_items:
            if selected_feed != "Alle Feeds" and (item.get("source") or "").strip().lower() != selected_feed.strip().lower():
                continue
            item_url = item.get("link", "").strip()
            item_fb = st.session_state.get("feedback_map", {}).get(item_url, item.get("feedback", 0))
            if curr_rating == "Nur Favoriten 👍" and item_fb != 1:
                continue
            if curr_rating == "Nur Irrelevante 👎" and item_fb != -1:
                continue
            if search_query:
                q = search_query.lower()
                if q not in item.get("title", "").lower() and q not in item.get("summary", "").lower():
                    continue
                cat_matching.append(item)
            else:
                cat_matching.append(item)

        if not cat_matching:
            continue

        categories_rendered += 1
        # Alle Artikel der Kategorie nach Datum sortieren
        cat_matching.sort(key=get_sort_key, reverse=descending_sort)

        cat_slug = "".join(c if c.isalnum() else "_" for c in category)
        # Deeplink aus E-Mail klappt diese Kategorie immer auf, sonst Filter-Checkbox oder aktive Suche/Auswahl
        cat_is_open = True if (
            is_filtering
            or (qp_category and category.strip().lower() == qp_category.lower())
            or bool(st.session_state.get("chk_expand_cats", False))
            or category in st.session_state.get("persisted_open_categories", set())
        ) else False

        feeds_in_cat = {item.get("source") for item in cat_matching if item.get("source")}
        num_feeds = len(feeds_in_cat)
        feed_label = f"{num_feeds} Feed" if num_feeds == 1 else f"{num_feeds} Feeds"
        item_label = f"{len(cat_matching)} Artikel" if len(cat_matching) != 1 else "1 Artikel"

        with st.expander(f"📁 **{category}** ({feed_label}, {item_label})", expanded=cat_is_open):
            # Innerhalb der Kategorie nach Feed gruppieren
            feeds_dict = {}
            for item in cat_matching:
                src = item.get("source", "Unbekannt")
                feeds_dict.setdefault(src, []).append(item)

            sorted_feed_names = sorted(feeds_dict.keys(), key=lambda x: x.strip().lower())

            for feed_name in sorted_feed_names:
                f_items_raw = feeds_dict[feed_name]
                seen_f_urls = set()
                f_items = []
                for it in f_items_raw:
                    u = (it.get("link") or "").strip()
                    if u and u in seen_f_urls:
                        continue
                    if u:
                        seen_f_urls.add(u)
                    f_items.append(it)
                # Artikel innerhalb des Feeds nach Datum sortieren
                f_items.sort(key=get_sort_key, reverse=descending_sort)

                feed_slug = "".join(c if c.isalnum() else "_" for c in feed_name)
                feed_limit_key = f"feed_limit_{feed_slug}"
                DEFAULT_FEED_PAGE_SIZE = 20
                current_feed_limit = st.session_state.get(feed_limit_key, DEFAULT_FEED_PAGE_SIZE)

                # Bei aktiver Suche oder Bewertungsfilter alle Treffer anzeigen, sonst paginiert
                if search_query or (curr_rating and curr_rating != "Alle Bewertungen"):
                    visible_items = f_items
                else:
                    visible_items = f_items[:current_feed_limit]

                # Deeplink aus E-Mail klappt diesen Feed immer auf, sonst Filter-Checkbox oder aktive Suche/Auswahl
                feed_is_open = True if (
                    is_filtering
                    or (qp_feed and feed_name.strip().lower() == qp_feed.lower())
                    or bool(st.session_state.get("chk_expand_feeds", False))
                    or feed_name in st.session_state.get("persisted_open_feeds", set())
                ) else False

                with st.expander(f"📡 **{feed_name}** ({len(f_items)} Artikel)", expanded=feed_is_open):
                    st.html(f'<div id="anchor-feed-{feed_slug}" style="height:0; margin:0; padding:0;"></div>')
                    cols = st.columns(2)
                    for idx, item in enumerate(visible_items):
                        displayed_count += 1
                        with cols[idx % 2]:
                            with st.container(border=True):
                                item_url = (item.get("link") or "").strip()
                                clean_title = clean_html_text(item.get("title", "Kein Titel"))
                                clean_summary = format_summary_html(item.get("summary", ""))
                                pdate = format_article_date(item)
                                date_str = f"<div style='font-size:0.8rem; color:#64748b; margin-top:0.2rem; margin-bottom:0.35rem;'>🕒 {pdate}</div>" if pdate else ""
                                summary_str = f"<div style='font-size:0.88rem; line-height:1.45; margin-bottom:0.75rem;'>{clean_summary}</div>" if clean_summary else "<div style='margin-bottom:0.5rem;'></div>"
                                st.markdown(
                                    f"**[{clean_title}]({item['link']})**\n\n{date_str}{summary_str}",
                                    unsafe_allow_html=True
                                )

                                # Bewertungs-Daumen (Like / Dislike) links & Gelesen-Symbol rechts
                                cur_fb = st.session_state.get("feedback_map", {}).get(item_url, item.get("feedback", 0))
                                default_fb = 1 if cur_fb == 1 else (0 if cur_fb == -1 else None)
                                item_url_hash = hashlib.md5(item_url.encode("utf-8")).hexdigest()[:12] if item_url else f"item_{displayed_count}"
                                fb_key = f"fb_{item_url_hash}"
                                read_key = f"read_{item_url_hash}"
                                if fb_key in rendered_element_keys:
                                    dup_cnt = 1
                                    while f"{fb_key}_{dup_cnt}" in rendered_element_keys:
                                        dup_cnt += 1
                                    fb_key = f"{fb_key}_{dup_cnt}"
                                rendered_element_keys.add(fb_key)
                                if read_key in rendered_element_keys:
                                    dup_cnt = 1
                                    while f"{read_key}_{dup_cnt}" in rendered_element_keys:
                                        dup_cnt += 1
                                    read_key = f"{read_key}_{dup_cnt}"
                                rendered_element_keys.add(read_key)

                                col_fb, col_read = st.columns([1, 1], vertical_alignment="center", wrap=False)
                                with col_fb:
                                    st.feedback(
                                    "thumbs",
                                    key=fb_key,
                                    default=default_fb,
                                    on_change=on_article_feedback_change,
                                    args=(item_url, fb_key, clean_title),
                                )
                                with col_read:
                                    st.button(
                                        "",
                                        icon=":material/check:",
                                        key=read_key,
                                        type="tertiary",
                                        help="Artikel als gelesen markieren & archivieren",
                                        on_click=on_article_read_and_archive,
                                        args=(item, category, feed_name),
                                    )

                    if len(f_items) > len(visible_items):
                        remaining_count = len(f_items) - len(visible_items)
                        batch_count = min(DEFAULT_FEED_PAGE_SIZE, remaining_count)
                        c_m1, c_m2, c_m3 = st.columns([1, 2, 1])
                        with c_m2:
                            if st.button(
                                f"▼ Weitere {batch_count} von {remaining_count} Artikeln laden",
                                key=f"btn_more_{feed_slug}",
                                use_container_width=True,
                                help="Lädt weitere Artikel dieser Quelle in die Ansicht",
                            ):
                                st.session_state[feed_limit_key] = current_feed_limit + DEFAULT_FEED_PAGE_SIZE
                                if "persisted_open_feeds" not in st.session_state:
                                    st.session_state["persisted_open_feeds"] = set()
                                st.session_state["persisted_open_feeds"].add(feed_name)
                                st.rerun()

    if "last_read_feed_slug" in st.session_state:
        target_slug = st.session_state.pop("last_read_feed_slug")
        embed_client_script(f"""
        (function() {{
            setTimeout(function() {{
                var el = document.getElementById("anchor-feed-{target_slug}");
                if (el) {{
                    el.scrollIntoView({{ behavior: 'instant', block: 'nearest' }});
                }}
            }}, 30);
        }})();
        """)

    with col_stat_placeholder:
        if displayed_count > 0:
            sort_label = "älteste zuerst" if bool(st.session_state.get("chk_sort_oldest", True)) else "neueste zuerst"
            age_filter_note = f" • Max. Alter: {active_max_age_weeks} Wochen" if active_max_age_weeks > 0 else ""
            st.caption(f"Zeige **{displayed_count}** Artikel in **{categories_rendered}** Kategorien ({sort_label}{age_filter_note})")
        else:
            if selected_feed != "Alle Feeds":
                st.warning(f"Keine Artikel für den Feed '{selected_feed}' gefunden (0 Treffer).")
            elif selected_cat != "Alle Kategorien":
                st.warning(f"Keine Artikel für die Kategorie '{selected_cat}' gefunden (0 Treffer).")
            else:
                st.warning("Keine Artikel gefunden, die den Suchkriterien entsprechen (0 Treffer).")

# ----------------- TAB: KI -----------------
with tab_ki:
    st.markdown("<h3 style='margin-top:0.25rem; margin-bottom:0.4rem;'>✨ KI-Synthese & Briefing</h3>", unsafe_allow_html=True)
    
    current_prompt_directives = working_config.get("settings", {}).get("custom_prompt_directives")
    if not current_prompt_directives:
        current_prompt_directives = DEFAULT_DIRECTIVES

    current_main_prompt = working_config.get("settings", {}).get("custom_main_prompt")
    if not current_main_prompt:
        current_main_prompt = DEFAULT_MAIN_PROMPT_TEMPLATE

    with st.expander("⚙️ KI-Prompt-Konfiguration (Hauptprompt & Direktiven)", expanded=False):
        st.caption("Hier kannst du den vollständigen Haupt-/Systemprompt sowie redaktionelle Richtlinien für Gemini steuern.")
        
        ki_main_prompt = st.text_area(
            "Haupt-Prompt für Gemini (Rolle, Struktur & Format):",
            value=current_main_prompt,
            key="input_ki_main_prompt",
            help="Definiert die Rollen- und Strukturvorgaben für Gemini (Infobox, Top 5 Links). Die Platzhalter {lang_name}, {active_directives} und {context_data} werden automatisch eingesetzt.",
            height=200,
            disabled=not is_admin,
        )
        
        ki_prompt_directives = st.text_area(
            "Redaktionelle Filter & Direktiven (Erweiterte Regeln):",
            value=current_prompt_directives,
            key="input_ki_prompt_directives",
            help="Hier kannst du z. B. vorgeben: 'Filtere reine Werbung und Sonderangebote heraus. Ignoriere Krypto. Fokussiere auf Berliner Lokalthemen.'",
            height=100,
            disabled=not is_admin,
        )
        
        if is_admin:
            col_save_p, col_reset_p = st.columns([1, 1])
            with col_save_p:
                if st.button("💾 Prompts als Standard in sources.yaml speichern", key="btn_save_ki_prompts", use_container_width=True):
                    working_config.setdefault("settings", {})["custom_main_prompt"] = ki_main_prompt.strip()
                    working_config.setdefault("settings", {})["custom_prompt_directives"] = ki_prompt_directives.strip()
                    save_sources(working_config, sync_github=True)
                    st.toast("Haupt-Prompt & Direktiven dauerhaft gespeichert & synchronisiert!", icon="💾")
                    st.rerun()
            with col_reset_p:
                if st.button("🔄 Standard-Hauptprompt laden", key="btn_reset_ki_main_prompt", use_container_width=True):
                    working_config.setdefault("settings", {})["custom_main_prompt"] = DEFAULT_MAIN_PROMPT_TEMPLATE.strip()
                    st.session_state["input_ki_main_prompt"] = DEFAULT_MAIN_PROMPT_TEMPLATE.strip()
                    save_sources(working_config, sync_github=True)
                    st.toast("Standard-Hauptprompt wiederhergestellt & synchronisiert!", icon="🔄")
                    st.rerun()
        else:
            st.caption("🔒 **Lese-Modus:** Das Anpassen und Speichern der Prompts erfordert Admin-Rechte.")

    col_btn, col_info = st.columns([1, 2], vertical_alignment="center")
    with col_btn:
        if is_admin:
            generate_clicked = st.button("🚀 Neues Briefing generieren", type="primary", use_container_width=True)
        else:
            with st.popover("🔒 Neues Briefing (Admin)", use_container_width=True):
                st.markdown("#### 🔑 Admin-Freischaltung")
                st.caption("Das Generieren neuer KI-Briefings verbraucht Gemini API-Kontingente und ist Administratoren vorbehalten:")
                admin_gen_pw = st.text_input("App-Passwort:", type="password", key="gen_unlock_pw", placeholder="••••••••")
                if st.button("🔓 Freischalten & Generieren", type="primary", key="gen_unlock_btn", use_container_width=True):
                    expected_password = get_configured_app_password()
                    if admin_gen_pw == expected_password:
                        set_admin_session_cookie(expected_password)
                        st.session_state["trigger_generate"] = True
                        st.toast("Admin-Berechtigung erteilt!", icon="🛡️")
                        st.rerun()
                    else:
                        st.error("Falsches Passwort.")
            generate_clicked = st.session_state.pop("trigger_generate", False)

    with col_info:
        if is_admin:
            st.caption("Fasst die relevantesten Artikel aus allen Feeds zusammen. ⭐ **Positiv bewertete Favoriten (Likes)** werden bevorzugt analysiert und hervorgehoben.")
        else:
            st.caption("👁️ **Lese-Modus:** Du kannst das bestehende Briefing lesen. Das Anstoßen einer neuen KI-Generierung erfordert Admin-Rechte.")

    if generate_clicked:
        if not is_admin:
            st.warning("Keine Berechtigung zur Generierung. Bitte als Admin anmelden.")
        else:
            total_items = sum(len(items) for items in news_data.values())
            logger.info("🧠 [Streamlit] Starte KI-Briefing-Generierung mit Modell '%s' für %d Artikel...", selected_model, total_items)
            with st.spinner(f"Gemini ({selected_model}) analysiert die Artikel und erstellt das Briefing..."):
                t0_gen = time.time()
                ai_summary = summarize_news_with_gemini(
                    news_data,
                    api_key=user_api_key,
                    model=selected_model,
                    main_prompt_template=ki_main_prompt,
                    custom_directives=ki_prompt_directives,
                )
                dur_gen = time.time() - t0_gen
                logger.info("✨ [Streamlit] KI-Briefing erfolgreich generiert (%d Zeichen in %.2fs).", len(ai_summary), dur_gen)
                st.session_state["cached_summary"] = ai_summary
                st.session_state["summary_timestamp"] = get_local_now().strftime("%d.%m.%Y, %H:%M Uhr")
                save_pool_state(news_data)
                try:
                    from src.rss_generator import export_briefing_rss
                    export_briefing_rss(ai_summary)
                    logger.info("📡 [Streamlit] briefing.xml erfolgreich aktualisiert.")
                except Exception as exc_rss:
                    logger.warning("Briefing-RSS konnte nicht exportiert werden: %s", exc_rss)
                try:
                    from src.storage import get_storage
                    storage_gen = get_storage()
                    briefing_date = get_local_now().strftime("%Y-%m-%d")
                    saved_id = storage_gen.save_briefing(briefing_date, ai_summary, selected_model)
                    cleaned_count = storage_gen.cleanup_archive(max_age_weeks=active_max_age_weeks)
                    logger.info("💾 [Streamlit] Briefing in DB archiviert (ID: %s, Modell: %s), %d alte Artikel bereinigt.", saved_id, selected_model, cleaned_count)
                except Exception as exc_sg:
                    logger.warning("Briefing-Speicherung oder Cleanup in Webapp fehlgeschlagen: %s", exc_sg)

    if "cached_summary" in st.session_state:
        st.markdown(f"*(Erstellt am: {st.session_state.get('summary_timestamp', '')})*")
        st.markdown(st.session_state["cached_summary"])
        
        st.markdown("---")
        # Download-Möglichkeit als Markdown
        st.download_button(
            label="📥 Briefing als Markdown herunterladen",
            data=st.session_state["cached_summary"],
            file_name=f"news_briefing_{get_local_now().strftime('%Y%m%d')}.md",
            mime="text/markdown",
        )
    else:
        if is_admin:
            st.info("Klicke auf den Button **'Neues Briefing generieren'**, um dein persönliches KI-Briefing zu erstellen.")
        else:
            st.info("Aktuell liegt noch kein generiertes Briefing für diese Sitzung vor. Schalte oben den Admin-Modus frei, um ein neues Briefing mit Gemini zu generieren.")

# ----------------- TAB: Feedly -----------------
with tab_feedly:
    st.subheader("📡 RSS Exposure")
    st.caption("Verwandle deinen News Aggregator Bot in deinen persönlichen RSS-Server! Alle Feeds enthalten stets die aggregierten Artikel der letzten 24 Stunden.")

    app_base_url = working_config.get("settings", {}).get("streamlit_app_url") or get_streamlit_app_url()
    app_base_url = (app_base_url or "").rstrip("/")

    # Oberer Info- und Aktionsbalken
    st.caption("🚀 **24/7 High-Speed GitHub CDN** • 0s Ladezeit • Standard RSS 2.0 XML • Letzte 24 Stunden")

    if is_admin:
        col_rss_act1, col_rss_act2, col_rss_act3 = st.columns([1, 1, 1])
        with col_rss_act1:
            rss_feed_view_mode = st.selectbox(
                "Ansicht:",
                options=["Alle Feeds", "Nur Kategorien", "Nur Einzel-Feeds"],
                key="sel_rss_view_mode",
                label_visibility="collapsed"
            )
        with col_rss_act2:
            if st.button("🔄 Neu laden", key="btn_refresh_rss", use_container_width=True, help="Liest die Artikel neu ein und generiert die lokalen XML-Dateien frisch"):
                st.cache_data.clear()
                st.toast("RSS-Feeds wurden frisch generiert!", icon="📡")
                st.rerun()
        with col_rss_act3:
            if st.button("🚀 Zu CDN pushen", key="btn_push_rss_cdn", use_container_width=True, help="Pusht die aktuellen XML-Feeds sofort als Commit zu GitHub & CDN"):
                with st.spinner("Pushe RSS-Feeds zu GitHub & CDN..."):
                    export_all_rss_feeds(news_data, config=working_config, base_url=app_base_url)
                    push_res = sync_sources_to_github(
                        config_dict=working_config,
                        commit_message="chore(rss): update RSS feeds via web dashboard",
                        include_rss_feeds=True
                    )
                    if push_res.get("success"):
                        st.success("RSS-Feeds erfolgreich zu GitHub & CDN synchronisiert!")
                        st.toast("Feeds zu CDN gepusht!", icon="🚀")
                    else:
                        trig_res = trigger_rss_update_workflow()
                        if trig_res.get("success"):
                            st.info("⚡ GitHub Action 'Update RSS Feeds' wurde angestoßen!")
                            st.toast("GitHub Action gestartet!", icon="⚡")
                        else:
                            st.error(f"Fehler: {push_res.get('error')}")
    else:
        col_rss_act1, col_rss_act2 = st.columns([1, 1])
        with col_rss_act1:
            rss_feed_view_mode = st.selectbox(
                "Ansicht:",
                options=["Alle Feeds", "Nur Kategorien", "Nur Einzel-Feeds"],
                key="sel_rss_view_mode",
                label_visibility="collapsed"
            )
        with col_rss_act2:
            if st.button("🔄 Neu laden", key="btn_refresh_rss", use_container_width=True, help="Liest die Artikel neu ein und generiert die lokalen XML-Dateien frisch"):
                st.cache_data.clear()
                st.toast("RSS-Feeds wurden frisch generiert!", icon="📡")
                st.rerun()

    # Feeds exportieren und Registry laden
    rss_registry = export_all_rss_feeds(news_data, config=working_config, base_url=app_base_url)

    # 1. Gesamt-Feed (Alle Nachrichten) & KI-Briefing Feed
    if rss_feed_view_mode in ["Alle Feeds", "Nur Kategorien"]:
        all_info = rss_registry.get("all", {})
        with st.expander(f"🌟 **Gesamt-Feed (Alle Nachrichten)** ({all_info.get('item_count', 0)} Artikel)", expanded=False):
            st.write("Enthält alle aggregierten Artikel aus sämtlichen Kategorien und Quellen chronologisch geordnet.")

            all_url = all_info.get("url") or all_info.get("cdn_url", "")
            feed_proto_url = all_url.replace("https://", "feed://").replace("http://", "feed://")

            st.code(all_url, language="text")

            col_u1, col_u2, col_u3 = st.columns(3)
            with col_u1:
                st.link_button("↗️ Im Browser öffnen", all_url, use_container_width=True)
            with col_u2:
                st.download_button(
                    "📥 XML herunterladen",
                    data=all_info.get("xml_preview", ""),
                    file_name="news_bot_all.xml",
                    mime="application/rss+xml",
                    use_container_width=True,
                    key="dl_btn_all_rss"
                )
            with col_u3:
                st.link_button("➕ 1-Click Abo (feed://)", feed_proto_url, use_container_width=True, help="Öffnet den Feed direkt im Standard-RSS-Reader deines Betriebssystems (z. B. Apple News, NetNewsWire)")

            with st.expander("👁️ RSS-XML-Vorschau anzeigen", expanded=False):
                st.code(all_info.get("xml_preview", ""), language="xml")

        briefing_info = rss_registry.get("briefing")
        if briefing_info:
            with st.expander("✨ **KI-Briefing Feed**", expanded=False):
                st.write("Abonniere das tägliche, von Gemini KI synthetisierte und kuratierte Briefing direkt in deinem RSS-Reader.")

                br_url = briefing_info.get("url") or briefing_info.get("cdn_url", "")
                br_proto_url = br_url.replace("https://", "feed://").replace("http://", "feed://")

                st.code(br_url, language="text")

                col_b1, col_b2, col_b3 = st.columns(3)
                with col_b1:
                    st.link_button("↗️ Im Browser öffnen", br_url, use_container_width=True)
                with col_b2:
                    st.download_button(
                        "📥 XML herunterladen",
                        data=briefing_info.get("xml_preview", ""),
                        file_name="news_bot_briefing.xml",
                        mime="application/rss+xml",
                        use_container_width=True,
                        key="dl_btn_briefing_rss"
                    )
                with col_b3:
                    st.link_button("➕ 1-Click Abo (feed://)", br_proto_url, use_container_width=True, help="Öffnet das KI-Briefing direkt im Standard-RSS-Reader")

                with st.expander("👁️ RSS-XML-Vorschau anzeigen", expanded=False):
                    st.code(briefing_info.get("xml_preview", ""), language="xml")

    # 2. Kategorie-Feeds
    if rss_feed_view_mode in ["Alle Feeds", "Nur Kategorien"]:
        categories_rss = rss_registry.get("categories", [])
        with st.expander(f"📁 **Feeds nach Themen-Kategorien** ({len(categories_rss)})", expanded=False):
            st.caption("Abonniere gezielt nur die Themen, die dich interessieren:")

            cat_cols = st.columns(2)
            for idx, cat_item in enumerate(categories_rss):
                with cat_cols[idx % 2]:
                    with st.container(border=True):
                        col_ch1, col_ch2 = st.columns([3, 1], vertical_alignment="center")
                        with col_ch1:
                            st.markdown(f"#### 📁 {cat_item['name']}")
                        with col_ch2:
                            st.caption(f"**{cat_item['item_count']}** Artikel")

                        st.caption(f"Enthält Beiträge aus {cat_item['feed_count']} konfigurierten Feeds.")
                        cat_url = cat_item.get("url") or cat_item.get("cdn_url", "")
                        cat_feed_proto = cat_url.replace("https://", "feed://").replace("http://", "feed://")

                        st.code(cat_url, language="text")

                        col_cbtn1, col_cbtn2, col_cbtn3 = st.columns(3)
                        with col_cbtn1:
                            st.link_button("↗️ Öffnen", cat_url, use_container_width=True)
                        with col_cbtn2:
                            st.download_button(
                                "📥 XML",
                                data=cat_item['xml_preview'],
                                file_name=f"{cat_item['slug']}.xml",
                                mime="application/rss+xml",
                                use_container_width=True,
                                key=f"dl_cat_{cat_item['slug']}"
                            )
                        with col_cbtn3:
                            st.link_button("➕ 1-Click", cat_feed_proto, use_container_width=True, help="1-Click Abo via feed:// Protokoll")

                        with st.expander(f"👁️ XML ({cat_item['name']}) ansehen", expanded=False):
                            st.code(cat_item['xml_preview'], language="xml")

    # 3. Einzel-Feeds nach Quellen
    if rss_feed_view_mode in ["Alle Feeds", "Nur Einzel-Feeds"]:
        feeds_rss = rss_registry.get("feeds", [])
        with st.expander(f"📡 **Feeds einzelner Quellen** ({len(feeds_rss)})", expanded=False):
            st.caption("Aufbereitete Feeds für jede spezifische Nachrichtenquelle:")

            all_cat_options = ["Alle Kategorien"] + sorted(list({f['category'] for f in feeds_rss}))
            selected_feed_cat = st.selectbox("Quellen filtern nach Kategorie:", all_cat_options, key="sel_filter_source_cat")

            filtered_feeds = [f for f in feeds_rss if selected_feed_cat == "Alle Kategorien" or f['category'] == selected_feed_cat]

            feed_grid = st.columns(2)
            for idx, f_item in enumerate(filtered_feeds):
                with feed_grid[idx % 2]:
                    with st.container(border=True):
                        col_fh1, col_fh2 = st.columns([3, 1], vertical_alignment="center")
                        with col_fh1:
                            st.markdown(f"**📡 {f_item['name']}**")
                        with col_fh2:
                            st.caption(f"📁 {f_item['category']}")

                        st.caption(f"Artikel im Pool: **{f_item['item_count']}** • [Original-Feed ansehen]({f_item['original_url']})")
                        f_url = f_item.get("url") or f_item.get("cdn_url", "")
                        f_proto = f_url.replace("https://", "feed://").replace("http://", "feed://")

                        st.code(f_url, language="text")

                        col_fbtn1, col_fbtn2, col_fbtn3 = st.columns(3)
                        with col_fbtn1:
                            st.link_button("↗️ Öffnen", f_url, use_container_width=True)
                        with col_fbtn2:
                            st.download_button(
                                "📥 XML",
                                data=f_item['xml_preview'],
                                file_name=f"{f_item['slug']}.xml",
                                mime="application/rss+xml",
                                use_container_width=True,
                                key=f"dl_single_feed_{f_item['slug']}"
                            )
                        with col_fbtn3:
                            st.link_button("➕ 1-Click", f_proto, use_container_width=True, help="1-Click Abo via feed:// Protokoll")

                        with st.expander(f"👁️ XML ({f_item['name']}) ansehen", expanded=False):
                            st.code(f_item['xml_preview'], language="xml")

    # 4. Anleitung für RSS-Reader
    with st.expander("ℹ️ **Anleitung: Wie binde ich diese Feeds in Feedly / RSS-Reader ein?**", expanded=False):
        all_example_url = rss_registry.get("all", {}).get("url") or "https://cdn.jsdelivr.net/gh/hschenke/news-aggregator-bot@main/static/rss/all.xml"
        st.markdown(f"""
        ### So abonnierst du deine persönlichen Feeds:
        1. **URL kopieren**: Klicke oben im Kasten des gewünschten Feeds auf das Kopier-Icon des Code-Blocks (z. B. `{all_example_url}`).
        2. **RSS-Reader öffnen**: Starte deinen bevorzugten News-Reader (z. B. *Feedly*, *NetNewsWire*, *Apple News*, *Inoreader*, *Thunderbird*, *Outlook* etc.).
        3. **Feed hinzufügen**:
           - **Feedly**: In der linken Seitenleiste auf `+` (Follow Sources) klicken > URL einfügen > `Follow`.
           - **NetNewsWire / Reeder**: Menü `Feed` > `Add Web Feed...` > URL einfügen > `Add`.
           - **Inoreader**: Suchfeld oben > URL einfügen > `Abonnieren`.
           - **Thunderbird**: Ordner "Blogs & News-Feeds" auswählen > `Feed-Abonnements verwalten` > `Hinzufügen` > URL einfügen.
        4. **Tipp für macOS & iOS**: Wenn dein Reader das URL-Schema `feed://` unterstützt, kannst du einfach auf **'➕ 1-Click'** klicken, um den Feed direkt mit einem Klick zu öffnen und zu abonnieren!

        > **Hinweis:** Alle Feeds werden über ein globales High-Speed CDN (jsDelivr / GitHub) direkt als standardkonformes RSS 2.0 XML (`application/xml`) ausgeliefert. Sie sind 24/7 ohne Wartezeit oder App-Standby erreichbar.
        """)


# ----------------- TAB: Quellen & Feeds verwalten -----------------
with tab_manage:

    is_admin = st.session_state.get("auth_role") == ROLE_ADMIN or not get_configured_app_password()
    if not is_admin:
        st.subheader("⚙️ Quellen & Feeds verwalten")
        st.warning(
            "🔒 **Schreibschutz aktiv: Du bist im Lese-Modus angemeldet.**\n\n"
            "Über deinen E-Mail-Link hast du uneingeschränkten Lesezugriff auf das Briefing und alle Artikel. "
            "Um RSS-Feeds hinzuzufügen, zu bearbeiten, zu löschen oder Einstellungen zu ändern, "
            "schalte bitte den **Admin-Modus** mit deinem App-Passwort frei."
        )

        with st.container(border=True):
            st.markdown("#### 🔑 Admin-Modus freischalten")
            st.caption("Gib dein `APP_PASSWORD` ein, um Feeds & Einstellungen zu bearbeiten:")
            col_unl1, col_unl2 = st.columns([3, 1], vertical_alignment="bottom")
            with col_unl1:
                admin_pw_input = st.text_input("App-Passwort:", type="password", key="tab3_admin_pw_input", placeholder="••••••••")
            with col_unl2:
                if st.button("🔓 Admin-Modus aktivieren", type="primary", key="tab3_btn_unlock", use_container_width=True):
                    expected_password = get_configured_app_password()
                    if admin_pw_input == expected_password:
                        set_admin_session_cookie(expected_password)
                        st.toast("Admin-Berechtigung erteilt!", icon="🛡️")
                        st.rerun()
                    else:
                        st.error("Falsches Passwort.")

        st.markdown("---")
        with st.expander("👁️ Aktuell konfigurierte Kategorien & Feeds ansehen (Schreibgeschützt)", expanded=False):
            categories_list = sorted(saved_sources_config.get("categories", []), key=lambda c: c.get("name", "").strip().lower())
            if not categories_list:
                st.info("Keine Kategorien konfiguriert.")
            for cat in categories_list:
                feeds = sorted(cat.get("feeds", []), key=lambda f: f.get("name", "").strip().lower())
                st.markdown(f"**📁 {cat.get('name')}** ({len(feeds)} Feeds)")
                for f in feeds:
                    st.caption(f"• **{f.get('name')}** (`{f.get('url')}`)")

        st.stop()

    st.subheader("⚙️ Quellen & Feeds verwalten")
    st.caption("Verwalte deine RSS-Feeds und Einstellungen. Änderungen werden gesammelt und erst durch Klick auf **'💾 Alle Änderungen speichern'** dauerhaft gesichert.")

    # Feedback nach Speichern anzeigen falls vorhanden
    feedback = st.session_state.pop("save_feedback", None)
    if feedback:
        level, msg = feedback
        if level == "success":
            st.success(msg)
        elif level == "warning":
            st.warning(msg)

    # Oberer Status- und Speicher-Bereich
    if has_unsaved_changes:
        with st.container(border=True):
            col_stat_txt, col_stat_save, col_stat_disc = st.columns([3, 1, 1], vertical_alignment="center")
            with col_stat_txt:
                st.markdown("⚠️ **Ungespeicherte Änderungen vorhanden!**")
                st.caption("Du hast Anpassungen vorgenommen, die noch nicht in `sources.yaml` geschrieben wurden.")
            with col_stat_save:
                if st.button("💾 Alle Änderungen speichern", type="primary", use_container_width=True, key="top_save_all_btn"):
                    perform_save_all()
            with col_stat_disc:
                if st.button("↩️ Verwerfen", use_container_width=True, key="top_discard_all_btn"):
                    perform_discard_all()
    else:
        with st.container(border=True):
            col_stat_txt, col_stat_save = st.columns([4, 1], vertical_alignment="center")
            with col_stat_txt:
                st.markdown("✅ **Alle Feeds & Einstellungen sind auf dem aktuellen Stand (gespeichert).**")
            with col_stat_save:
                if st.button("💾 Jetzt sichern", use_container_width=True, key="top_save_sync_btn", help="Aktuellen Stand erneut schreiben & zu GitHub pushen"):
                    perform_save_all()

    sources_path = get_sources_path()

    # --- GitHub-Sync (Anleitung nur anzeigen, wenn noch nicht konfiguriert) ---
    if not gh_cfg.get("token"):
        with st.expander("ℹ️ **Automatischer GitHub-Sync (Empfohlen für Streamlit Cloud)**", expanded=False):
            st.markdown(f"""
            Streamlit Community Cloud Container sind flüchtig (*ephemeral*). Bei einem Neustart der Cloud-App werden lokal gespeicherte Dateien auf den Stand des Git-Repositories zurückgesetzt.
            
            **So aktivierst du den automatischen Git-Push für das Dashboard:**
            1. Erstelle ein GitHub-Token (Personal Access Token) unter [github.com/settings/tokens](https://github.com/settings/tokens) mit Schreibrechten (`repo` bzw. `contents:write`).
            2. Trage in deinen **Streamlit Cloud App-Settings > Secrets** (oder lokal in `.env`) folgendes ein:
            ```toml
            GITHUB_TOKEN = "ghp_deinTokenHier"
            GITHUB_REPO = "{gh_cfg['repo']}"
            ```
            3. **Fertig!** Danach spiegelt das Web-Dashboard jede Änderung beim Speichern per Git-Commit in dein GitHub-Repository zurück – und GitHub Actions greift morgens automatisch auf die neuesten Feeds zu!
            """)

    # --- Sektion 1: Kategorien verwalten (Neu anlegen & Umbenennen) ---
    with st.expander("📁 Kategorien verwalten (Neu anlegen & Umbenennen)", expanded=False):
        subtab_cat1, subtab_cat2 = st.tabs(["➕ Neue Kategorie anlegen", "✏️ Kategorie umbenennen"])

        with subtab_cat1:
            st.write("Erstelle eine neue Themen-Kategorie für deine Feeds (z. B. *Wissenschaft*, *Gaming*, *Finanzen*):")
            col_cat_in, col_cat_btn = st.columns([3, 1], vertical_alignment="bottom")
            with col_cat_in:
                new_category_input = st.text_input(
                    "Name der neuen Kategorie:",
                    placeholder="z. B. Wissenschaft & Raumfahrt",
                    key="input_direct_new_category"
                )
            with col_cat_btn:
                if st.button("➕ Kategorie anlegen", type="primary", use_container_width=True, key="btn_direct_create_cat"):
                    cat_clean = new_category_input.strip()
                    if not cat_clean:
                        st.error("Bitte gib einen Namen für die Kategorie ein.")
                    else:
                        success = add_category(cat_clean, config=working_config, save_to_disk=False)
                        if success:
                            st.session_state["has_unsaved_changes"] = True
                            st.session_state["pending_nav_tab"] = "manage"
                            st.query_params["tab"] = "manage"
                            st.session_state["last_edited_category"] = cat_clean
                            st.toast(f"Kategorie '{cat_clean}' angelegt (noch nicht gespeichert).", icon="📁")
                            st.rerun()
                        else:
                            st.warning(f"Kategorie '{cat_clean}' existiert bereits.")

        with subtab_cat2:
            existing_cat_names = [c.get("name", "").strip() for c in working_config.get("categories", []) if c.get("name")]
            if not existing_cat_names:
                st.info("Noch keine Kategorien vorhanden.")
            else:
                st.write("Wähle eine Kategorie aus, um ihren Namen zu ändern:")
                col_ren_select, col_ren_new, col_ren_btn = st.columns([2, 2, 1], vertical_alignment="bottom")
                with col_ren_select:
                    cat_to_rename = st.selectbox("Kategorie auswählen:", options=existing_cat_names, key="select_cat_to_rename")
                with col_ren_new:
                    new_cat_name_input = st.text_input("Neuer Name:", value=cat_to_rename, key=f"input_ren_cat_{cat_to_rename}")
                with col_ren_btn:
                    if st.button("✏️ Umbenennen", type="primary", use_container_width=True, key="btn_rename_cat"):
                        if not new_cat_name_input.strip():
                            st.error("Der neue Name darf nicht leer sein.")
                        elif new_cat_name_input.strip() == cat_to_rename:
                            st.info("Der Name wurde nicht verändert.")
                        else:
                            try:
                                rename_category(cat_to_rename, new_cat_name_input.strip(), config=working_config, save_to_disk=False)
                                st.session_state["has_unsaved_changes"] = True
                                st.session_state["pending_nav_tab"] = "manage"
                                st.query_params["tab"] = "manage"
                                st.session_state["last_edited_category"] = new_cat_name_input.strip()
                                st.toast(f"Kategorie in '{new_cat_name_input.strip()}' umbenannt (noch nicht gespeichert).", icon="✏️")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Fehler beim Umbenennen: {e}")

    def render_feed_test_result(t_res: Dict[str, Any]) -> None:
        """Rendert eine übersichtliche, einklappbare Infobox mit allen Stream-Testergebnissen."""
        if not t_res:
            return

        success = t_res.get("success", False)
        item_count = t_res.get("item_count", 0)
        title = t_res.get("title", "Unbekannter Titel")
        stream_type = t_res.get("stream_type", "Unbekannt")
        status_code = t_res.get("status_code", "-")
        latency_ms = t_res.get("latency_ms", 0)
        content_type = t_res.get("content_type", "")
        content_len = t_res.get("content_length", 0)
        err = t_res.get("error")
        warn = t_res.get("warning")
        is_redir = t_res.get("is_redirected", False)
        final_url = t_res.get("final_url", "")
        sample_items = t_res.get("sample_items", [])
        disc = t_res.get("autodiscovered_feeds", [])

        icon = "✅" if (success and item_count > 0) else ("⚠️" if success else "❌")
        box_header = (
            f"{icon} Stream-Test Ergebnis: {title} ({stream_type} • {item_count} Artikel)"
            if (success and item_count > 0)
            else f"{icon} Stream-Test: {title} ({'0 Artikel' if success else err or 'Fehlgeschlagen'})"
        )

        with st.expander(box_header, expanded=True):
            if success and item_count > 0:
                st.success(f"**Stream erfolgreich verifiziert:** **{title}** ({stream_type}) — **{item_count} Einträge** gefunden!")
            elif success and item_count == 0:
                st.warning(f"**Stream erreichbar, aber leer:** **{title}** ({stream_type}) lieferte aktuell **0 Artikel**.")
            else:
                st.error(f"**Stream-Test fehlgeschlagen:** {err or 'Unbekannter Fehler'}")

            # Übersichtliche 2-Spalten-Struktur statt gequetschter 4 Spalten
            col_info1, col_info2 = st.columns(2)
            with col_info1:
                st.markdown(f"• **Stream-Format:** `{stream_type}`")
                st.markdown(f"• **Gefundene Artikel:** **{item_count}** Einträge")
                if t_res.get("site_url"):
                    st.markdown(f"• **Website der Quelle:** [{t_res['site_url']}]({t_res['site_url']})")
                elif final_url:
                    st.markdown(f"• **Ziel-URL:** `{final_url}`")
                if t_res.get("language"):
                    st.markdown(f"• **Sprache:** `{t_res['language']}`")
            with col_info2:
                status_badge = f"`HTTP {status_code}`" if status_code else "`-`"
                st.markdown(f"• **Server-Status:** {status_badge} ({latency_ms} ms)")
                ct_clean = content_type.split(";")[0].strip() if content_type else "unbekannt"
                size_str = f" • {content_len / 1024:.1f} KB" if content_len else ""
                st.markdown(f"• **Content-Type:** `{ct_clean}`{size_str}")
                if t_res.get("last_updated"):
                    st.markdown(f"• **Stand:** `{t_res['last_updated']}`")

            if t_res.get("description"):
                st.info(f"**Beschreibung:** {t_res['description']}")

            if warn:
                st.warning(f"**Hinweis:** {warn}")
            if is_redir:
                st.info(f"**URL-Weiterleitung:** Die Ziel-URL leitet weiter auf `{final_url}`.")

            # Artikel-Vorschau direkt in der Infobox
            if sample_items:
                st.markdown("---")
                st.markdown(f"**📰 Vorschau der neuesten Einträge ({min(len(sample_items), 3)} von {item_count}):**")
                for idx, item in enumerate(sample_items, 1):
                    i_title = item.get("title", "Ohne Titel")
                    i_link = item.get("link", "")
                    i_pub = item.get("published", "")
                    i_desc = item.get("summary", "")

                    title_md = f"**[{i_title}]({i_link})**" if i_link else f"**{i_title}**"
                    pub_badge = f" • 🕒 `{i_pub}`" if i_pub else ""
                    st.markdown(f"{idx}. {title_md}{pub_badge}")
                    if i_desc:
                        st.caption(i_desc)

            if disc:
                st.markdown("---")
                st.info("**Auf dieser Webseite gefundene alternative RSS/Atom-Feeds:**")
                for d in disc:
                    st.markdown(f"- **{d['title']}**: `{d['url']}`")

    # --- Sektion 2: RSS-Feeds verwalten (Neu aufnehmen & Bearbeiten) ---
    with st.expander("📡 RSS-Feeds verwalten (Neu aufnehmen & Bearbeiten)", expanded=False):
        subtab_feed1, subtab_feed2 = st.tabs(["➕ Neuen Feed hinzufügen", "✏️ Bestehenden Feed bearbeiten"])

        # Tab 1: Neuer Feed
        with subtab_feed1:
            existing_categories = sorted([c.get("name", "").strip() for c in working_config.get("categories", []) if c.get("name")], key=lambda x: x.strip().lower())
            cat_select_options = existing_categories + ["➕ [Neue Kategorie erstellen...]"]

            col_new1, col_new2 = st.columns(2)
            with col_new1:
                selected_cat_choice = st.selectbox(
                    "Kategorie zuordnen:",
                    options=cat_select_options,
                    help="Wähle eine bestehende Kategorie oder erstelle eine neue.",
                    key="select_cat_add_feed"
                )
                if selected_cat_choice == "➕ [Neue Kategorie erstellen...]":
                    custom_cat_name = st.text_input("Name der neuen Kategorie:", placeholder="z. B. Wissenschaft & Raumfahrt", key="input_custom_cat_add")
                    target_cat_name = custom_cat_name.strip()
                else:
                    target_cat_name = selected_cat_choice.strip()

            with col_new2:
                new_feed_name = st.text_input("Name des Feeds:", placeholder="z. B. The Verge Tech", key="input_new_feed_name")

            new_feed_url = st.text_input("RSS- oder Atom-Feed URL:", placeholder="https://www.theverge.com/rss/index.xml", key="input_new_feed_url")

            col_kw1, col_kw2 = st.columns(2)
            with col_kw1:
                new_feed_include = st.text_input(
                    "🟢 Nur mit Keywords aufnehmen (Einschließen / Whitelist):",
                    placeholder="z. B. Mahlsdorf, Kaulsdorf",
                    key="input_new_feed_include",
                    help="Wenn ausgefüllt, werden NUR Artikel übernommen, die mindestens eines dieser Wörter in Titel oder Text enthalten."
                )
            with col_kw2:
                new_feed_exclude = st.text_input(
                    "🔴 Mit Keywords ausschließen (Ausschließen / Blacklist):",
                    placeholder="z. B. Krypto, Sport, Werbung",
                    key="input_new_feed_exclude",
                    help="Artikel, die mindestens eines dieser Wörter enthalten, werden verworfen."
                )

            col_act1, col_act2 = st.columns([1, 2], vertical_alignment="center")
            with col_act1:
                test_clicked = st.button("🔍 Feed-URL testen", use_container_width=True, key="btn_test_new_feed")
            with col_act2:
                add_clicked = st.button("➕ Feed zur Liste hinzufügen", type="primary", use_container_width=True, key="btn_add_new_feed")

            if test_clicked:
                if not new_feed_url.strip():
                    st.warning("Bitte gib zuerst eine Feed-URL ein.")
                else:
                    with st.spinner("Prüfe Feed-URL und Stream..."):
                        test_res = test_feed_connection(new_feed_url)
                        render_feed_test_result(test_res)

            if add_clicked:
                if not target_cat_name:
                    st.error("Bitte gib einen Kategorienamen an.")
                elif not new_feed_name.strip():
                    st.error("Bitte gib einen Namen für den Feed an.")
                elif not new_feed_url.strip() or not (new_feed_url.strip().startswith("http://") or new_feed_url.strip().startswith("https://")):
                    st.error("Bitte gib eine gültige URL an (beginnend mit http:// oder https://).")
                else:
                    try:
                        add_feed(
                            category_name=target_cat_name,
                            feed_name=new_feed_name,
                            feed_url=new_feed_url,
                            include_keywords=new_feed_include.strip(),
                            exclude_keywords=new_feed_exclude.strip(),
                            config=working_config,
                            save_to_disk=False,
                        )
                        st.session_state["has_unsaved_changes"] = True
                        st.session_state["pending_nav_tab"] = "manage"
                        st.query_params["tab"] = "manage"
                        st.session_state["last_edited_category"] = target_cat_name
                        st.toast(f"Feed '{new_feed_name}' zu '{target_cat_name}' hinzugefügt (noch nicht gespeichert).", icon="📡")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fehler beim Hinzufügen des Feeds: {e}")

        # Tab 2: Bestehenden Feed bearbeiten (Name, URL, Kategorie)
        with subtab_feed2:
            all_feed_options = []
            feed_dict = {}
            for cat in sorted(working_config.get("categories", []), key=lambda c: c.get("name", "").strip().lower()):
                cname = cat.get("name", "Allgemein")
                for feed in sorted(cat.get("feeds", []), key=lambda f: f.get("name", "").strip().lower()):
                    fname = feed.get("name", "Unbenannt")
                    furl = feed.get("url", "")
                    label = f"[{cname}] {fname} ({furl})"
                    all_feed_options.append(label)
                    feed_dict[label] = (cname, feed)

            if not all_feed_options:
                st.info("Noch keine Feeds zum Bearbeiten vorhanden.")
            else:
                selected_edit_label = st.selectbox(
                    "Feed zum Bearbeiten auswählen:",
                    options=all_feed_options,
                    key="top_select_edit_feed"
                )
                curr_cname, curr_f = feed_dict[selected_edit_label]
                all_cats = sorted([c.get("name", "").strip() for c in working_config.get("categories", []) if c.get("name")], key=lambda x: x.strip().lower())
                top_cat_options = all_cats + ["➕ [Neue Kategorie erstellen...]"]

                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    edit_fname = st.text_input(
                        "Feed-Name ändern:",
                        value=curr_f.get("name", ""),
                        key=f"top_edit_name_{curr_f.get('url')}"
                    )
                with col_e2:
                    cat_index = all_cats.index(curr_cname) if curr_cname in all_cats else 0
                    edit_fcat = st.selectbox(
                        "Kategorie ändern / verschieben:",
                        options=top_cat_options,
                        index=cat_index,
                        key=f"top_edit_cat_{curr_f.get('url')}",
                        help="Wähle eine bestehende Kategorie oder erstelle eine neue, um diesen Feed dorthin zu verschieben."
                    )

                if edit_fcat == "➕ [Neue Kategorie erstellen...]":
                    top_custom_cat = st.text_input(
                        "Name der neuen Ziel-Kategorie:",
                        placeholder="z. B. Wissenschaft & Raumfahrt",
                        key=f"top_custom_cat_{curr_f.get('url')}"
                    )
                    target_top_cat = top_custom_cat.strip()
                else:
                    target_top_cat = edit_fcat.strip()

                edit_furl = st.text_input(
                    "Feed-URL ändern:",
                    value=curr_f.get("url", ""),
                    key=f"top_edit_url_{curr_f.get('url')}"
                )

                curr_inc = curr_f.get("include_keywords", [])
                curr_inc_str = ", ".join(curr_inc) if isinstance(curr_inc, list) else str(curr_inc or "")
                curr_exc = curr_f.get("exclude_keywords", [])
                curr_exc_str = ", ".join(curr_exc) if isinstance(curr_exc, list) else str(curr_exc or "")

                col_ek1, col_ek2 = st.columns(2)
                with col_ek1:
                    edit_finclude = st.text_input(
                        "🟢 Nur mit Keywords aufnehmen (Einschließen / Whitelist):",
                        value=curr_inc_str,
                        placeholder="z. B. Mahlsdorf, Kaulsdorf",
                        key=f"top_edit_inc_{curr_f.get('url')}",
                        help="Wenn ausgefüllt, werden nur Artikel übernommen, die mindestens eines dieser Wörter enthalten."
                    )
                with col_ek2:
                    edit_fexclude = st.text_input(
                        "🔴 Mit Keywords ausschließen (Ausschließen / Blacklist):",
                        value=curr_exc_str,
                        placeholder="z. B. Sport, Krypto",
                        key=f"top_edit_exc_{curr_f.get('url')}",
                        help="Artikel mit diesen Wörtern werden ignoriert."
                    )

                col_ebtn1, col_ebtn2, col_ebtn3 = st.columns([1, 2, 1], vertical_alignment="center")
                with col_ebtn1:
                    if st.button("🔍 Feed testen", use_container_width=True, key=f"top_test_{curr_f.get('url')}"):
                        with st.spinner("Prüfe Feed-URL und Stream..."):
                            t_res = test_feed_connection(edit_furl.strip())
                            render_feed_test_result(t_res)
                with col_ebtn2:
                    if st.button("✔️ Im Entwurf vormerken", type="primary", use_container_width=True, key=f"top_save_{curr_f.get('url')}"):
                        if not edit_fname.strip():
                            st.error("Der Feed-Name darf nicht leer sein.")
                        elif not edit_furl.strip() or not (edit_furl.strip().startswith("http://") or edit_furl.strip().startswith("https://")):
                            st.error("Bitte gib eine gültige URL an.")
                        elif not target_top_cat:
                            st.error("Bitte gib einen Namen für die Ziel-Kategorie an.")
                        else:
                            try:
                                update_feed(
                                    category_name=curr_cname,
                                    old_url=curr_f.get("url"),
                                    new_name=edit_fname.strip(),
                                    new_url=edit_furl.strip(),
                                    new_category=target_top_cat,
                                    include_keywords=edit_finclude.strip(),
                                    exclude_keywords=edit_fexclude.strip(),
                                    config=working_config,
                                    save_to_disk=False,
                                )
                                st.session_state["has_unsaved_changes"] = True
                                st.session_state["pending_nav_tab"] = "manage"
                                st.query_params["tab"] = "manage"
                                st.session_state["last_edited_category"] = target_top_cat
                                if target_top_cat.lower() != curr_cname.lower():
                                    st.toast(f"Feed '{edit_fname}' in Kategorie '{target_top_cat}' verschoben (noch nicht gespeichert).", icon="📦")
                                else:
                                    st.toast(f"Feed '{edit_fname}' aktualisiert (noch nicht gespeichert).", icon="✏️")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Fehler beim Übernehmen: {e}")
                with col_ebtn3:
                    with st.popover("🗑️ Löschen", use_container_width=True):
                        st.markdown(f"Feed **'{curr_f.get('name')}'** wirklich entfernen?")
                        if st.button("Bestätigen", key=f"top_del_{curr_f.get('url')}", type="primary", use_container_width=True):
                            delete_feed(curr_cname, curr_f.get("url"), config=working_config, save_to_disk=False)
                            st.session_state["has_unsaved_changes"] = True
                            st.session_state["pending_nav_tab"] = "manage"
                            st.query_params["tab"] = "manage"
                            st.session_state["last_edited_category"] = curr_cname
                            st.toast(f"Feed '{curr_f.get('name')}' entfernt (noch nicht gespeichert).", icon="🗑️")
                            st.rerun()

    st.markdown("---")

    # --- Sektion 3: Aktive Feeds & Quellen bearbeiten / löschen ---
    st.markdown("### 📋 Aktive Feeds nach Kategorien")
    st.caption("Hier kannst du Feeds verwalten, löschen oder deren Details bearbeiten. Änderungen werden gesammelt.")

    categories = sorted(working_config.get("categories", []), key=lambda c: c.get("name", "").strip().lower())
    if not categories:
        st.info("Es sind aktuell keine Kategorien hinterlegt.")

    all_category_names = sorted(
        list({c.get("name", "").strip() for c in working_config.get("categories", []) if c.get("name")}),
        key=lambda x: x.lower()
    )

    for cat_idx, cat in enumerate(categories):
        cat_name = cat.get("name", "Allgemein")
        feeds = sorted(cat.get("feeds", []), key=lambda f: f.get("name", "").strip().lower())
        is_expanded = (st.session_state.get("last_edited_category") == cat_name)

        with st.expander(f"📁 {cat_name} ({len(feeds)} Feeds)", expanded=is_expanded):
            # Kategorie Header Actions
            col_cat_info, col_cat_del = st.columns([5, 1], vertical_alignment="center")
            with col_cat_info:
                st.caption(f"Kategorie: **{cat_name}** • {len(feeds)} konfigurierte Feeds")
            with col_cat_del:
                with st.popover("🗑️ Kategorie löschen", use_container_width=True):
                    st.markdown(f"Kategorie **'{cat_name}'** samt aller Feeds wirklich löschen?")
                    if st.button("Kategorie löschen", key=f"del_cat_{cat_idx}", type="primary", use_container_width=True):
                        delete_category(cat_name, config=working_config, save_to_disk=False)
                        st.session_state["has_unsaved_changes"] = True
                        st.session_state["pending_nav_tab"] = "manage"
                        st.query_params["tab"] = "manage"
                        st.session_state.pop("last_edited_category", None)
                        st.toast(f"Kategorie '{cat_name}' entfernt (noch nicht gespeichert).", icon="🗑️")
                        st.rerun()

            if not feeds:
                st.info(f"In der Kategorie '{cat_name}' sind noch keine Feeds hinterlegt. Du kannst oben einen neuen Feed hinzufügen oder diese Kategorie löschen.")
            else:
                for feed_idx, feed in enumerate(feeds):
                    f_name = feed.get("name", "Unbenannt")
                    f_url = feed.get("url", "")
                    key_hash = hashlib.md5(f_url.encode("utf-8")).hexdigest()[:8]

                    with st.container(border=True):
                        col_top1, col_top2 = st.columns([5, 1], vertical_alignment="center")
                        with col_top1:
                            st.markdown(f"**{f_name}**")
                            f_inc = feed.get("include_keywords", [])
                            f_exc = feed.get("exclude_keywords", [])
                            badges = []
                            if f_inc:
                                badges.append(f"🟢 Nur: `{', '.join(f_inc)}`")
                            if f_exc:
                                badges.append(f"🔴 Ohne: `{', '.join(f_exc)}`")
                            kw_badge = f" • {' | '.join(badges)}" if badges else ""
                            st.caption(f"🔗 [{f_url}]({f_url}){kw_badge}")
                        with col_top2:
                            with st.popover("🗑️ Löschen", use_container_width=True):
                                st.markdown(f"Feed **'{f_name}'** wirklich entfernen?")
                                if st.button("Bestätigen", key=f"feed_del_conf_{cat_idx}_{feed_idx}", type="primary", use_container_width=True):
                                    delete_feed(cat_name, f_url, config=working_config, save_to_disk=False)
                                    st.session_state["has_unsaved_changes"] = True
                                    st.session_state["pending_nav_tab"] = "manage"
                                    st.query_params["tab"] = "manage"
                                    st.session_state["last_edited_category"] = cat_name
                                    st.toast(f"Feed '{f_name}' entfernt (noch nicht gespeichert).", icon="🗑️")
                                    st.rerun()

                        with st.expander("🛠️ Details & URL bearbeiten / Feed testen", expanded=False):
                            col_ed1, col_ed2 = st.columns(2)
                            with col_ed1:
                                edit_name_val = st.text_input("Name ändern:", value=f_name, key=f"edit_name_{key_hash}")
                            with col_ed2:
                                cat_select_options = all_category_names + ["➕ [Neue Kategorie erstellen...]"]
                                cat_default_idx = all_category_names.index(cat_name) if cat_name in all_category_names else 0
                                edit_cat_choice = st.selectbox(
                                    "Kategorie ändern / verschieben:",
                                    options=cat_select_options,
                                    index=cat_default_idx,
                                    key=f"edit_cat_{key_hash}",
                                    help="Wähle eine bestehende Kategorie oder erstelle eine neue, um diesen Feed dorthin zu verschieben."
                                )

                            if edit_cat_choice == "➕ [Neue Kategorie erstellen...]":
                                custom_cat_input = st.text_input(
                                    "Name der neuen Ziel-Kategorie:",
                                    placeholder="z. B. Wissenschaft & Raumfahrt",
                                    key=f"edit_custom_cat_{key_hash}"
                                )
                                target_category_val = custom_cat_input.strip()
                            else:
                                target_category_val = edit_cat_choice.strip()

                            edit_url_val = st.text_input("URL ändern:", value=f_url, key=f"edit_url_{key_hash}")

                            f_inc_str = ", ".join(f_inc) if isinstance(f_inc, list) else str(f_inc or "")
                            f_exc_str = ", ".join(f_exc) if isinstance(f_exc, list) else str(f_exc or "")
                            col_ek1, col_ek2 = st.columns(2)
                            with col_ek1:
                                edit_inc_val = st.text_input(
                                    "🟢 Nur Artikel mit Keywords aufnehmen (Einschließen):",
                                    value=f_inc_str,
                                    placeholder="z. B. Mahlsdorf, Kaulsdorf",
                                    key=f"edit_inc_{key_hash}",
                                    help="Wenn ausgefüllt, werden nur Artikel übernommen, die mindestens eines dieser Wörter enthalten."
                                )
                            with col_ek2:
                                edit_exc_val = st.text_input(
                                    "🔴 Artikel mit Keywords ausschließen (Ausschließen):",
                                    value=f_exc_str,
                                    placeholder="z. B. Sport, Krypto",
                                    key=f"edit_exc_{key_hash}",
                                    help="Artikel mit diesen Wörtern werden ignoriert."
                                )

                            col_t_btn, col_s_btn, col_d_btn = st.columns([1, 1, 1])
                            with col_t_btn:
                                if st.button("🔍 Feed testen", key=f"btn_test_{key_hash}", use_container_width=True):
                                    with st.spinner("Prüfe Feed-URL und Stream..."):
                                        t_res = test_feed_connection(edit_url_val.strip())
                                        render_feed_test_result(t_res)
                            with col_s_btn:
                                if st.button("✔️ Im Entwurf vormerken", key=f"btn_save_all_{key_hash}", use_container_width=True, help="Übernimmt die Feed-Anpassung in den Arbeitsentwurf"):
                                    if not edit_name_val.strip():
                                        st.error("Der Feed-Name darf nicht leer sein.")
                                    elif not edit_url_val.strip() or not (edit_url_val.strip().startswith("http://") or edit_url_val.strip().startswith("https://")):
                                        st.error("Bitte gib eine gültige URL an (beginnend mit http:// oder https://).")
                                    elif not target_category_val:
                                        st.error("Bitte gib einen Namen für die Ziel-Kategorie an.")
                                    else:
                                        try:
                                            update_feed(
                                                cat_name,
                                                f_url,
                                                new_name=edit_name_val.strip(),
                                                new_url=edit_url_val.strip(),
                                                new_category=target_category_val,
                                                include_keywords=edit_inc_val.strip(),
                                                exclude_keywords=edit_exc_val.strip(),
                                                config=working_config,
                                                save_to_disk=False
                                            )
                                            st.session_state["has_unsaved_changes"] = True
                                            st.session_state["pending_nav_tab"] = "manage"
                                            st.query_params["tab"] = "manage"
                                            st.session_state["last_edited_category"] = target_category_val
                                            if target_category_val.lower() != cat_name.lower():
                                                st.toast(f"Feed '{edit_name_val.strip()}' in Kategorie '{target_category_val}' verschoben (noch nicht gespeichert).", icon="📦")
                                            else:
                                                st.toast("Feed-Details übernommen (noch nicht gespeichert).", icon="✏️")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Fehler beim Übernehmen: {e}")
                            with col_d_btn:
                                if st.button("💾 Direkt speichern & pushen", key=f"btn_direct_{key_hash}", type="primary", use_container_width=True, help="Speichert sofort dauerhaft in sources.yaml und synchronisiert zu GitHub & CDN"):
                                    if not edit_name_val.strip():
                                        st.error("Der Feed-Name darf nicht leer sein.")
                                    elif not edit_url_val.strip() or not (edit_url_val.strip().startswith("http://") or edit_url_val.strip().startswith("https://")):
                                        st.error("Bitte gib eine gültige URL an (beginnend mit http:// oder https://).")
                                    elif not target_category_val:
                                        st.error("Bitte gib einen Namen für die Ziel-Kategorie an.")
                                    else:
                                        try:
                                            update_feed(
                                                cat_name,
                                                f_url,
                                                new_name=edit_name_val.strip(),
                                                new_url=edit_url_val.strip(),
                                                new_category=target_category_val,
                                                include_keywords=edit_inc_val.strip(),
                                                exclude_keywords=edit_exc_val.strip(),
                                                config=working_config,
                                                save_to_disk=False
                                            )
                                            st.session_state["pending_nav_tab"] = "manage"
                                            st.query_params["tab"] = "manage"
                                            st.session_state["last_edited_category"] = target_category_val
                                            perform_save_all()
                                        except Exception as e:
                                            st.error(f"Fehler beim Speichern: {e}")

    st.markdown("---")

    # --- Sektion 4: Globale Einstellungen ---
    with st.expander("⚙️ Globale Einstellungen", expanded=False):
        current_settings = working_config.get("settings", {})
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            current_lang = current_settings.get("language", "de")
            lang_options = ["de", "en", "fr", "es"]
            lang_idx = lang_options.index(current_lang) if current_lang in lang_options else 0
            setting_lang = st.selectbox("Sprache für Zusammenfassung:", options=lang_options, index=lang_idx, key="input_setting_lang")
        with col_s2:
            current_style = current_settings.get("summary_style", "tldr")
            style_options = ["tldr", "executive_bullet_points", "bullet_points", "narrative"]
            style_idx = style_options.index(current_style) if current_style in style_options else 0
            setting_style = st.selectbox("Briefing-Stil:", options=style_options, index=style_idx, key="input_setting_style")
        with col_s3:
            raw_age = current_settings.get("max_article_age_weeks")
            if raw_age is None:
                raw_age = current_settings.get("max_age_weeks", DEFAULT_MAX_ARTICLE_AGE_WEEKS)
            try:
                curr_age_val = int(raw_age)
            except (ValueError, TypeError):
                curr_age_val = DEFAULT_MAX_ARTICLE_AGE_WEEKS
            setting_max_age = st.number_input(
                "Max. Artikel-Alter (Wochen):",
                min_value=0,
                max_value=104,
                value=curr_age_val,
                step=1,
                key="input_setting_max_age_weeks",
                help="Artikel, die älter als diese Anzahl an Wochen sind, werden automatisch herausgefiltert und nicht angezeigt (Standard: 20 Wochen). 0 = Keine Altersbegrenzung."
            )

        col_url, col_sync = st.columns([1.5, 1])
        with col_url:
            default_app_url = current_settings.get("streamlit_app_url", os.getenv("STREAMLIT_APP_URL", "https://news-aggregator-bot-sdfgedfwcu7yr9gzikr8q8.streamlit.app"))
            setting_app_url = st.text_input(
                "Streamlit App URL:",
                value=default_app_url,
                key="input_setting_app_url",
                help="Basis-URL dieser Streamlit-App (wird in den E-Mail-Briefings für jede Kategorie verlinkt)."
            )
        with col_sync:
            raw_sync_interval = current_settings.get("batch_sync_interval_minutes", DEFAULT_BUFFER_INTERVAL_MINUTES)
            try:
                curr_sync_interval = int(raw_sync_interval)
            except (ValueError, TypeError):
                curr_sync_interval = DEFAULT_BUFFER_INTERVAL_MINUTES
            sync_interval_options = [1, 3, 5, 10, 15, 30]
            if curr_sync_interval not in sync_interval_options:
                curr_sync_interval = 5
            sync_interval_labels = {
                1: "1 Minute",
                3: "3 Minuten",
                5: "5 Minuten (Empfohlen)",
                10: "10 Minuten",
                15: "15 Minuten",
                30: "30 Minuten",
            }
            setting_sync_interval = st.selectbox(
                "Puffer-Sync (Gelesen/Likes):",
                options=sync_interval_options,
                index=sync_interval_options.index(curr_sync_interval),
                format_func=lambda x: sync_interval_labels.get(x, f"{x} Minuten"),
                key="input_setting_sync_interval",
                help="Legt fest, nach wie vielen Minuten als gelesen markierte Artikel und Bewertungen gesammelt in die Datenbank geschrieben werden (Bulk-Sync)."
            )

        st.markdown("---")

        current_filter_ads = current_settings.get("filter_ads", True)
        setting_filter_ads = st.checkbox(
            "🚫 Werbe- & Anzeigen-Filter aktiv",
            value=current_filter_ads,
            key="input_setting_filter_ads",
            help="Entfernt automatisch Promotion- und Werbeartikel wie 'heise-Angebot', 'Anzeige', 'Sponsored' etc."
        )

        default_ad_kws = current_settings.get("ad_keywords")
        if not default_ad_kws or not isinstance(default_ad_kws, list):
            default_ad_kws = [
                "heise-angebot", "anzeige", "werbung", "sponsored",
                "gesponsert", "advertorial", "partnerangebot",
                "deal des tages", "rabatt-aktion"
            ]

        if setting_filter_ads:
            setting_ad_keywords_str = st.text_area(
                "Auszuschließende Werbe-Keywords & Promotion-Muster (Komma-getrennt):",
                value=", ".join(default_ad_kws),
                key="input_setting_ad_keywords",
                help="Auszuschließende Werbe-Keywords & Promotion-Muster (Komma-getrennt). Artikel, deren Titel oder Teaser diese Begriffe enthalten, werden bei aktivem Werbefilter automatisch herausgefiltert.",
                label_visibility="collapsed",
                height=70
            )
        else:
            setting_ad_keywords_str = ", ".join(default_ad_kws)

        col_g1, col_g2 = st.columns(2)
        with col_g1:
            if st.button("✔️ Im Entwurf vormerken", type="secondary", use_container_width=True, key="btn_apply_global_settings"):
                parsed_ad_kws = [k.strip() for k in setting_ad_keywords_str.split(",") if k.strip()]
                new_settings_dict = {
                    "language": setting_lang,
                    "summary_style": setting_style,
                    "streamlit_app_url": setting_app_url.strip(),
                    "batch_sync_interval_minutes": int(setting_sync_interval),
                    "max_article_age_weeks": int(setting_max_age),
                    "filter_ads": setting_filter_ads,
                    "ad_keywords": parsed_ad_kws,
                }
                action_buffer.set_interval_minutes(int(setting_sync_interval))
                if "custom_prompt_directives" in current_settings:
                    new_settings_dict["custom_prompt_directives"] = current_settings["custom_prompt_directives"]
                if "custom_main_prompt" in current_settings:
                    new_settings_dict["custom_main_prompt"] = current_settings["custom_main_prompt"]
                update_settings(new_settings_dict, config=working_config, save_to_disk=False)
                st.session_state["has_unsaved_changes"] = True
                st.session_state["pending_nav_tab"] = "manage"
                st.query_params["tab"] = "manage"
                st.toast("Globale Einstellungen im Entwurf übernommen (noch nicht gespeichert).", icon="⚙️")
                st.rerun()
        with col_g2:
            if st.button("💾 Direkt speichern & pushen", type="primary", use_container_width=True, key="btn_save_global_settings_direct"):
                parsed_ad_kws = [k.strip() for k in setting_ad_keywords_str.split(",") if k.strip()]
                new_settings_dict = {
                    "language": setting_lang,
                    "summary_style": setting_style,
                    "streamlit_app_url": setting_app_url.strip(),
                    "batch_sync_interval_minutes": int(setting_sync_interval),
                    "max_article_age_weeks": int(setting_max_age),
                    "filter_ads": setting_filter_ads,
                    "ad_keywords": parsed_ad_kws,
                }
                action_buffer.set_interval_minutes(int(setting_sync_interval))
                if "custom_prompt_directives" in current_settings:
                    new_settings_dict["custom_prompt_directives"] = current_settings["custom_prompt_directives"]
                if "custom_main_prompt" in current_settings:
                    new_settings_dict["custom_main_prompt"] = current_settings["custom_main_prompt"]
                update_settings(new_settings_dict, config=working_config, save_to_disk=False)
                perform_save_all()

        st.caption("🔒 **Sicherheitshinweis:** Sensible Zugangsdaten wie `APP_PASSWORD` oder API-Keys werden niemals in `sources.yaml` gespeichert, sondern sicher als Secrets in **GitHub Actions** und **Streamlit Cloud** verwaltet.")

    # --- Sektion 5: Live-Vorschau der sources.yaml Datei ---
    with st.expander("📄 Live-Vorschau der Konfiguration (Entwurf)", expanded=False):
        try:
            import yaml
            yaml_raw = yaml.dump(working_config, allow_unicode=True, sort_keys=False, default_flow_style=False)
            st.code(yaml_raw, language="yaml")
            if has_unsaved_changes:
                st.caption("⚠️ Diese Vorschau enthält noch ungespeicherte Änderungen.")
            else:
                st.caption("✅ Entspricht dem aktuellen Stand auf der Festplatte.")

            col_v1, col_v2 = st.columns([1, 1])
            with col_v1:
                st.download_button(
                    "📥 sources.yaml Entwurf herunterladen",
                    data=yaml_raw,
                    file_name="sources.yaml",
                    mime="text/yaml",
                    use_container_width=True
                )
            with col_v2:
                if has_unsaved_changes:
                    if st.button("💾 Alle Änderungen jetzt speichern", type="primary", use_container_width=True, key="btn_preview_save"):
                        perform_save_all()
                elif gh_cfg["token"]:
                    if st.button("🐙 Manuell zu GitHub synchronisieren", use_container_width=True, key="btn_preview_gh_sync"):
                        with st.spinner("Pushe zu GitHub..."):
                            sync_res = sync_sources_to_github(config_dict=working_config)
                            if sync_res["success"]:
                                st.success("Erfolgreich zu GitHub synchronisiert!")
                                st.toast("Zu GitHub gepusht!", icon="🐙")
                            else:
                                st.error(f"Fehler: {sync_res['error']}")
        except Exception as e:
            st.error(f"Fehler bei der Vorschau: {e}")

    # --- Unterer Abschluss- und Speicher-Bereich ---
    if has_unsaved_changes:
        st.markdown("---")
        with st.container(border=True):
            st.markdown("### 💾 Änderungen abschließen")
            st.write("Du hast alle Aktionen durchgeführt? Klicke auf **'💾 Alle Änderungen jetzt speichern'**, um die Konfiguration dauerhaft in `sources.yaml` zu sichern und mit GitHub zu synchronisieren.")
            col_end_s, col_end_d, col_end_space = st.columns([2, 1, 3], vertical_alignment="center")
            with col_end_s:
                if st.button("💾 Alle Änderungen jetzt speichern", type="primary", use_container_width=True, key="btn_save_all_bottom"):
                    perform_save_all()
            with col_end_d:
                if st.button("↩️ Änderungen verwerfen", use_container_width=True, key="btn_discard_all_bottom"):
                    perform_discard_all()
            with col_end_space:
                st.caption("Alle Änderungen werden in einem einzigen Schritt gebündelt gespeichert.")

