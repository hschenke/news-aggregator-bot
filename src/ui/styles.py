"""
UI Styles and client-side CSS module for News Aggregator Bot.
Encapsulates all layout, responsive design, anti-stale optimizations, and typography rules.
"""

from __future__ import annotations

import streamlit as st


def embed_client_script(js_code: str) -> None:
    """Führt Hilfsskripte (z. B. Cookie/Storage-Sync) modern und unsichtbar via st.html aus (Chrome & Firefox)."""
    if not js_code or not js_code.strip():
        return
    html_wrapper = (
        f"<div style='display:none !important;width:0 !important;height:0 !important;"
        f"margin:0 !important;padding:0 !important;overflow:hidden !important;border:none !important;'>"
        f"<script>{js_code}</script></div>"
    )
    st.html(html_wrapper, unsafe_allow_javascript=True)



def apply_custom_styles() -> None:
    """Applies high-performance custom CSS to the Streamlit app."""
    st.markdown("""
<style>
    /* Main container spacing */
    .block-container {
        padding-top: 3.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.25rem !important;
        padding-right: 1.25rem !important;
        max-width: 1250px;
    }

    /* Invisible helper iframes */
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

    /* Header link anchors */
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

    /* Skeleton loaders */
    [data-testid="stSkeleton"],
    [data-testid="stSkeletonElement"],
    .stSkeleton {
        display: none !important;
        opacity: 0 !important;
        visibility: hidden !important;
    }

    /* Anti-stale state: prevents greying / fading out during reruns */
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

    /* Keep buttons and feedback visible and active */
    [data-testid="stFeedback"] button:disabled,
    [data-testid="stFeedback"] button[data-disabled="true"],
    [data-testid="stFeedback"] button[disabled],
    div[class*="st-key-read_"] button:disabled,
    div[class*="st-key-read_"] button[data-disabled="true"],
    div[class*="st-key-read_"] button[disabled] {
        opacity: 1 !important;
        cursor: pointer !important;
    }

    .stApp[data-test-script-state="running"] [data-testid="stVerticalBlockBorderWrapper"],
    .stApp[data-test-script-state="running"] [data-testid="stElementContainer"],
    .stApp[data-test-script-state="running"] [data-testid="stFeedback"],
    .stApp[data-test-script-state="running"] div[class*="st-key-read_"] {
        opacity: 1 !important;
        filter: none !important;
    }

    /* Card container styling */
    [data-testid="stVerticalBlockBorderWrapper"] {
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        overflow-wrap: anywhere !important;
        word-break: break-word !important;
        overflow: hidden !important;
        border-radius: 0.5rem !important;
        transition: transform 0.1s ease, box-shadow 0.1s ease !important;
    }

    /* Action bar inside article cards */
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        justify-content: space-between !important;
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        margin-top: 0.4rem !important;
    }

    /* Links: Bewertungs-Daumen */
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child,
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: flex-start !important;
        flex: 1 1 auto !important;
        width: auto !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child [data-testid="stVerticalBlock"],
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: flex-start !important;
        width: 100% !important;
        gap: 0 !important;
    }

    /* Rechts: Gelesen-Button bündig am rechten Rand */
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child,
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: flex-end !important;
        flex: 1 1 auto !important;
        width: auto !important;
        margin-left: auto !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"],
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: flex-end !important;
        width: 100% !important;
        gap: 0 !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child .stButton,
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child .stButton,
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child div[class*="st-key-read_"],
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child div[class*="st-key-read_"] {
        display: inline-flex !important;
        justify-content: flex-end !important;
        align-items: center !important;
        margin-left: auto !important;
        margin-right: 0 !important;
        width: auto !important;
    }

    /* Badges */
    .news-badge {
        display: inline-block;
        padding: 0.2rem 0.5rem;
        font-size: 0.75rem;
        font-weight: 600;
        border-radius: 0.25rem;
        margin-right: 0.4rem;
        margin-bottom: 0.3rem;
    }
    .news-badge-cat {
        background-color: rgba(37, 99, 235, 0.12);
        color: #2563EB;
        border: 1px solid rgba(37, 99, 235, 0.25);
    }
    .news-badge-source {
        background-color: rgba(100, 116, 139, 0.12);
        color: #475569;
        border: 1px solid rgba(100, 116, 139, 0.2);
    }
    .news-badge-date {
        background-color: rgba(148, 163, 184, 0.1);
        color: #64748B;
    }

    /* Sidebar Navigation */
    .custom-nav-container {
        display: flex !important;
        flex-direction: column !important;
        gap: 0.45rem !important;
        margin-top: 0 !important;
        margin-bottom: 0.5rem !important;
        width: 100% !important;
    }
    .custom-nav-btn {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: 100% !important;
        padding-top: 0.4rem !important;
        padding-bottom: 0.4rem !important;
        padding-left: 0.65rem !important;
        padding-right: 0.65rem !important;
        min-height: 2.25rem !important;
        line-height: 1.2 !important;
        font-size: 0.88rem !important;
        font-weight: 500 !important;
        border-radius: 0.45rem !important;
        border: 1px solid rgba(128, 128, 128, 0.22) !important;
        background-color: transparent !important;
        color: inherit !important;
        cursor: pointer !important;
        transition: all 0.15s ease-in-out !important;
        text-align: center !important;
        box-sizing: border-box !important;
        user-select: none !important;
    }
    .custom-nav-btn:hover:not(.disabled-nav-btn) {
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
    .custom-nav-btn.disabled-nav-btn {
        opacity: 0.42 !important;
        cursor: not-allowed !important;
        border: 1px dashed rgba(128, 128, 128, 0.3) !important;
        color: rgba(128, 128, 128, 0.8) !important;
        background-color: transparent !important;
    }

    /* Streamlit tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.5rem;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 0.95rem;
        font-weight: 500;
        padding: 0.5rem 1rem;
        border-radius: 0.375rem;
    }

    /* KPI chips */
    .kpi-container {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
        margin: 0.4rem 0;
    }
    .kpi-chip {
        padding: 0.25rem 0.5rem;
        border-radius: 0.375rem;
        font-size: 0.8rem;
        font-weight: 600;
        background-color: rgba(128, 128, 128, 0.1);
    }

    /* Bewertungs-Daumen kompakt & direkt unterm Text platzieren */
    [data-testid="stFeedback"] {
        margin-top: 0.25rem !important;
        margin-bottom: 0 !important;
        padding: 0 !important;
        display: inline-flex !important;
        align-items: center !important;
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

    /* Gelesen-Symbol Styling: Randlos, transparent, dezent wie st.feedback */
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
    div[class*="st-key-read_"] button [data-testid="stIconMaterial"],
    div[class*="st-key-read_"] button span {
        color: #16a34a !important;
        font-variation-settings: 'FILL' 1, 'wght' 600 !important;
    }

    /* Mobile Responsive Rules */
    @media (max-width: 768px) {
        /* Suchleiste auf Mobile: Eingabefeld, Reset und Go in einer Zeile bündig halten */
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
        }
        [data-testid="stHorizontalBlock"]:has(.st-key-input_search_query) > [data-testid="stColumn"]:has(.st-key-btn_search_go),
        [data-testid="stHorizontalBlock"]:has(.st-key-input_search_query) > [data-testid="column"]:has(.st-key-btn_search_go) {
            min-width: 2.5rem !important;
            max-width: 2.75rem !important;
            flex: 0 0 2.5rem !important;
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
            justify-content: flex-start !important;
            flex: 1 1 auto !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child,
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child {
            justify-content: flex-end !important;
            margin-left: auto !important;
        }
    }
</style>
""", unsafe_allow_html=True)
