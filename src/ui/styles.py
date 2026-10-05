"""
UI Styles and client-side CSS module for News Aggregator Bot.
Encapsulates all layout, responsive design, anti-stale optimizations, and typography rules.
"""

from __future__ import annotations

import time
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


def render_dismissible_notice(notice_text: str, notice_key: str, icon: str = "✅") -> None:
    """Renders a prominent, dismissible notice banner with an instant client-side close button."""
    if not notice_text or not str(notice_text).strip():
        return
    import html
    import hashlib
    escaped_text = html.escape(str(notice_text).strip())
    content_hash = hashlib.md5(escaped_text.encode("utf-8")).hexdigest()[:8]
    banner_id = f"notice-banner-{notice_key}-{content_hash}"
    btn_id = f"notice-close-btn-{notice_key}-{content_hash}"
    html_markup = f"""
    <div id="{banner_id}" class="persistent-dismissible-notice" data-banner-id="{banner_id}">
        <div class="notice-content">
            <span class="notice-icon">{icon}</span>
            <span class="notice-message" style="color: #065f46; font-weight: 600;">{escaped_text}</span>
        </div>
        <button id="{btn_id}" class="notice-close-btn" type="button" onclick="var el=document.getElementById('{banner_id}');if(el){{el.style.display='none';el.remove();}}" title="Hinweis schließen">✖</button>
    </div>
    <script>
    (function() {{
        var bId = "{banner_id}";
        var btnId = "{btn_id}";
        try {{
            if (sessionStorage.getItem(bId) === "dismissed") {{
                var el = document.getElementById(bId);
                if (el) {{
                    el.style.display = "none";
                    el.remove();
                }}
                return;
            }}
        }} catch(e) {{}}
        var btn = document.getElementById(btnId);
        if (btn) {{
            btn.onclick = function() {{
                try {{ sessionStorage.setItem(bId, "dismissed"); }} catch(e) {{}}
                var el = document.getElementById(bId);
                if (el) {{
                    el.style.display = "none";
                    el.remove();
                }}
            }};
        }}

        // Auto-dismiss after 10 seconds with smooth fade-out
        setTimeout(function() {{
            var el = document.getElementById(bId);
            if (el) {{
                el.style.transition = "opacity 0.6s ease, max-height 0.6s ease, margin 0.6s ease, padding 0.6s ease";
                el.style.opacity = "0";
                el.style.maxHeight = "0";
                el.style.paddingTop = "0";
                el.style.paddingBottom = "0";
                el.style.marginTop = "0";
                el.style.marginBottom = "0";
                setTimeout(function() {{
                    try {{ sessionStorage.setItem(bId, "dismissed"); }} catch(e) {{}}
                    if (el && el.parentNode) {{
                        el.remove();
                    }}
                }}, 600);
            }}
        }}, 10000);
    }})();
    </script>
    """
    st.html(html_markup, unsafe_allow_javascript=True)


def release_action_overlay() -> None:
    """Ensure that the loading overlay is released once the page render completes."""
    nonce = time.time()
    embed_client_script(f"""
        (function() {{
            var _t = '{nonce}';
            if (window._newsBotHideActionOverlay) {{
                window._newsBotHideActionOverlay();
            }}
            var el = document.getElementById('news-bot-loading-overlay');
            if (el) {{
                el.classList.remove('active');
                el.style.display = 'none';
                el.style.opacity = '0';
                el.style.visibility = 'hidden';
                el.style.pointerEvents = 'none';
            }}
        }})();
    """)



