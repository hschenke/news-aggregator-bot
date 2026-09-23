import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.aggregator import collect_all_news
from src.summarizer import summarize_news_with_gemini

st.set_page_config(
    page_title="News Aggregator Bot",
    page_icon="📰",
    layout="wide",
)

st.title("📰 News Aggregator Bot")
st.caption(f"Dein persönliches AI-Briefing & Dashboard • Stand: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

# Sidebar Controls
st.sidebar.header("⚙️ Steuerung")
if st.sidebar.button("🔄 News jetzt aktualisieren", use_container_width=True):
    st.cache_data.clear()

st.sidebar.markdown("---")
st.sidebar.markdown("""
**Quellen & Konfiguration:**
- Feeds werden aus `config/sources.yaml` gelesen.
- KI-Zusammenfassung nutzt Google Gemini.
""")

@st.cache_data(ttl=3600)  # 1 Stunde Zwischenspeicher
def get_news_data():
    return collect_all_news()

with st.spinner("Lade aktuelle News..."):
    news_data = get_news_data()

tab1, tab2 = st.tabs(["✨ KI-Briefing", "📋 Alle Artikel & Feeds"])

with tab1:
    st.subheader("Tages-Zusammenfassung")
    if st.button("🚀 KI-Briefing neu generieren", type="primary"):
        with st.spinner("Gemini analysiert und fasst Nachrichten zusammen..."):
            ai_summary = summarize_news_with_gemini(news_data)
            st.session_state["cached_summary"] = ai_summary

    if "cached_summary" in st.session_state:
        st.markdown(st.session_state["cached_summary"])
    else:
        st.info("Klicke auf den Button oben, um ein frisches KI-Briefing zu erstellen.")

with tab2:
    for category, items in news_data.items():
        st.subheader(f"📌 {category} ({len(items)} Artikel)")
        cols = st.columns(2)
        for idx, item in enumerate(items):
            with cols[idx % 2]:
                with st.container(border=True):
                    st.markdown(f"**[{item['title']}]({item['link']})**")
                    st.caption(f"Quelle: {item.get('source', 'Unbekannt')}")
                    if item.get("summary"):
                        st.write(item["summary"])
