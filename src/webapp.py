import streamlit as st
import sys
import os
import hmac
import hashlib
import time
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
)
from src.summarizer import summarize_news_with_gemini, get_configured_api_key

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

# Custom Styling
st.markdown("""
<style>
    .metric-card {
        background-color: var(--secondary-background-color);
        padding: 1rem 1.25rem;
        border-radius: 0.75rem;
        border: 1px solid rgba(128, 128, 128, 0.2);
    }
    .article-card {
        padding: 1rem;
        border-radius: 0.6rem;
        border: 1px solid rgba(128, 128, 128, 0.2);
        margin-bottom: 0.85rem;
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
        margin: 3rem auto;
        padding: 2rem;
        background-color: var(--secondary-background-color);
        border-radius: 1rem;
        border: 1px solid rgba(128, 128, 128, 0.2);
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
</style>
""", unsafe_allow_html=True)


# --- Passwort-Schutz & Login-Cookie ---
def get_configured_app_password() -> str:
    """Liest das App-Passwort aus Umgebungsvariablen oder Streamlit Secrets."""
    pw = os.getenv("APP_PASSWORD")
    if not pw:
        try:
            if hasattr(st, "secrets") and "APP_PASSWORD" in st.secrets:
                pw = str(st.secrets["APP_PASSWORD"])
        except Exception:
            pass
    return (pw or "").strip()


