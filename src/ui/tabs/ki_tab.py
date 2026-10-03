"""
KI Briefing tab module for News Aggregator Bot UI.
Renders AI-curated daily briefings and provides generation triggers for administrators.
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any

import streamlit as st

from src.summarizer import summarize_news_with_gemini
from src.rss_generator import export_briefing_rss
from src.storage import get_storage

logger = logging.getLogger(__name__)


def render_ki_tab(
    news_data: dict[str, list[dict[str, Any]]],
    is_admin: bool,
) -> None:
    """Renders the AI briefing tab."""
    st.subheader("🧠 KI-Briefing")
    st.caption("Tagesaktuelle, kuratierte Zusammenfassung der relevantesten Meldungen.")

    # Load latest briefing from session state or storage
    current_briefing: str | None = st.session_state.get("cached_summary")
    briefing_meta: dict[str, Any] | None = None

    if not current_briefing:
        try:
            storage = get_storage()
            latest = storage.get_latest_briefing()
            if latest and isinstance(latest.get("content"), str):
                current_briefing = latest["content"]
                briefing_meta = latest
                st.session_state["cached_summary"] = current_briefing
        except Exception as exc:
            logger.debug("Failed to load latest briefing from storage: %s", exc)

    # Admin Generation Bar
    if is_admin:
        with st.expander("⚙️ Briefing-Generierung & Modellsteuerung", expanded=not bool(current_briefing)):
            col_m1, col_m2 = st.columns([3, 2], vertical_alignment="bottom")
            with col_m1:
                available_models = [
                    "gemini-3.5-flash-lite",
                    "gemini-2.5-flash",
                    "gemini-2.5-pro",
                ]
                default_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
                default_idx = (
                    available_models.index(default_model)
                    if default_model in available_models
                    else 0
                )
                selected_model = st.selectbox(
                    "LLM-Modell:",
                    options=available_models,
                    index=default_idx,
                    key="sel_ki_model",
                )

            with col_m2:
                btn_generate = st.button(
                    "✨ Neues Briefing generieren",
                    type="primary",
                    use_container_width=True,
                    key="btn_generate_briefing",
                )

            if btn_generate:
                total_items = sum(len(v) for v in news_data.values())
                if total_items == 0:
                    st.warning("Keine aktuellen Artikel für das Briefing vorhanden.")
                else:
                    with st.spinner(f"Generiere KI-Briefing mit {selected_model}..."):
                        t_start = time.perf_counter()
                        try:
                            summary = summarize_news_with_gemini(news_data, model=selected_model)
                            duration = time.perf_counter() - t_start
                            logger.info(
                                "Generated AI briefing (%d chars in %.2fs) using %s.",
                                len(summary),
                                duration,
                                selected_model,
                            )

                            # Save to session and storage
                            st.session_state["cached_summary"] = summary
                            current_briefing = summary

                            storage = get_storage()
                            briefing_date = time.strftime("%Y-%m-%d")
                            storage.save_briefing(briefing_date, summary, selected_model)

                            # Update RSS
                            try:
                                export_briefing_rss(summary, news_data=news_data)
                            except Exception as e_rss:
                                logger.warning("Could not export briefing RSS: %s", e_rss)

                            st.toast("KI-Briefing erfolgreich generiert!", icon="✨")
                            st.rerun()
                        except Exception as exc:
                            logger.error("AI briefing generation failed: %s", exc)
                            st.error(f"Fehler bei der Generierung: {exc}")

    # Display briefing content
    if current_briefing:
        st.markdown("---")
        st.markdown(current_briefing, unsafe_allow_html=True)
    else:
        st.info(
            "Aktuell liegt noch kein generiertes Briefing vor. "
            "Melde dich als Administrator an, um ein Briefing mit Gemini zu generieren."
        )
