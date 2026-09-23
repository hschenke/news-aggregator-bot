import streamlit as st
import sys
import os
from pathlib import Path
from datetime import datetime

# Projekt-Root zum Python-Pfad hinzufügen
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.aggregator import collect_all_news, load_sources
from src.summarizer import summarize_news_with_gemini, get_configured_api_key

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
</style>
""", unsafe_allow_html=True)


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

# --- Main Layout & Data Loading ---
with st.spinner("Lade aktuelle Nachrichten aus den RSS-Feeds..."):
    news_data = get_news_data()
    sources_config = get_sources_config()

# Kennzahlen berechnen
total_categories = len(news_data)
total_articles = sum(len(items) for items in news_data.values())
total_feeds = sum(len(c.get("feeds", [])) for c in sources_config.get("categories", []))

st.title("📰 Daily Executive Briefing")
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
    "⚙️ Quellen & Feeds"
])

# ----------------- TAB 1: KI-Briefing -----------------
with tab1:
    st.subheader("Synthetisiertes KI-Briefing")
    
    col_btn, col_info = st.columns([1, 2])
    with col_btn:
        generate_clicked = st.button("🚀 Neues Briefing generieren", type="primary", use_container_width=True)
    with col_info:
        st.caption("Fasst die relevantesten Artikel aus allen Feeds zusammen und formatiert ein kompaktes Executive Briefing.")

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
        selected_cat = st.selectbox("Nach Kategorie filtern:", category_options)
        
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

# ----------------- TAB 3: Quellen -----------------
with tab3:
    st.subheader("Konfigurierte RSS-Feeds")
    st.write("Diese Quellen werden aktuell in `config/sources.yaml` verwaltet:")

    for cat in sources_config.get("categories", []):
        with st.expander(f"📁 {cat.get('name', 'Unbenannt')} ({len(cat.get('feeds', []))} Feeds)", expanded=True):
            for feed in cat.get("feeds", []):
                st.markdown(f"- **{feed.get('name')}**: [{feed.get('url')}]({feed.get('url')}) *(Max. {feed.get('max_items', 5)} Artikel)*")

    st.markdown("---")
    st.info("💡 **Tipp:** Du kannst neue Feeds oder Kategorien jederzeit einfach in der Datei `config/sources.yaml` ergänzen und auf GitHub committen.")