def generate_auth_token(password: str) -> str:
    """Erstellt ein kryptografisch signiertes Authentifizierungs-Token mit Zeitstempel."""
    timestamp = str(int(time.time()))
    sig = hmac.new(password.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{timestamp}:{sig}"


def verify_auth_token(token: str, password: str, max_age_days: int = COOKIE_EXPIRY_DAYS) -> bool:
    """Verifiziert das Authentifizierungs-Token und prüft die Gültigkeitsdauer."""
    if not token or ":" not in token:
        return False
    try:
        timestamp_str, sig = token.split(":", 1)
        expected_sig = hmac.new(password.encode("utf-8"), timestamp_str.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, sig):
            return False
        timestamp = int(timestamp_str)
        if time.time() - timestamp > (86400 * max_age_days):
            return False
        return True
    except Exception:
        return False


def check_password() -> bool:
    """
    Überprüft das App-Passwort:
    1. Bereits in session_state authentifiziert
    2. Gespeicherter Login-Cookie im Browser
    3. Passwort-Eingabe über Formular
    """
    expected_password = get_configured_app_password()
    if not expected_password:
        return True  # Kein Passwort konfiguriert -> freier Zugang

    # 1. Bereits in session_state authentifiziert?
    if st.session_state.get("authenticated", False):
        return True

    # 2. Login-Cookie prüfen (zuerst st.context.cookies aus HTTP Header, dann CookieController)
    token_from_cookie = None
    if hasattr(st, "context") and hasattr(st.context, "cookies"):
        token_from_cookie = st.context.cookies.get(COOKIE_AUTH_NAME)
    if not token_from_cookie and cookie_controller:
        try:
            token_from_cookie = cookie_controller.get(COOKIE_AUTH_NAME)
        except Exception:
            pass

    if token_from_cookie and verify_auth_token(token_from_cookie, expected_password):
        st.session_state["authenticated"] = True
        return True

    # 3. Nicht angemeldet: Login-Formular anzeigen
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
            remember_me = st.checkbox("Angemeldet bleiben (Login-Cookie für 7 Tage)", value=True)
            submit = st.form_submit_button("Anmelden", use_container_width=True, type="primary")

            if submit:
                if password_input == expected_password:
                    st.session_state["authenticated"] = True
                    if remember_me and cookie_controller:
                        try:
                            token = generate_auth_token(expected_password)
                            cookie_controller.set(
                                COOKIE_AUTH_NAME,
                                token,
                                max_age=float(86400 * COOKIE_EXPIRY_DAYS),
                                expires=datetime.now() + timedelta(days=COOKIE_EXPIRY_DAYS),
                                same_site="lax"
                            )
                        except Exception as e:
                            print(f"[Warnung] Cookie konnte nicht gesetzt werden: {e}")
                    st.toast("Erfolgreich angemeldet!", icon="🔓")
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


# --- Sidebar ---
st.sidebar.title("📰 News Bot")
st.sidebar.caption("Autonomer KI-Nachrichten-Kurator")

# API-Key Management
configured_key = get_configured_api_key()
user_api_key = None

if configured_key:
    st.sidebar.success("🟢 Gemini API verbunden", icon="✅")
    user_api_key = configured_key
else:
    st.sidebar.warning("🟡 Kein API-Key hinterlegt", icon="⚠️")
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

# Optional: Logout-Button bei aktivem Passwortschutz
if get_configured_app_password():
    st.sidebar.markdown("---")
    st.sidebar.caption("🔒 Status: Angemeldet")
    if st.sidebar.button("🚪 Abmelden", use_container_width=True):
        st.session_state["authenticated"] = False
        if cookie_controller:
            try:
                cookie_controller.remove(COOKIE_AUTH_NAME)
            except Exception:
                pass
        st.toast("Erfolgreich abgemeldet.", icon="🔒")
        st.rerun()

# --- Main Layout & Data Loading ---
with st.spinner("Lade aktuelle Nachrichten aus den RSS-Feeds..."):
    news_data = get_news_data()
    sources_config = get_sources_config()

# Kennzahlen berechnen
total_categories = len(news_data)
total_articles = sum(len(items) for items in news_data.values())
total_feeds = sum(len(c.get("feeds", [])) for c in sources_config.get("categories", []))

st.title("📰 Daily News Briefing")
st.caption(f"Intelligente Nachrichten-Kuratierung • Aktualisiert: {datetime.now().strftime('%d.%m.%Y, %H:%M Uhr')}")

# KPI Row
col1, col2, col3, col4 = st.columns(4)
col1.metric("📌 Kategorien", total_categories)
col2.metric("📡 Aktive Feeds", total_feeds)
col3.metric("📄 Artikel im Pool", total_articles)
col4.metric("🤖 LLM Engine", selected_model.replace("gemini-", "Gemini "))

st.markdown("---")

# Navigation Tabs
tab1, tab2, tab3 = st.tabs([
    "✨ KI-Tages-Briefing",
    "📋 Alle Artikel durchsuchen",
    "⚙️ Quellen & Feeds verwalten"
])

# ----------------- TAB 1: KI-Briefing -----------------
with tab1:
    st.subheader("Synthetisiertes KI-Briefing")
    
    col_btn, col_info = st.columns([1, 2])
    with col_btn:
        generate_clicked = st.button("🚀 Neues Briefing generieren", type="primary", use_container_width=True)
    with col_info:
        st.caption("Fasst die relevantesten Artikel aus allen Feeds zusammen und formatiert ein kompaktes TL;DR-Briefing.")

    if generate_clicked:
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
        st.info("💡 Klicke auf den Button **'Neues Briefing generieren'**, um dein persönliches KI-Briefing zu erstellen.")

# ----------------- TAB 2: Artikel durchsuchen -----------------
with tab2:
    filter_col1, filter_col2 = st.columns([1, 2])
    
    with filter_col1:
        category_options = ["Alle Kategorien"] + list(news_data.keys())
        default_cat_idx = 0
        qp_cat = st.query_params.get("category", "")
        if qp_cat:
            for idx, c in enumerate(category_options):
                if c.strip().lower() == qp_cat.strip().lower():
                    default_cat_idx = idx
                    break
        selected_cat = st.selectbox("Nach Kategorie filtern:", category_options, index=default_cat_idx)
        
    with filter_col2:
        search_query = st.text_input("🔍 Artikel durchsuchen (Stichwort):", placeholder="z. B. AI, Apple, Wirtschaft...")

    # Artikel filtern
    displayed_count = 0
    for category, items in news_data.items():
        if selected_cat != "Alle Kategorien" and category != selected_cat:
            continue
            
        matching_items = []
        for item in items:
            if search_query:
                q = search_query.lower()
                if q not in item["title"].lower() and q not in item.get("summary", "").lower():
                    continue
            matching_items.append(item)
            
        if not matching_items:
            continue
            
        st.markdown(f"### {category} ({len(matching_items)})")
        cols = st.columns(2)
        
        for idx, item in enumerate(matching_items):
            displayed_count += 1
            with cols[idx % 2]:
                with st.container(border=True):
                    st.markdown(f"**[{item['title']}]({item['link']})**")
                    st.caption(f"Quelle: **{item.get('source', 'Unbekannt')}**")
                    if item.get("summary"):
                        st.write(item["summary"])
                    st.link_button("↗ Zum Originalartikel", item["link"], use_container_width=True)

    if displayed_count == 0:
        st.warning("Keine Artikel gefunden, die den Suchkriterien entsprechen.")

# ----------------- TAB 3: Quellen & Feeds verwalten -----------------
with tab3:
    st.subheader("⚙️ Quellen & Feeds verwalten")
    st.caption("Verwalte deine RSS-Feeds und Einstellungen direkt im Web-Dashboard. Alle Änderungen werden automatisch in `config/sources.yaml` gespeichert.")

    sources_path = get_sources_path()

    # --- GitHub-Sync Statusanzeige ---
    gh_cfg = get_github_sync_config()
    if gh_cfg["token"]:
        st.success(f"🟢 **GitHub-Synchronisation aktiv:** Änderungen werden automatisch als Commit in `{gh_cfg['repo']}` (`{gh_cfg['branch']}`) gespeichert.", icon="🐙")
    else:
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
            3. **Fertig!** Danach spiegelt das Web-Dashboard jede Änderung sofort per Git-Commit in dein GitHub-Repository zurück – und GitHub Actions greift morgens automatisch auf die neuesten Feeds zu!
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
                        success = add_category(cat_clean)
                        if success:
                            st.cache_data.clear()
                            st.toast(f"✅ Kategorie '{cat_clean}' erfolgreich in sources.yaml angelegt!", icon="📁")
                            st.rerun()
                        else:
                            st.warning(f"Kategorie '{cat_clean}' existiert bereits.")

        with subtab_cat2:
            existing_cat_names = [c.get("name", "").strip() for c in sources_config.get("categories", []) if c.get("name")]
            if not existing_cat_names:
                st.info("Noch keine Kategorien vorhanden.")
            else:
                st.write("Wähle eine Kategorie aus, um ihren Namen in `sources.yaml` zu ändern:")
                col_ren_select, col_ren_new, col_ren_btn = st.columns([2, 2, 1], vertical_alignment="bottom")
                with col_ren_select:
                    cat_to_rename = st.selectbox("Kategorie auswählen:", options=existing_cat_names, key="select_cat_to_rename")
                with col_ren_new:
                    new_cat_name_input = st.text_input("Neuer Name:", value=cat_to_rename, key=f"input_ren_cat_{cat_to_rename}")
                with col_ren_btn:
                    if st.button("💾 Umbenennen", type="primary", use_container_width=True, key="btn_rename_cat"):
                        if not new_cat_name_input.strip():
                            st.error("Der neue Name darf nicht leer sein.")
                        elif new_cat_name_input.strip() == cat_to_rename:
                            st.info("Der Name wurde nicht verändert.")
                        else:
                            try:
                                rename_category(cat_to_rename, new_cat_name_input.strip())
                                st.cache_data.clear()
                                st.toast(f"✅ Kategorie in '{new_cat_name_input.strip()}' umbenannt!", icon="✏️")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Fehler beim Umbenennen: {e}")

    # --- Sektion 2: RSS-Feeds verwalten (Neu aufnehmen & Bearbeiten) ---
    with st.expander("📡 RSS-Feeds verwalten (Neu aufnehmen & Bearbeiten)", expanded=True):
        subtab_feed1, subtab_feed2 = st.tabs(["➕ Neuen Feed hinzufügen", "✏️ Bestehenden Feed bearbeiten"])

        # Tab 1: Neuer Feed
        with subtab_feed1:
            existing_categories = [c.get("name", "").strip() for c in sources_config.get("categories", []) if c.get("name")]
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

            col_new3, col_new4 = st.columns([3, 1])
            with col_new3:
                new_feed_url = st.text_input("RSS- oder Atom-Feed URL:", placeholder="https://www.theverge.com/rss/index.xml", key="input_new_feed_url")
            with col_new4:
                new_feed_max = st.number_input(
                    "Max. Artikel:",
                    min_value=1,
                    max_value=50,
                    value=5,
                    step=1,
                    help="Maximale Anzahl der Artikel, die aus diesem Feed geladen werden.",
                    key="input_new_feed_max"
                )

            col_act1, col_act2 = st.columns([1, 2], vertical_alignment="center")
            with col_act1:
                test_clicked = st.button("🔍 Feed-URL testen", use_container_width=True, key="btn_test_new_feed")
            with col_act2:
                add_clicked = st.button("💾 Feed aufnehmen & in sources.yaml speichern", type="primary", use_container_width=True, key="btn_add_new_feed")

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
                            max_items=new_feed_max,
                        )
                        st.cache_data.clear()
                        st.toast(f"✅ Feed '{new_feed_name}' erfolgreich zu '{target_cat_name}' hinzugefügt!", icon="📡")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fehler beim Hinzufügen des Feeds: {e}")

        # Tab 2: Bestehenden Feed bearbeiten (Name, URL, Kategorie, Max. Artikel)
        with subtab_feed2:
            all_feed_options = []
            feed_dict = {}
            for cat in sources_config.get("categories", []):
                cname = cat.get("name", "Allgemein")
                for feed in cat.get("feeds", []):
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
                all_cats = [c.get("name", "").strip() for c in sources_config.get("categories", []) if c.get("name")]

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

                col_e3, col_e4 = st.columns([3, 1])
                with col_e3:
                    edit_furl = st.text_input(
                        "Feed-URL ändern:",
                        value=curr_f.get("url", ""),
                        key=f"top_edit_url_{curr_f.get('url')}"
                    )
                with col_e4:
                    edit_fmax = st.number_input(
                        "Max. Artikel:",
                        min_value=1,
                        max_value=50,
                        value=int(curr_f.get("max_items", 5)),
                        step=1,
                        key=f"top_edit_max_{curr_f.get('url')}"
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
                    if st.button("💾 Änderungen in sources.yaml speichern", type="primary", use_container_width=True, key=f"top_save_{curr_f.get('url')}"):
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
                                    new_max_items=edit_fmax,
                                    new_category=edit_fcat.strip()
                                )
                                st.cache_data.clear()
                                st.toast(f"✅ Feed '{edit_fname}' erfolgreich aktualisiert!", icon="💾")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Fehler beim Speichern: {e}")
                with col_ebtn3:
                    with st.popover("🗑️ Löschen", use_container_width=True):
                        st.markdown(f"Feed **'{curr_f.get('name')}'** wirklich entfernen?")
                        if st.button("Bestätigen", key=f"top_del_{curr_f.get('url')}", type="primary", use_container_width=True):
                            delete_feed(curr_cname, curr_f.get("url"))
                            st.cache_data.clear()
                            st.toast(f"🗑️ Feed '{curr_f.get('name')}' entfernt.", icon="🗑️")
                            st.rerun()

    st.markdown("---")

    # --- Sektion 3: Aktive Feeds & Quellen bearbeiten / löschen ---
    st.markdown("### 📋 Aktive Feeds nach Kategorien")
    st.caption("Hier kannst du für jeden Feed die maximale Anzahl der Artikel festlegen, Feeds löschen oder deren Details bearbeiten.")

    categories = sources_config.get("categories", [])
    if not categories:
        st.info("Es sind aktuell keine Kategorien in sources.yaml hinterlegt.")

    for cat_idx, cat in enumerate(categories):
        cat_name = cat.get("name", "Allgemein")
        feeds = cat.get("feeds", [])

        with st.expander(f"📁 {cat_name} ({len(feeds)} Feeds)", expanded=True):
            # Kategorie Header Actions
            col_cat_info, col_cat_del = st.columns([5, 1], vertical_alignment="center")
            with col_cat_info:
                st.caption(f"Kategorie: **{cat_name}** • {len(feeds)} konfigurierte Feeds")
            with col_cat_del:
                with st.popover("🗑️ Kategorie löschen", use_container_width=True):
                    st.markdown(f"Kategorie **'{cat_name}'** samt aller Feeds wirklich löschen?")
                    if st.button("Kategorie löschen", key=f"del_cat_{cat_idx}", type="primary", use_container_width=True):
                        delete_category(cat_name)
                        st.cache_data.clear()
                        st.toast(f"🗑️ Kategorie '{cat_name}' gelöscht.", icon="🗑️")
                        st.rerun()

            if not feeds:
                st.info(f"💡 In der Kategorie '{cat_name}' sind noch keine Feeds hinterlegt. Du kannst oben einen neuen Feed hinzufügen oder diese Kategorie rechts oben löschen.")
            else:
                for feed_idx, feed in enumerate(feeds):
                    f_name = feed.get("name", "Unbenannt")
                    f_url = feed.get("url", "")
                    f_max = int(feed.get("max_items", 5))

                    with st.container(border=True):
                        col_top1, col_top2 = st.columns([4, 2], vertical_alignment="center")
                        with col_top1:
                            st.markdown(f"**{f_name}**")
                            st.caption(f"🔗 [{f_url}]({f_url})")

                        col_f_max, col_f_save, col_f_del = st.columns([2, 1, 1], vertical_alignment="bottom")
                        with col_f_max:
                            current_max_input = st.number_input(
                                "Max. Artikel:",
                                min_value=1,
                                max_value=50,
                                value=f_max,
                                step=1,
                                key=f"feed_max_{cat_idx}_{feed_idx}",
                                help="Maximale Anzahl der Artikel, die aus diesem Feed geladen werden."
                            )
                        with col_f_save:
                            if st.button("💾 Speichern", key=f"feed_save_{cat_idx}_{feed_idx}", use_container_width=True):
                                update_feed(cat_name, f_url, new_max_items=current_max_input)
                                st.cache_data.clear()
                                st.toast(f"✅ Max. Artikel für '{f_name}' auf {current_max_input} aktualisiert!", icon="💾")
                                st.rerun()
                        with col_f_del:
                            with st.popover("🗑️ Löschen", use_container_width=True):
                                st.markdown(f"Feed **'{f_name}'** wirklich entfernen?")
                                if st.button("Bestätigen", key=f"feed_del_conf_{cat_idx}_{feed_idx}", type="primary", use_container_width=True):
                                    delete_feed(cat_name, f_url)
                                    st.cache_data.clear()
                                    st.toast(f"🗑️ Feed '{f_name}' entfernt.", icon="🗑️")
                                    st.rerun()

                        with st.expander("🛠️ Details & URL bearbeiten / Feed testen", expanded=False):
                            col_ed1, col_ed2 = st.columns(2)
                            with col_ed1:
                                edit_name_val = st.text_input("Name ändern:", value=f_name, key=f"edit_name_{cat_idx}_{feed_idx}")
                            with col_ed2:
                                edit_url_val = st.text_input("URL ändern:", value=f_url, key=f"edit_url_{cat_idx}_{feed_idx}")

                            col_t_btn, col_s_btn = st.columns(2)
                            with col_t_btn:
                                if st.button("🔍 Feed testen", key=f"btn_test_{cat_idx}_{feed_idx}", use_container_width=True):
                                    t_res = test_feed_connection(edit_url_val.strip())
                                    if t_res["success"]:
                                        st.success(f"✅ Erreichbar: '{t_res['title']}' ({t_res['item_count']} Einträge gefunden)")
                                    else:
                                        st.error(f"❌ Fehler: {t_res['error']}")
                            with col_s_btn:
                                if st.button("💾 Alle Details speichern", key=f"btn_save_all_{cat_idx}_{feed_idx}", type="primary", use_container_width=True):
                                    update_feed(cat_name, f_url, new_name=edit_name_val, new_url=edit_url_val, new_max_items=current_max_input)
                                    st.cache_data.clear()
                                    st.toast("✅ Feed-Details aktualisiert!", icon="💾")
                                    st.rerun()

    st.markdown("---")

    # --- Sektion 4: Globale Einstellungen ---
    with st.expander("⚙️ Globale Einstellungen (sources.yaml)", expanded=False):
        current_settings = sources_config.get("settings", {})
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            setting_max_cat = st.number_input(
                "Max. Artikel pro Kategorie (Briefing):",
                min_value=1,
                max_value=20,
                value=int(current_settings.get("max_articles_per_category", 4)),
                step=1,
                help="Steuert, wie viele Top-Themen pro Kategorie im KI-Briefing erscheinen."
            )
        with col_s2:
            current_lang = current_settings.get("language", "de")
            lang_options = ["de", "en", "fr", "es"]
            lang_idx = lang_options.index(current_lang) if current_lang in lang_options else 0
            setting_lang = st.selectbox("Sprache für Zusammenfassung:", options=lang_options, index=lang_idx)
        with col_s3:
            current_style = current_settings.get("summary_style", "tldr")
            style_options = ["tldr", "executive_bullet_points", "bullet_points", "narrative"]
            style_idx = style_options.index(current_style) if current_style in style_options else 0
            setting_style = st.selectbox("Briefing-Stil:", options=style_options, index=style_idx)

        default_app_url = current_settings.get("streamlit_app_url", os.getenv("STREAMLIT_APP_URL", "https://news-aggregator-bot.streamlit.app"))
        setting_app_url = st.text_input(
            "Streamlit App URL:",
            value=default_app_url,
            help="Basis-URL dieser Streamlit-App (wird in den E-Mail-Briefings für jede Kategorie verlinkt)."
        )

        if st.button("💾 Globale Einstellungen in sources.yaml speichern", type="primary"):
            update_settings({
                "max_articles_per_category": setting_max_cat,
                "language": setting_lang,
                "summary_style": setting_style,
                "streamlit_app_url": setting_app_url.strip(),
            })
            st.cache_data.clear()
            st.toast("✅ Globale Einstellungen in sources.yaml gespeichert!", icon="💾")
            st.rerun()

    # --- Sektion 5: Live-Vorschau der sources.yaml Datei ---
    with st.expander("📄 Live-Vorschau: config/sources.yaml", expanded=False):
        try:
            with open(sources_path, "r", encoding="utf-8") as f:
                yaml_raw = f.read()
            st.code(yaml_raw, language="yaml")
            col_v1, col_v2 = st.columns([1, 1])
            with col_v1:
                st.download_button(
                    "📥 sources.yaml herunterladen",
                    data=yaml_raw,
                    file_name="sources.yaml",
                    mime="text/yaml",
                    use_container_width=True
                )
            with col_v2:
                if gh_cfg["token"]:
                    if st.button("🐙 Jetzt manuell zu GitHub committen", use_container_width=True):
                        with st.spinner("Pushe zu GitHub..."):
                            sync_res = sync_sources_to_github()
                            if sync_res["success"]:
                                st.success("✅ Erfolgreich zu GitHub synchronisiert!")
                                st.toast("✅ Zu GitHub gepusht!", icon="🐙")
                            else:
                                st.error(f"❌ Fehler: {sync_res['error']}")
        except Exception as e:
            st.error(f"Konnte Datei nicht lesen: {e}")