def apply_custom_styles() -> None:
    """Applies high-performance custom CSS to the Streamlit app."""
    st.markdown("""
<style>
    /* Main container spacing - balanced clean layout */
    .block-container {
        padding-top: 2.25rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.25rem !important;
        padding-right: 1.25rem !important;
        max-width: 1250px;
    }

    /* Vertical block flow: balanced gaps */
    [data-testid="stVerticalBlock"] {
        gap: 0.55rem !important;
    }

    /* Sidebar vertical flow: balanced spacing without crowding */
    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.45rem !important;
    }

    /* Divider rules: visible, balanced dividers */
    hr, [data-testid="stDivider"], .stMarkdown hr {
        margin-top: 0.55rem !important;
        margin-bottom: 0.55rem !important;
        border: none !important;
        border-top: 1px solid rgba(128, 128, 128, 0.3) !important;
    }

    section[data-testid="stSidebar"] hr,
    section[data-testid="stSidebar"] [data-testid="stDivider"],
    section[data-testid="stSidebar"] .stMarkdown hr {
        margin-top: 0.5rem !important;
        margin-bottom: 0.5rem !important;
        border: none !important;
        border-top: 1px solid rgba(128, 128, 128, 0.35) !important;
        display: block !important;
        width: 100% !important;
    }

    /* Headings & Section Typography */
    h1 {
        margin-top: 0 !important;
        margin-bottom: 0.15rem !important;
        line-height: 1.2 !important;
        padding: 0 !important;
    }
    h2, .stSubheader {
        margin-top: 0.4rem !important;
        margin-bottom: 0.25rem !important;
        padding: 0 !important;
    }
    h3, .stMarkdown h3 {
        margin-top: 1.1rem !important;
        margin-bottom: 0.45rem !important;
        padding: 0 !important;
    }
    h4, h5, h6 {
        margin-top: 0.4rem !important;
        margin-bottom: 0.25rem !important;
        padding: 0 !important;
    }

    /* Captions: tight paragraph margins to prevent vertical drifting */
    .stCaption, [data-testid="stCaptionContainer"] {
        margin-top: 0.1rem !important;
        margin-bottom: 0.2rem !important;
        line-height: 1.3 !important;
    }
    .stCaption p, [data-testid="stCaptionContainer"] p {
        margin-top: 0 !important;
        margin-bottom: 0 !important;
    }

    section[data-testid="stSidebar"] .stCaption,
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        margin-top: 0.1rem !important;
        margin-bottom: 0.1rem !important;
    }
    section[data-testid="stSidebar"] .stCaption p {
        margin: 0 !important;
        padding: 0 !important;
    }

    /* Main header: close gap between title, caption and tabs */
    .block-container [data-testid="stElementContainer"]:has(h1) {
        margin-bottom: 0 !important;
    }
    .block-container [data-testid="stElementContainer"]:has(.stCaption) {
        margin-top: 0 !important;
        margin-bottom: 0 !important;
    }
    .block-container [data-testid="stElementContainer"]:has(.stTabs) {
        margin-top: 0.1rem !important;
    }

    /* Streamlit tabs */
    .stTabs {
        margin-top: 0.15rem !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.4rem !important;
        margin-top: 0 !important;
        margin-bottom: 0.65rem !important;
        padding-top: 0 !important;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 0.95rem;
        font-weight: 500;
        padding: 0.45rem 0.9rem;
        border-radius: 0.375rem;
    }

    /* Compact alerts */
    [data-testid="stAlert"] {
        padding: 0.5rem 0.8rem !important;
        margin-top: 0.15rem !important;
        margin-bottom: 0.15rem !important;
    }
    [data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {
        margin: 0 !important;
        line-height: 1.35 !important;
    }

    /* Expander spacing: comfortable separation so cards don't look glued together */
    [data-testid="stExpander"] {
        margin-top: 0.35rem !important;
        margin-bottom: 0.65rem !important;
        border-radius: 0.5rem !important;
    }
    [data-testid="stExpander"] details summary {
        padding: 0.45rem 0.85rem !important;
    }
    [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
        padding: 0.65rem 0.85rem !important;
    }

    /* Expander inner caption & label tightening (fixes gap in KI Prompt configuration) */
    [data-testid="stExpanderDetails"] [data-testid="stVerticalBlock"] {
        gap: 0.35rem !important;
    }
    [data-testid="stExpanderDetails"] .stCaption {
        margin-top: 0 !important;
        margin-bottom: 0.15rem !important;
    }
    [data-testid="stExpanderDetails"] .stCaption p {
        margin: 0 !important;
        padding: 0 !important;
    }
    [data-testid="stExpanderDetails"] [data-testid="stWidgetLabel"] {
        margin-top: 0.15rem !important;
        margin-bottom: 0.15rem !important;
        min-height: 0 !important;
    }
    [data-testid="stExpanderDetails"] [data-testid="stWidgetLabel"] label,
    [data-testid="stExpanderDetails"] [data-testid="stWidgetLabel"] p {
        margin: 0 !important;
        padding: 0 !important;
    }

    /* Bordered containers (Status box, Feed cards) */
    [data-testid="stVerticalBlockBorderWrapper"] {
        margin-top: 0.35rem !important;
        margin-bottom: 0.75rem !important;
        padding: 0.65rem 0.85rem !important;
    }

    /* Compact buttons */
    .stButton button {
        padding: 0.35rem 0.75rem !important;
        min-height: 2.15rem !important;
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

    /* Sidebar Header & Version Badge Spacing */
    .sidebar-header-container {
        display: flex !important;
        align-items: center !important;
        gap: 12px !important;
        margin-top: 0.2rem !important;
        margin-bottom: 0.25rem !important;
    }
    .sidebar-header-title {
        font-size: 1.35rem !important;
        font-weight: 700 !important;
        line-height: 1.2 !important;
        margin: 0 !important;
        display: inline-flex !important;
        align-items: center !important;
    }
    .sidebar-version-badge {
        display: inline-flex !important;
        align-items: center !important;
        margin-left: 10px !important;
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        padding: 2px 8px !important;
        border-radius: 6px !important;
        background: rgba(37, 99, 235, 0.1) !important;
        border: 1px solid rgba(37, 99, 235, 0.25) !important;
        color: #2563eb !important;
        letter-spacing: 0.02em !important;
        vertical-align: middle !important;
        white-space: nowrap !important;
    }

    /* Sidebar Navigation */
    .custom-nav-container {
        display: flex !important;
        flex-direction: column !important;
        gap: 0.45rem !important;
        margin-top: 0.25rem !important;
        margin-bottom: 0.25rem !important;
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

    /* Centered Action Loading Overlay: Greys out entire page, disables interaction, shows central spinner */
    #news-bot-loading-overlay {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        width: 100vw !important;
        height: 100vh !important;
        background-color: rgba(15, 23, 42, 0.72) !important;
        backdrop-filter: blur(5px) !important;
        -webkit-backdrop-filter: blur(5px) !important;
        z-index: 9999999 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        justify-content: center !important;
        color: #ffffff !important;
        pointer-events: none !important;
        opacity: 0 !important;
        visibility: hidden !important;
        transition: opacity 0.15s ease-in-out, visibility 0.15s ease-in-out !important;
    }
    #news-bot-loading-overlay.active {
        opacity: 1 !important;
        visibility: visible !important;
        pointer-events: all !important;
    }
    .action-spinner-circle {
        width: 58px !important;
        height: 58px !important;
        border: 5px solid rgba(255, 255, 255, 0.22) !important;
        border-top-color: #38bdf8 !important;
        border-radius: 50% !important;
        animation: spin-action-overlay 0.85s linear infinite !important;
        margin-bottom: 1.25rem !important;
    }
    @keyframes spin-action-overlay {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    .action-spinner-title {
        font-size: 1.35rem !important;
        font-weight: 700 !important;
        color: #f8fafc !important;
        text-align: center !important;
        max-width: 85% !important;
        line-height: 1.4 !important;
        text-shadow: 0 2px 6px rgba(0, 0, 0, 0.6) !important;
    }
    .action-spinner-subtitle {
        font-size: 0.95rem !important;
        color: #cbd5e1 !important;
        margin-top: 0.5rem !important;
        text-align: center !important;
        max-width: 80% !important;
        line-height: 1.4 !important;
    }
    /* Hide all Streamlit toasts globally */
    [data-testid="stToast"],
    .stToast {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
        height: 0 !important;
        width: 0 !important;
        overflow: hidden !important;
    }

    /* Strikte Formatierung für deaktivierte Buttons (z. B. 💾 Gespeichert) */
    button:disabled,
    button[disabled],
    [data-testid="stBaseButton-secondary"]:disabled,
    [data-testid="stBaseButton-primary"]:disabled {
        opacity: 0.45 !important;
        cursor: not-allowed !important;
        pointer-events: none !important;
        filter: grayscale(0.6) !important;
    }

    /* Persistentes Hinweisfeld mit sofort schließendem X-Button ohne Server-Roundtrip */
    .persistent-dismissible-notice {
        display: flex !important;
        align-items: center !important;
        justify-content: space-between !important;
        background-color: #ecfdf5 !important;
        border: 1px solid #6ee7b7 !important;
        border-left: 4px solid #059669 !important;
        border-radius: 8px !important;
        padding: 0.5rem 0.85rem !important;
        margin-bottom: 0.5rem !important;
        color: #065f46 !important;
        font-size: 0.92rem !important;
        line-height: 1.35 !important;
        box-sizing: border-box !important;
        width: 100% !important;
    }
    .persistent-dismissible-notice .notice-content {
        display: flex !important;
        align-items: center !important;
        gap: 0.6rem !important;
        flex: 1 1 auto !important;
        font-weight: 600 !important;
        color: #065f46 !important;
    }
    .persistent-dismissible-notice .notice-icon {
        font-size: 1.15rem !important;
        line-height: 1 !important;
        flex-shrink: 0 !important;
    }
    .persistent-dismissible-notice .notice-message {
        color: #065f46 !important;
        font-weight: 600 !important;
    }
    .persistent-dismissible-notice .notice-close-btn {
        background: transparent !important;
        border: none !important;
        color: #047857 !important;
        font-size: 1.25rem !important;
        font-weight: 700 !important;
        line-height: 1 !important;
        padding: 0.2rem 0.6rem !important;
        margin-left: 0.75rem !important;
        cursor: pointer !important;
        border-radius: 4px !important;
        transition: color 0.15s ease, background-color 0.15s ease !important;
        flex-shrink: 0 !important;
    }
    .persistent-dismissible-notice .notice-close-btn:hover {
        color: #064e3b !important;
        background-color: rgba(5, 150, 105, 0.15) !important;
    }

    @media (prefers-color-scheme: dark) {
        .persistent-dismissible-notice {
            background-color: rgba(6, 78, 59, 0.35) !important;
            border-color: rgba(52, 211, 153, 0.35) !important;
            border-left-color: #34d399 !important;
            color: #ecfdf5 !important;
        }
        .persistent-dismissible-notice .notice-content,
        .persistent-dismissible-notice .notice-message {
            color: #ecfdf5 !important;
        }
        .persistent-dismissible-notice .notice-close-btn {
            color: #86efac !important;
        }
        .persistent-dismissible-notice .notice-close-btn:hover {
            color: #ffffff !important;
            background-color: rgba(255, 255, 255, 0.15) !important;
        }
    }
</style>
""", unsafe_allow_html=True)

    # Centered Action Loading Overlay DOM & Client Interceptor
    st.html("""
    <div id="news-bot-loading-overlay">
        <div class="action-spinner-circle"></div>
        <div id="news-bot-loading-title" class="action-spinner-title">Aktion wird ausgeführt...</div>
        <div id="news-bot-loading-subtitle" class="action-spinner-subtitle">Bitte einen Moment Geduld</div>
    </div>
    <script>
    (function() {
        function getOverlay(doc) {
            var el = doc.getElementById("news-bot-loading-overlay");
            if (!el && window.parent && window.parent.document) {
                try { el = window.parent.document.getElementById("news-bot-loading-overlay"); } catch(e) {}
            }
            return el;
        }

        function hideActionOverlay() {
            var overlay = getOverlay(document);
            if (overlay) {
                overlay.classList.remove("active");
                overlay.style.display = "none";
                overlay.style.opacity = "0";
                overlay.style.visibility = "hidden";
                overlay.style.pointerEvents = "none";
            }
        }
        window._newsBotHideActionOverlay = hideActionOverlay;

        function showActionOverlay(title, subtitle) {
            var overlay = getOverlay(document);
            if (overlay) {
                var titleEl = overlay.querySelector(".action-spinner-title") || document.getElementById("news-bot-loading-title");
                var subEl = overlay.querySelector(".action-spinner-subtitle") || document.getElementById("news-bot-loading-subtitle");
                if (titleEl && title) titleEl.innerText = title;
                if (subEl && subtitle) subEl.innerText = subtitle;
                overlay.classList.add("active");
                overlay.style.display = "flex";
                overlay.style.opacity = "1";
                overlay.style.visibility = "visible";
                overlay.style.pointerEvents = "all";

                overlay.onclick = function() {
                    hideActionOverlay();
                };
            }

            // Watch for Streamlit execution finish and release overlay
            var startTime = Date.now();
            var wasRunning = false;
            var checkIdleInterval = setInterval(function() {
                var doc = (overlay && overlay.ownerDocument) ? overlay.ownerDocument : document;
                var rootApp = doc.querySelector('.stApp') || (window.parent && window.parent.document ? window.parent.document.querySelector('.stApp') : null);
                var runningIcon = doc.querySelector('[data-testid="stStatusWidgetRunningIcon"]') || (window.parent && window.parent.document ? window.parent.document.querySelector('[data-testid="stStatusWidgetRunningIcon"]') : null);
                
                var isRunning = false;
                if (runningIcon) {
                    isRunning = true;
                } else if (rootApp && rootApp.getAttribute('data-test-script-state') === 'running') {
                    isRunning = true;
                }

                if (isRunning) {
                    wasRunning = true;
                }

                var elapsed = Date.now() - startTime;
                if (wasRunning && !isRunning && elapsed > 400) {
                    clearInterval(checkIdleInterval);
                    hideActionOverlay();
                }
            }, 200);

            // Sicherheits-Timeout (Fallback): Mindestens 35 Sekunden für längere KI-Generierungen und Feed-Aktualisierungen
            setTimeout(function() {
                clearInterval(checkIdleInterval);
                hideActionOverlay();
            }, 35000);
        }
        window._newsBotShowActionOverlay = showActionOverlay;

        // Auto-hide immediately upon any script execution / re-render
        hideActionOverlay();
        setTimeout(hideActionOverlay, 80);
        setTimeout(hideActionOverlay, 300);
        setTimeout(hideActionOverlay, 800);

        // Escape key fallback
        document.addEventListener("keydown", function(e) {
            if (e.key === "Escape" || e.keyCode === 27) {
                hideActionOverlay();
            }
        });

        function handleClick(e) {
            var btn = e.target && e.target.closest ? e.target.closest("button") : null;
            if (!btn) return;
            if (btn.classList.contains("disabled-nav-btn")) return;

            var keyHolder = btn.closest("[class*='st-key-']");
            var keyClass = keyHolder ? keyHolder.className : "";
            var btnText = (btn.innerText || "").trim().toLowerCase();

            if (keyClass.indexOf("top_save_sources_btn") !== -1 || btnText.indexOf("jetzt sichern") !== -1 || btnText.indexOf("speichern") !== -1) {
                showActionOverlay("💾 Sichere Feeds & Einstellungen...", "Synchronisiere mit Konfiguration & GitHub...");
            } else if (keyClass.indexOf("top_discard_sources_btn") !== -1 || btnText.indexOf("verwerfen") !== -1) {
                showActionOverlay("↩️ Verwerfe Änderungen...", "Setze Entwürfe auf gespeicherten Stand zurück...");
            } else if (keyClass.indexOf("btn_save_feed_") !== -1 || btnText.indexOf("im entwurf merken") !== -1 || btnText.indexOf("entwurf merken") !== -1) {
                showActionOverlay("✏️ Merke Feed-Änderungen...", "Übernehme Feed in den Arbeitsentwurf...");
            } else if (keyClass.indexOf("btn_apply_settings") !== -1 || btnText.indexOf("einstellungen im entwurf übernehmen") !== -1) {
                showActionOverlay("⚙️ Übernehme Einstellungen...", "Aktualisiere Einstellungen im Arbeitsentwurf...");
            } else if (keyClass.indexOf("btn_generate_briefing") !== -1 || btnText.indexOf("neues briefing generieren") !== -1) {
                showActionOverlay("🧠 Generiere KI-Briefing mit Gemini...", "Analysiere Artikel und erstelle Zusammenfassung...");
            } else if (keyClass.indexOf("sb_btn_refresh_feeds") !== -1 || btnText.indexOf("feeds neu laden") !== -1) {
                showActionOverlay("🔄 Lese RSS-Feeds ein...", "Lade Feeds live und aktualisiere Datenbank...");
            } else if (keyClass.indexOf("btn_refresh_rss") !== -1 || btnText.indexOf("feeds neu generieren") !== -1) {
                showActionOverlay("📡 Generiere RSS-Feeds neu...", "Erstelle XML-Dateien für Feedly & Reader...");
            } else if (keyClass.indexOf("btn_push_rss_cdn") !== -1 || btnText.indexOf("zu github & cdn pushen") !== -1) {
                showActionOverlay("🚀 Pushe Feeds zu GitHub & CDN...", "Synchronisiere Feeds mit GitHub Actions & CDN...");
            } else if (keyClass.indexOf("btn_add_cat") !== -1 || btnText.indexOf("kategorie hinzufügen") !== -1) {
                showActionOverlay("📁 Füge Kategorie hinzu...", "Kategorie wird im Entwurf angelegt...");
            } else if (keyClass.indexOf("btn_ren_cat") !== -1 || btnText.indexOf("umbenennen") !== -1) {
                showActionOverlay("✏️ Benenne Kategorie um...", "Kategorie wird im Entwurf umbenannt...");
            } else if (keyClass.indexOf("btn_submit_new_feed") !== -1 || btnText.indexOf("feed hinzufügen") !== -1) {
                showActionOverlay("➕ Füge Feed hinzu...", "Feed wird im Entwurf registriert...");
            } else if (keyClass.indexOf("btn_save_ki_prompts") !== -1 || btnText.indexOf("prompts in prompts.yaml speichern") !== -1 || btnText.indexOf("prompts in sources.yaml speichern") !== -1) {
                showActionOverlay("💾 Speichere KI-Prompts...", "Prompts werden in prompts.yaml gesichert...");
            } else if (keyClass.indexOf("btn_reset_ki_main_prompt") !== -1 || btnText.indexOf("standard-hauptprompt laden") !== -1) {
                showActionOverlay("↩️ Lade Standard-Prompt...", "Setze Prompt auf Werkseinstellung zurück...");
            }
        }

        function handleNoticeClose(e) {
            var target = e.target;
            if (!target) return;
            var closeBtn = target.closest ? target.closest(".notice-close-btn") : null;
            if (!closeBtn && target.classList && target.classList.contains("notice-close-btn")) {
                closeBtn = target;
            }
            if (closeBtn) {
                var notice = closeBtn.closest ? closeBtn.closest(".persistent-dismissible-notice") : null;
                if (!notice && closeBtn.parentElement) {
                    notice = closeBtn.parentElement.closest(".persistent-dismissible-notice");
                }
                if (notice) {
                    var bannerId = notice.getAttribute("id") || notice.getAttribute("data-banner-id");
                    if (bannerId) {
                        try { sessionStorage.setItem(bannerId, "dismissed"); } catch(err) {}
                    }
                    notice.style.setProperty("display", "none", "important");
                    notice.remove();
                }
            }
        }

        document.addEventListener("click", handleNoticeClose, true);
        document.addEventListener("click", handleClick, true);
        try {
            if (window.parent && window.parent.document && window.parent.document !== document) {
                window.parent.document.addEventListener("click", handleNoticeClose, true);
                window.parent.document.addEventListener("click", handleClick, true);
            }
        } catch(e) {}
    })();
    </script>
    """, unsafe_allow_javascript=True)
