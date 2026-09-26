import streamlit as st
import sys
import os
import hmac
import hashlib
import time
import copy
from pathlib import Path
from datetime import datetime, timedelta

# Projekt-Root zum Python-Pfad hinzufügen
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

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
)
from src.summarizer import summarize_news_with_gemini, get_configured_api_key, get_streamlit_app_url
from src.rss_generator import export_all_rss_feeds

try:
    from streamlit_cookies_controller import CookieController
    cookie_controller = CookieController(key="news_bot_auth_cookie_ctrl")
except Exception:
    cookie_controller = None

COOKIE_AUTH_NAME = "news_bot_session"
COOKIE_EXPIRY_DAYS = 7

# Page Configuration
st.set_page_config(
    page_title="News Aggregator Bot | AI Briefing",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling (Kompakt & Mobile-optimiert)
st.markdown("""
<style>
    /* Haupt-Container kompakter auf Desktop & Mobile */
    .block-container {
        padding-top: 1.4rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.25rem !important;
        padding-right: 1.25rem !important;
        max-width: 1250px;
    }
    @media (max-width: 768px) {
        .block-container {
            padding-top: 0.75rem !important;
            padding-bottom: 1.5rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
        h1 {
            font-size: 1.4rem !important;
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
    """Führt Hilfsskripte (z. B. Cookie/Storage-Sync) modern über st.iframe oder Fallback aus."""
    html_wrapper = f"<script>{js_code}</script>"
    if hasattr(st, "iframe"):
        st.iframe(html_wrapper, height=1, width=1)
    elif hasattr(st, "components") and hasattr(st.components, "v1"):
        st.components.v1.html(html_wrapper, height=0, width=0)


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
                    st.toast("Erfolgreich als Admin angemeldet!", icon="🔓")
                    st.rerun()
                else:
                    role = get_auth_role(password_input, expected_password)
                    if role == ROLE_READONLY:
                        st.session_state["authenticated"] = True
                        st.session_state["auth_role"] = ROLE_READONLY
                        st.toast("Erfolgreich im Lese-Modus angemeldet!", icon="👁️")
                        st.rerun()
                    else:
                        st.error("❌ Falsches Passwort. Bitte erneut versuchen.")

    return False


if not check_password():
    st.stop()


# --- Caching Data Loading ---
@st.cache_data(ttl=1800, show_spinner=False)  # 30 Minuten Cache
def get_news_data():
    return collect_all_news()

@st.cache_data(ttl=3600, show_spinner=False)
def get_sources_config():
    try:
        return load_sources()
    except Exception:
        return {}


# Gespeicherten Stand laden und Arbeitsentwurf im session_state verwalten
saved_sources_config = get_sources_config()
if "working_sources_config" not in st.session_state:
    st.session_state["working_sources_config"] = copy.deepcopy(saved_sources_config)

working_config = st.session_state["working_sources_config"]

def harvest_global_settings():
    """Übernimmt ggf. im Formular eingetragene globale Einstellungen in den Arbeitsentwurf."""
    settings = st.session_state["working_sources_config"].setdefault("settings", {})
    settings.pop("max_articles_per_category", None)
    if "input_setting_lang" in st.session_state:
        settings["language"] = str(st.session_state["input_setting_lang"])
    if "input_setting_style" in st.session_state:
        settings["summary_style"] = str(st.session_state["input_setting_style"])
    if "input_setting_app_url" in st.session_state:
        settings["streamlit_app_url"] = str(st.session_state["input_setting_app_url"]).strip()

def perform_save_all():
    """Speichert den gesamten Arbeitsentwurf persistent in sources.yaml und synchronisiert mit GitHub."""
    harvest_global_settings()
    cfg_to_save = st.session_state.get("working_sources_config", {})
    try:
        # RSS-Feeds vor dem Push frisch aufbereiten, damit sie sofort aktuell auf GitHub/CDN landen
        try:
            cached_news = get_news_data()
            app_base = cfg_to_save.get("settings", {}).get("streamlit_app_url") or get_streamlit_app_url()
            export_all_rss_feeds(cached_news, config=cfg_to_save, base_url=app_base)
        except Exception as e_rss:
            print(f"[Hinweis] Lokaler RSS-Feed Export vor Save übersprungen: {e_rss}")

        gh_res = save_sources(cfg_to_save, sync_github=True)
        st.cache_data.clear()
        st.session_state["working_sources_config"] = copy.deepcopy(load_sources())
        if gh_res.get("success"):
            st.session_state["save_feedback"] = ("success", "✅ Alle Änderungen erfolgreich in `config/sources.yaml` und auf dem RSS-CDN gespeichert!")
            st.toast("Gespeichert & mit GitHub / CDN synchronisiert!", icon="🚀")
        else:
            err = gh_res.get("error")
            if err and "Kein GITHUB_TOKEN" not in err:
                st.session_state["save_feedback"] = ("warning", f"In `sources.yaml` gespeichert, aber GitHub-Sync fehlgeschlagen: {err}")
            else:
                st.session_state["save_feedback"] = ("success", "✅ Alle Änderungen erfolgreich in `config/sources.yaml` gespeichert!")
                st.toast("In sources.yaml gespeichert!", icon="💾")
        st.rerun()
    except Exception as e:
        st.error(f"❌ Fehler beim Speichern: {e}")

def perform_discard_all():
    """Verwirft alle ungespeicherten Änderungen und setzt auf den Stand der sources.yaml zurück."""
    st.cache_data.clear()
    st.session_state["working_sources_config"] = copy.deepcopy(load_sources())
    for k in list(st.session_state.keys()):
        if k.startswith("edit_name_") or k.startswith("edit_url_") or k.startswith("input_setting_"):
            del st.session_state[k]
    st.toast("↩️ Alle Änderungen verworfen. Gespeicherter Stand wiederhergestellt.", icon="↩️")
    st.rerun()

has_unsaved_changes = (working_config != saved_sources_config)


# --- Sidebar ---
st.sidebar.markdown("<h2 style='margin-top:0.2rem; margin-bottom:0.25rem; font-size:1.35rem;'>📰 News Bot</h2>", unsafe_allow_html=True)

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
    options=["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash"],
    index=0,
    help="Flash-Lite ist ultraschnell & sparsam, Flash bietet mehr Nuancen."
)

st.sidebar.markdown("---")

# Refresh Button
if st.sidebar.button("🔄 Feeds neu laden", use_container_width=True):
    st.cache_data.clear()
    st.toast("Feeds wurden aktualisiert!", icon="📰")
    st.rerun()

# Deep-Link Query-Params säubern, damit URLs sauber bleiben und Defaults nicht überschreiben
for qp_clean in ["category", "feed"]:
    if qp_clean in st.query_params:
        del st.query_params[qp_clean]

is_viewing_rss = bool(st.query_params.get("page") == "rss" or st.query_params.get("tab") == "rss" or st.query_params.get("view") == "rss")

if is_viewing_rss:
    if st.sidebar.button("🏠 Zum Briefing / Dashboard", use_container_width=True, key="sb_btn_to_briefing"):
        for k in ["page", "tab", "view"]:
            if k in st.query_params:
                del st.query_params[k]
        st.rerun()
else:
    if st.sidebar.button("📡 RSS-Feeds abonnieren", use_container_width=True, key="sb_btn_to_rss"):
        st.query_params["page"] = "rss"
        st.rerun()

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
        st.sidebar.success("**Admin (Vollzugriff)**", icon="🛡️")
    else:
        st.sidebar.info("**Lese-Modus (E-Mail)**", icon="👁️")
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
with st.spinner("Lade aktuelle Nachrichten aus den RSS-Feeds..."):
    news_data = get_news_data()

# Kennzahlen berechnen
total_categories = len(news_data)
total_articles = sum(len(items) for items in news_data.values())
total_feeds = sum(len(c.get("feeds", [])) for c in working_config.get("categories", []))

st.title("📰 Daily News Briefing")
st.caption(f"Aktualisiert: {datetime.now().strftime('%d.%m.%Y, %H:%M Uhr')}")

# KPI Row (Kompakt & Mobile-optimiert)
engine_short = selected_model.replace("gemini-", "").replace("-flash-lite", " Flash-Lite").replace("-flash", " Flash")
st.markdown(f"""
<div class="kpi-container">
    <span class="kpi-chip">📌 <strong>{total_categories}</strong> Kategorien</span>
    <span class="kpi-chip">📡 <strong>{total_feeds}</strong> Feeds</span>
    <span class="kpi-chip kpi-pool">📄 <strong>{total_articles}</strong> Artikel im Pool</span>
    <span class="kpi-chip">🤖 <strong>{engine_short}</strong></span>
</div>
""", unsafe_allow_html=True)

# Navigation Tabs
is_viewing_rss = bool(st.query_params.get("page") == "rss" or st.query_params.get("tab") == "rss" or st.query_params.get("view") == "rss")
manage_tab_title = "⚙️ Feeds & Quellen 🔴" if has_unsaved_changes else "⚙️ Feeds & Quellen"

if is_viewing_rss:
    tab_rss, tab_briefing, tab_articles, tab_manage = st.tabs([
        "📡 RSS-Feeds",
        "✨ KI-Briefing",
        "📋 Alle Artikel",
        manage_tab_title
    ])
else:
    tab_briefing, tab_articles, tab_rss, tab_manage = st.tabs([
        "✨ KI-Briefing",
        "📋 Alle Artikel",
        "📡 RSS-Feeds",
        manage_tab_title
    ])

# ----------------- TAB: KI-Briefing -----------------
with tab_briefing:
    st.markdown("<h3 style='margin-top:0.25rem; margin-bottom:0.4rem;'>✨ Synthetisiertes KI-Briefing</h3>", unsafe_allow_html=True)
    
    is_admin = st.session_state.get("auth_role") == ROLE_ADMIN or not get_configured_app_password()
    
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
                        st.error("❌ Falsches Passwort.")
            generate_clicked = st.session_state.pop("trigger_generate", False)

    with col_info:
        if is_admin:
            st.caption("Fasst die relevantesten Artikel aus allen Feeds zusammen und formatiert ein kompaktes Briefing.")
        else:
            st.caption("👁️ **Lese-Modus:** Du kannst das bestehende Briefing lesen. Das Anstoßen einer neuen KI-Generierung erfordert Admin-Rechte.")

    if generate_clicked:
        if not is_admin:
            st.warning("⚠️ Keine Berechtigung zur Generierung. Bitte als Admin anmelden.")
        else:
            with st.spinner(f"Gemini ({selected_model}) analysiert die Artikel und erstellt das Briefing..."):
                ai_summary = summarize_news_with_gemini(
                    news_data,
                    api_key=user_api_key,
                    model=selected_model
                )
                st.session_state["cached_summary"] = ai_summary
                st.session_state["summary_timestamp"] = datetime.now().strftime("%d.%m.%Y, %H:%M Uhr")

    if "cached_summary" in st.session_state:
        st.markdown(f"*(Erstellt am: {st.session_state.get('summary_timestamp', '')})*")
        st.markdown(st.session_state["cached_summary"])
        
        st.markdown("---")
        # Download-Möglichkeit als Markdown
        st.download_button(
            label="📥 Briefing als Markdown herunterladen",
            data=st.session_state["cached_summary"],
            file_name=f"news_briefing_{datetime.now().strftime('%Y%m%d')}.md",
            mime="text/markdown",
        )
    else:
        if is_admin:
            st.info("💡 Klicke auf den Button **'Neues Briefing generieren'**, um dein persönliches KI-Briefing zu erstellen.")
        else:
            st.info("💡 Aktuell liegt noch kein generiertes Briefing für diese Sitzung vor. Schalte oben den Admin-Modus frei, um ein neues Briefing mit Gemini zu generieren.")

# ----------------- TAB: Artikel durchsuchen -----------------
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
            try:
                dt = datetime.fromtimestamp(ts)
                return dt.strftime("%d.%m.%Y, %H:%M Uhr")
            except Exception:
                pass
        pub = it.get("published", "") or it.get("updated", "")
        if pub:
            return str(pub)[:30]
        return ""

    # 1. State initialisieren: Default ist IMMER "Alle Kategorien"
    # Eventuell verbliebene Legacy-Keys aufräumen
    for legacy_k in ["articles_selected_cat", "sel_articles_cat_widget"]:
        if legacy_k in st.session_state:
            del st.session_state[legacy_k]

    if "sel_articles_category" not in st.session_state:
        st.session_state["sel_articles_category"] = "Alle Kategorien"
    if "articles_cat_feed_memory" not in st.session_state:
        st.session_state["articles_cat_feed_memory"] = {}
    if "chk_expand_cats" not in st.session_state:
        st.session_state["chk_expand_cats"] = True
    if "chk_expand_feeds" not in st.session_state:
        st.session_state["chk_expand_feeds"] = True

    sorted_all_categories = sorted(list(news_data.keys()), key=lambda x: x.strip().lower())
    category_options = ["Alle Kategorien"] + sorted_all_categories

    if st.session_state["sel_articles_category"] not in category_options:
        st.session_state["sel_articles_category"] = "Alle Kategorien"

    filter_col1, filter_col2, filter_col3 = st.columns([1, 1, 2])

    with filter_col1:
        selected_cat = st.selectbox(
            "Kategorie:",
            options=category_options,
            key="sel_articles_category"
        )

    with filter_col2:
        if selected_cat != "Alle Kategorien":
            cat_items = news_data.get(selected_cat, [])
            available_feeds = sorted(list({item.get("source") for item in cat_items if item.get("source")}), key=lambda x: x.strip().lower())
            feed_options = ["Alle Feeds"] + available_feeds
        else:
            all_feeds = sorted(list({item.get("source") for items in news_data.values() for item in items if item.get("source")}), key=lambda x: x.strip().lower())
            feed_options = ["Alle Feeds"] + all_feeds

        feed_widget_key = f"sel_feed_for_{selected_cat}"
        remembered_feed = st.session_state["articles_cat_feed_memory"].get(selected_cat, "Alle Feeds")
        if remembered_feed not in feed_options:
            remembered_feed = "Alle Feeds"

        if feed_widget_key not in st.session_state or st.session_state[feed_widget_key] not in feed_options:
            st.session_state[feed_widget_key] = remembered_feed

        selected_feed = st.selectbox(
            "Feed / Quelle:",
            options=feed_options,
            key=feed_widget_key
        )
        st.session_state["articles_cat_feed_memory"][selected_cat] = selected_feed

    with filter_col3:
        search_query = st.text_input("🔍 Suche:", placeholder="z. B. AI, Apple, Wirtschaft...")

    col_stat, col_toggles = st.columns([3, 2], vertical_alignment="center")
    with col_toggles:
        c_tog1, c_tog2 = st.columns(2)
        with c_tog1:
            expand_cats = st.checkbox("📂 Kategorien auf", key="chk_expand_cats", help="Alle Kategorien aufklappen")
        with c_tog2:
            expand_feeds = st.checkbox("📡 Feeds auf", key="chk_expand_feeds", help="Alle Feeds innerhalb der Kategorien aufklappen")

    displayed_count = 0
    categories_rendered = 0

    for category in sorted_all_categories:
        if selected_cat != "Alle Kategorien" and category != selected_cat:
            continue

        cat_items = news_data.get(category, [])

        # Artikel filtern nach Feed und Suche
        cat_matching = []
        for item in cat_items:
            if selected_feed != "Alle Feeds" and item.get("source") != selected_feed:
                continue
            if search_query:
                q = search_query.lower()
                if q not in item.get("title", "").lower() and q not in item.get("summary", "").lower():
                    continue
            cat_matching.append(item)

        if not cat_matching:
            continue

        categories_rendered += 1
        # Alle Artikel der Kategorie nach Datum absteigend sortieren
        cat_matching.sort(key=get_article_timestamp, reverse=True)

        cat_is_expanded = (selected_cat != "Alle Kategorien") or expand_cats
        with st.expander(f"📁 **{category}** ({len(cat_matching)} Artikel)", expanded=cat_is_expanded):
            # Innerhalb der Kategorie nach Feed gruppieren
            feeds_dict = {}
            for item in cat_matching:
                src = item.get("source", "Unbekannt")
                feeds_dict.setdefault(src, []).append(item)

            sorted_feed_names = sorted(feeds_dict.keys(), key=lambda x: x.strip().lower())

            for feed_name in sorted_feed_names:
                f_items = feeds_dict[feed_name]
                # Artikel innerhalb des Feeds nach Datum sortieren
                f_items.sort(key=get_article_timestamp, reverse=True)

                feed_is_expanded = (selected_feed != "Alle Feeds") or expand_feeds
                with st.expander(f"📡 **{feed_name}** ({len(f_items)} Artikel)", expanded=feed_is_expanded):
                    cols = st.columns(2)
                    for idx, item in enumerate(f_items):
                        displayed_count += 1
                        with cols[idx % 2]:
                            with st.container(border=True):
                                st.markdown(f"**[{item['title']}]({item['link']})**")
                                pdate = format_article_date(item)
                                pdate_badge = f" • 🕒 {pdate}" if pdate else ""
                                st.caption(f"Quelle: **{item.get('source', 'Unbekannt')}**{pdate_badge}")
                                if item.get("summary"):
                                    st.write(item["summary"])
                                st.link_button("↗ Zum Originalartikel", item["link"], use_container_width=True)

    with col_stat:
        if displayed_count > 0:
            st.caption(f"Zeige **{displayed_count}** Artikel in **{categories_rendered}** Kategorien (chronologisch sortiert)")
        else:
            st.warning("Keine Artikel gefunden, die den Suchkriterien entsprechen.")

# ----------------- TAB: Eigene RSS-Feeds -----------------
with tab_rss:
    st.subheader("📡 Eigene RSS-Feeds abonnieren")
    st.caption("Verwandle deinen News Aggregator Bot in deinen persönlichen RSS-Server! Alle gesammelten Artikel stehen als standardkonforme RSS 2.0 Feeds zur Verfügung.")

    app_base_url = working_config.get("settings", {}).get("streamlit_app_url") or get_streamlit_app_url()
    app_base_url = (app_base_url or "").rstrip("/")

    # Oberer Info- und Aktionsbalken
    st.caption("🚀 **24/7 High-Speed GitHub CDN** • 0s Ladezeit • Standard RSS 2.0 XML")

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
                        st.success("✅ RSS-Feeds erfolgreich zu GitHub & CDN synchronisiert!")
                        st.toast("Feeds zu CDN gepusht!", icon="🚀")
                    else:
                        trig_res = trigger_rss_update_workflow()
                        if trig_res.get("success"):
                            st.info("⚡ GitHub Action 'Update RSS Feeds' wurde angestoßen!")
                            st.toast("GitHub Action gestartet!", icon="⚡")
                        else:
                            st.error(f"❌ Fehler: {push_res.get('error')}")
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

    # 1. Gesamt-Feed (Alle Nachrichten)
    if rss_feed_view_mode in ["Alle Feeds", "Nur Kategorien"]:
        all_info = rss_registry.get("all", {})
        with st.container(border=True):
            col_all_h1, col_all_h2 = st.columns([3, 1], vertical_alignment="center")
            with col_all_h1:
                st.markdown("### 🌟 Alle Nachrichten (Gesamt-Feed)")
                st.write("Enthält alle aggregierten Artikel aus sämtlichen Kategorien und Quellen chronologisch geordnet.")
            with col_all_h2:
                st.metric("Gesamtartikel", all_info.get("item_count", 0))

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

        st.markdown("---")

    # 2. Kategorie-Feeds
    if rss_feed_view_mode in ["Alle Feeds", "Nur Kategorien"]:
        categories_rss = rss_registry.get("categories", [])
        st.markdown(f"### 📁 Feeds nach Themen-Kategorien ({len(categories_rss)})")
        st.write("Abonniere gezielt nur die Themen, die dich interessieren:")

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

        st.markdown("---")

    # 3. Einzel-Feeds nach Quellen
    if rss_feed_view_mode in ["Alle Feeds", "Nur Einzel-Feeds"]:
        feeds_rss = rss_registry.get("feeds", [])
        st.markdown(f"### 📡 Feeds einzelner Quellen ({len(feeds_rss)})")
        st.write("Aufbereitete Feeds für jede spezifische Nachrichtenquelle:")

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

        st.markdown("---")

    # 4. Anleitung für RSS-Reader
    with st.expander("ℹ️ **Anleitung: Wie binde ich diese Feeds in meinen RSS-Reader ein?**", expanded=False):
        all_example_url = rss_registry.get("all", {}).get("url") or "https://cdn.jsdelivr.net/gh/hschenke/news-aggregator-bot@main/static/rss/all.xml"
        st.markdown(f"""
        ### So abonnierst du deine persönlichen Feeds:
        1. **URL kopieren**: Klicke oben im Kasten des gewünschten Feeds auf das Kopier-Icon des Code-Blocks (z. B. `{all_example_url}`).
        2. **RSS-Reader öffnen**: Starte deinen bevorzugten News-Reader (z. B. *NetNewsWire*, *Feedly*, *Apple News*, *Inoreader*, *Thunderbird*, *Outlook* etc.).
        3. **Feed hinzufügen**:
           - **NetNewsWire / Reeder**: Menü `Feed` > `Add Web Feed...` > URL einfügen > `Add`.
           - **Feedly**: In der linken Seitenleiste auf `+` (Follow Sources) klicken > URL einfügen > `Follow`.
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
                        st.error("❌ Falsches Passwort.")

        st.markdown("---")
        with st.expander("👁️ Aktuell konfigurierte Kategorien & Feeds ansehen (Schreibgeschützt)", expanded=True):
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
            st.success(msg, icon="✅")
        elif level == "warning":
            st.warning(msg, icon="⚠️")

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
                                st.toast(f"Kategorie in '{new_cat_name_input.strip()}' umbenannt (noch nicht gespeichert).", icon="✏️")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Fehler beim Umbenennen: {e}")

    # --- Sektion 2: RSS-Feeds verwalten (Neu aufnehmen & Bearbeiten) ---
    with st.expander("📡 RSS-Feeds verwalten (Neu aufnehmen & Bearbeiten)", expanded=True):
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

            col_act1, col_act2 = st.columns([1, 2], vertical_alignment="center")
            with col_act1:
                test_clicked = st.button("🔍 Feed-URL testen", use_container_width=True, key="btn_test_new_feed")
            with col_act2:
                add_clicked = st.button("➕ Feed zur Liste hinzufügen", type="primary", use_container_width=True, key="btn_add_new_feed")

            if test_clicked:
                if not new_feed_url.strip():
                    st.warning("Bitte gib zuerst eine Feed-URL ein.")
                else:
                    with st.spinner("Prüfe Feed-URL..."):
                        test_res = test_feed_connection(new_feed_url)
                        if test_res["success"]:
                            st.success(
                                f"✅ Feed erreichbar: **{test_res['title']}** "
                                f"({test_res['item_count']} Einträge gefunden. Neuester: *'{test_res['latest_title']}'*)"
                            )
                        else:
                            st.error(f"❌ Feed nicht erreichbar oder ungültig: {test_res['error']}")

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
                            config=working_config,
                            save_to_disk=False,
                        )
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
                        options=all_cats,
                        index=cat_index,
                        key=f"top_edit_cat_{curr_f.get('url')}"
                    )

                edit_furl = st.text_input(
                    "Feed-URL ändern:",
                    value=curr_f.get("url", ""),
                    key=f"top_edit_url_{curr_f.get('url')}"
                )

                col_ebtn1, col_ebtn2, col_ebtn3 = st.columns([1, 2, 1], vertical_alignment="center")
                with col_ebtn1:
                    if st.button("🔍 Feed testen", use_container_width=True, key=f"top_test_{curr_f.get('url')}"):
                        with st.spinner("Prüfe Feed-URL..."):
                            t_res = test_feed_connection(edit_furl.strip())
                            if t_res["success"]:
                                st.success(f"✅ Erreichbar: **{t_res['title']}** ({t_res['item_count']} Einträge gefunden)")
                            else:
                                st.error(f"❌ Nicht erreichbar: {t_res['error']}")
                with col_ebtn2:
                    if st.button("✔️ Änderungen übernehmen", type="primary", use_container_width=True, key=f"top_save_{curr_f.get('url')}"):
                        if not edit_fname.strip():
                            st.error("Der Feed-Name darf nicht leer sein.")
                        elif not edit_furl.strip() or not (edit_furl.strip().startswith("http://") or edit_furl.strip().startswith("https://")):
                            st.error("Bitte gib eine gültige URL an.")
                        else:
                            try:
                                update_feed(
                                    category_name=curr_cname,
                                    old_url=curr_f.get("url"),
                                    new_name=edit_fname.strip(),
                                    new_url=edit_furl.strip(),
                                    new_category=edit_fcat.strip(),
                                    config=working_config,
                                    save_to_disk=False,
                                )
                                st.toast(f"Feed '{edit_fname}' aktualisiert (noch nicht gespeichert).", icon="✏️")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Fehler beim Übernehmen: {e}")
                with col_ebtn3:
                    with st.popover("🗑️ Löschen", use_container_width=True):
                        st.markdown(f"Feed **'{curr_f.get('name')}'** wirklich entfernen?")
                        if st.button("Bestätigen", key=f"top_del_{curr_f.get('url')}", type="primary", use_container_width=True):
                            delete_feed(curr_cname, curr_f.get("url"), config=working_config, save_to_disk=False)
                            st.toast(f"Feed '{curr_f.get('name')}' entfernt (noch nicht gespeichert).", icon="🗑️")
                            st.rerun()

    st.markdown("---")

    # --- Sektion 3: Aktive Feeds & Quellen bearbeiten / löschen ---
    st.markdown("### 📋 Aktive Feeds nach Kategorien")
    st.caption("Hier kannst du Feeds verwalten, löschen oder deren Details bearbeiten. Änderungen werden gesammelt.")

    categories = sorted(working_config.get("categories", []), key=lambda c: c.get("name", "").strip().lower())
    if not categories:
        st.info("Es sind aktuell keine Kategorien hinterlegt.")

    for cat_idx, cat in enumerate(categories):
        cat_name = cat.get("name", "Allgemein")
        feeds = sorted(cat.get("feeds", []), key=lambda f: f.get("name", "").strip().lower())

        with st.expander(f"📁 {cat_name} ({len(feeds)} Feeds)", expanded=True):
            # Kategorie Header Actions
            col_cat_info, col_cat_del = st.columns([5, 1], vertical_alignment="center")
            with col_cat_info:
                st.caption(f"Kategorie: **{cat_name}** • {len(feeds)} konfigurierte Feeds")
            with col_cat_del:
                with st.popover("🗑️ Kategorie löschen", use_container_width=True):
                    st.markdown(f"Kategorie **'{cat_name}'** samt aller Feeds wirklich löschen?")
                    if st.button("Kategorie löschen", key=f"del_cat_{cat_idx}", type="primary", use_container_width=True):
                        delete_category(cat_name, config=working_config, save_to_disk=False)
                        st.toast(f"Kategorie '{cat_name}' entfernt (noch nicht gespeichert).", icon="🗑️")
                        st.rerun()

            if not feeds:
                st.info(f"💡 In der Kategorie '{cat_name}' sind noch keine Feeds hinterlegt. Du kannst oben einen neuen Feed hinzufügen oder diese Kategorie löschen.")
            else:
                for feed_idx, feed in enumerate(feeds):
                    f_name = feed.get("name", "Unbenannt")
                    f_url = feed.get("url", "")
                    key_hash = hashlib.md5(f_url.encode("utf-8")).hexdigest()[:8]

                    with st.container(border=True):
                        col_top1, col_top2 = st.columns([5, 1], vertical_alignment="center")
                        with col_top1:
                            st.markdown(f"**{f_name}**")
                            st.caption(f"🔗 [{f_url}]({f_url})")
                        with col_top2:
                            with st.popover("🗑️ Löschen", use_container_width=True):
                                st.markdown(f"Feed **'{f_name}'** wirklich entfernen?")
                                if st.button("Bestätigen", key=f"feed_del_conf_{cat_idx}_{feed_idx}", type="primary", use_container_width=True):
                                    delete_feed(cat_name, f_url, config=working_config, save_to_disk=False)
                                    st.toast(f"Feed '{f_name}' entfernt (noch nicht gespeichert).", icon="🗑️")
                                    st.rerun()

                        with st.expander("🛠️ Details & URL bearbeiten / Feed testen", expanded=False):
                            col_ed1, col_ed2 = st.columns(2)
                            with col_ed1:
                                edit_name_val = st.text_input("Name ändern:", value=f_name, key=f"edit_name_{key_hash}")
                            with col_ed2:
                                edit_url_val = st.text_input("URL ändern:", value=f_url, key=f"edit_url_{key_hash}")

                            col_t_btn, col_s_btn = st.columns(2)
                            with col_t_btn:
                                if st.button("🔍 Feed testen", key=f"btn_test_{key_hash}", use_container_width=True):
                                    t_res = test_feed_connection(edit_url_val.strip())
                                    if t_res["success"]:
                                        st.success(f"✅ Erreichbar: '{t_res['title']}' ({t_res['item_count']} Einträge gefunden)")
                                    else:
                                        st.error(f"❌ Fehler: {t_res['error']}")
                            with col_s_btn:
                                if st.button("✔️ Details übernehmen", key=f"btn_save_all_{key_hash}", type="primary", use_container_width=True):
                                    update_feed(
                                        cat_name,
                                        f_url,
                                        new_name=edit_name_val.strip(),
                                        new_url=edit_url_val.strip(),
                                        config=working_config,
                                        save_to_disk=False
                                    )
                                    st.toast("Feed-Details übernommen (noch nicht gespeichert).", icon="✏️")
                                    st.rerun()

    st.markdown("---")

    # --- Sektion 4: Globale Einstellungen ---
    with st.expander("⚙️ Globale Einstellungen", expanded=False):
        current_settings = working_config.get("settings", {})
        col_s1, col_s2 = st.columns(2)
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

        default_app_url = current_settings.get("streamlit_app_url", os.getenv("STREAMLIT_APP_URL", "https://news-aggregator-bot-sdfgedfwcu7yr9gzikr8q8.streamlit.app"))
        setting_app_url = st.text_input(
            "Streamlit App URL:",
            value=default_app_url,
            key="input_setting_app_url",
            help="Basis-URL dieser Streamlit-App (wird in den E-Mail-Briefings für jede Kategorie verlinkt)."
        )

        if st.button("✔️ Globale Einstellungen übernehmen", type="secondary", use_container_width=True, key="btn_apply_global_settings"):
            new_settings_dict = {
                "language": setting_lang,
                "summary_style": setting_style,
                "streamlit_app_url": setting_app_url.strip(),
            }
            update_settings(new_settings_dict, config=working_config, save_to_disk=False)
            st.toast("Globale Einstellungen übernommen (noch nicht gespeichert).", icon="⚙️")
            st.rerun()

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
                                st.success("✅ Erfolgreich zu GitHub synchronisiert!")
                                st.toast("Zu GitHub gepusht!", icon="🐙")
                            else:
                                st.error(f"❌ Fehler: {sync_res['error']}")
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

