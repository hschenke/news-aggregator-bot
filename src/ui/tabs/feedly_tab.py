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

    if st.session_state.get("feedly_notice"):
        col_fn_t, col_fn_b = st.columns([12, 1], vertical_alignment="center")
        with col_fn_t:
            st.success(f"📡 {st.session_state['feedly_notice']}")
        with col_fn_b:
            if st.button("✖", key="btn_dismiss_feedly_notice", help="Hinweis schließen"):
                st.session_state.pop("feedly_notice", None)
                st.rerun()

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
        is_refreshing_rss = bool(st.session_state.get("is_refreshing_rss", False))
        is_pushing_rss = bool(st.session_state.get("is_pushing_rss", False))
        any_busy = is_refreshing_rss or is_pushing_rss

        col_act1, col_act2 = st.columns([1, 1])
        with col_act1:
            if st.button("🔄 Feeds neu generieren", key="btn_refresh_rss", use_container_width=True, disabled=any_busy):
                st.session_state["is_refreshing_rss"] = True
                with st.spinner("Generiere alle RSS-Feeds neu..."):
                    st.cache_data.clear()
                    st.session_state["is_refreshing_rss"] = False
                    st.session_state["feedly_notice"] = "Feeds wurden erfolgreich generiert & aktualisiert!"
                    st.rerun()
        with col_act2:
            if st.button("🚀 Zu GitHub & CDN pushen", key="btn_push_rss_cdn", use_container_width=True, disabled=any_busy):
                st.session_state["is_pushing_rss"] = True
                with st.spinner("Pushe RSS-Feeds zu GitHub & jsDelivr CDN..."):
                    push_res = sync_sources_to_github(
                        config_dict=working_config,
                        commit_message="chore(rss): update RSS feeds via web dashboard",
                        include_rss_feeds=True,
                    )
                    st.session_state["is_pushing_rss"] = False
                    if push_res.get("success"):
                        st.session_state["feedly_notice"] = "RSS-Feeds erfolgreich zu GitHub & CDN synchronisiert!"
                        st.success("RSS-Feeds erfolgreich zu GitHub & CDN synchronisiert!")
                    else:
                        trig_res = trigger_rss_update_workflow()
                        if trig_res.get("success"):
                            st.session_state["feedly_notice"] = "GitHub Action 'Update RSS Feeds' wurde angestoßen!"
                            st.info("GitHub Action 'Update RSS Feeds' wurde angestoßen!")
                        else:
                            st.error(f"Fehler: {push_res.get('error')}")

    st.markdown("---")

    # 1. Gesamt-Feed (Alle Nachrichten)
    all_info = rss_registry.get("all", {})
    all_url = all_info.get("url") or all_info.get("cdn_url", "")
    all_count = all_info.get("item_count", sum(len(v) for v in news_data.values()))

    with st.container(border=True):
        st.markdown(f"#### 🌟 Gesamt-Feed (Alle Nachrichten) — **{all_count}** Artikel")
        st.caption("Enthält alle aggregierten Nachrichten der letzten 24 Stunden chronologisch sortiert.")
        if all_url:
            st.code(all_url, language="text")
            st.link_button("↗️ Im Browser öffnen", all_url, use_container_width=True)

    # 2. KI-Briefing Feed
    briefing_info = rss_registry.get("briefing", {})
    briefing_url = briefing_info.get("url") or briefing_info.get("cdn_url", "")
    briefing_count = briefing_info.get("item_count", 1)

    with st.container(border=True):
        st.markdown(f"#### 🧠 KI-Briefing Feed — **{briefing_count}** Eintrag / Top-Meldungen")
        st.caption("Das kuratierte Tages-Briefing und die Top-Empfehlungen als eigenständiger Feed.")
        if briefing_url:
            st.code(briefing_url, language="text")
            st.link_button("↗️ Im Browser öffnen", briefing_url, use_container_width=True)
