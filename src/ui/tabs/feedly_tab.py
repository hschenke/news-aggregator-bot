"""
Feedly & RSS Exposure tab module for News Aggregator Bot UI.
Provides streamlined access to the two core RSS feeds:
1. Gesamt-Feed (all.xml)
2. KI-Briefing Feed (briefing.xml)
"""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from src.summarizer import get_streamlit_app_url
from src.aggregator import (
    sync_sources_to_github,
    trigger_rss_update_workflow,
)
from src.rss_generator import export_all_rss_feeds

logger = logging.getLogger(__name__)


def render_feedly_tab(
    news_data: dict[str, list[dict[str, Any]]],
    working_config: dict[str, Any],
    is_admin: bool,
) -> None:
    """Renders the Feedly RSS tab with strictly the 2 core feeds (Gesamt and KI Briefing)."""
    st.subheader("📡 RSS Feeds")
    st.caption(
        "Standardkonforme RSS 2.0 XML-Feeds für Feedly, Inoreader, NetNewsWire oder jeden beliebigen RSS-Reader."
    )

    app_base_url = (
        working_config.get("settings", {}).get("streamlit_app_url")
        or get_streamlit_app_url()
        or ""
    ).rstrip("/")

    # Export / build feeds
    briefing_md = st.session_state.get("cached_summary", "")
    rss_registry = export_all_rss_feeds(
        news_data,
        config=working_config,
        base_url=app_base_url,
        briefing_markdown=briefing_md,
    )

    # Admin controls
    if is_admin:
        col_act1, col_act2 = st.columns([1, 1])
        with col_act1:
            if st.button("🔄 Feeds neu generieren", key="btn_refresh_rss", use_container_width=True):
                st.cache_data.clear()
                st.toast("Feeds wurden frisch generiert!", icon="📡")
                st.rerun()
        with col_act2:
            if st.button("🚀 Zu GitHub & CDN pushen", key="btn_push_rss_cdn", use_container_width=True):
                with st.spinner("Pushe RSS-Feeds zu GitHub & jsDelivr CDN..."):
                    push_res = sync_sources_to_github(
                        config_dict=working_config,
                        commit_message="chore(rss): update RSS feeds via web dashboard",
                        include_rss_feeds=True,
                    )
                    if push_res.get("success"):
                        st.success("RSS-Feeds erfolgreich zu GitHub & CDN synchronisiert!")
                        st.toast("Feeds zu CDN gepusht!", icon="🚀")
                    else:
                        trig_res = trigger_rss_update_workflow()
                        if trig_res.get("success"):
                            st.info("GitHub Action 'Update RSS Feeds' wurde angestoßen!")
                            st.toast("GitHub Action gestartet!", icon="⚡")
                        else:
                            st.error(f"Fehler: {push_res.get('error')}")

    st.markdown("---")

    # 1. Gesamt-Feed (Alle Nachrichten)
    all_info = rss_registry.get("all", {})
    all_url = all_info.get("url") or all_info.get("cdn_url", "")
    all_count = all_info.get("item_count", sum(len(v) for v in news_data.values()))

    with st.container(border=True):
        st.markdown(f"#### 🌟 Gesamt-Feed (Alle Nachrichten) — `{all_count}` Artikel")
        st.caption("Enthält alle aggregierten Nachrichten der letzten 24 Stunden chronologisch sortiert.")
        if all_url:
            st.code(all_url, language="text")
            col_b1, col_b2, col_b3 = st.columns(3)
            with col_b1:
                st.link_button("↗️ Im Browser öffnen", all_url, use_container_width=True)
            with col_b2:
                st.download_button(
                    "📥 XML herunterladen",
                    data=all_info.get("xml_preview", ""),
                    file_name="news_all.xml",
                    mime="application/rss+xml",
                    use_container_width=True,
                )
            with col_b3:
                feedly_sub_url = f"https://feedly.com/i/subscription/feed/{all_url}"
                st.link_button("➕ Zu Feedly hinzufügen", feedly_sub_url, use_container_width=True)

    # 2. KI-Briefing Feed
    briefing_info = rss_registry.get("briefing", {})
    briefing_url = briefing_info.get("url") or briefing_info.get("cdn_url", "")
    briefing_count = briefing_info.get("item_count", 1)

    with st.container(border=True):
        st.markdown(f"#### 🧠 KI-Briefing Feed — `{briefing_count}` Eintrag / Top-Meldungen")
        st.caption("Das kuratierte Tages-Briefing und die Top-Empfehlungen als eigenständiger Feed.")
        if briefing_url:
            st.code(briefing_url, language="text")
            col_k1, col_k2, col_k3 = st.columns(3)
            with col_k1:
                st.link_button("↗️ Im Browser öffnen", briefing_url, use_container_width=True)
            with col_k2:
                st.download_button(
                    "📥 XML herunterladen",
                    data=briefing_info.get("xml_preview", ""),
                    file_name="briefing.xml",
                    mime="application/rss+xml",
                    use_container_width=True,
                )
            with col_k3:
                feedly_sub_url = f"https://feedly.com/i/subscription/feed/{briefing_url}"
                st.link_button("➕ Zu Feedly hinzufügen", feedly_sub_url, use_container_width=True)
