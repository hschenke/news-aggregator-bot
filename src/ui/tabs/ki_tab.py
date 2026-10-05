"""
KI Briefing tab module for News Aggregator Bot UI.
Renders AI-curated daily briefings and provides generation triggers and prompt configuration for administrators.
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any

import streamlit as st

from src.summarizer import (
    summarize_news_with_gemini,
    AVAILABLE_GEMINI_MODELS,
    DEFAULT_MAIN_PROMPT_TEMPLATE,
    DEFAULT_DIRECTIVES,
)
from src.aggregator import (
    load_prompts,
    save_prompts,
    sync_sources_to_github,
)
from src.rss_generator import export_briefing_rss
from src.storage import get_storage
from src.ui.styles import render_dismissible_notice

logger = logging.getLogger(__name__)


def render_ki_tab(
    news_data: dict[str, list[dict[str, Any]]],
    is_admin: bool,
) -> None:
    """Renders the AI briefing tab."""
    st.subheader("🧠 KI-Briefing")
    st.caption("Tagesaktuelle, kuratierte Zusammenfassung der relevantesten Meldungen.")

    if st.session_state.get("ki_notice"):
        render_dismissible_notice(st.session_state["ki_notice"], notice_key="ki_notice", icon="✨")

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

    # Prompt Configuration (for Admin and read-only for others)
    try:
        prompts_cfg = load_prompts()
    except Exception:
        prompts_cfg = {}

    current_main_prompt = (prompts_cfg.get("custom_main_prompt") or "").strip() or DEFAULT_MAIN_PROMPT_TEMPLATE.strip()
    current_directives = (prompts_cfg.get("custom_prompt_directives") or "").strip() or DEFAULT_DIRECTIVES.strip()

    with st.expander("🛠️ KI-Prompt-Konfiguration (Hauptprompt & Direktiven)", expanded=False):
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
            value=current_directives,
            key="input_ki_prompt_directives",
            help="Hier kannst du z. B. vorgeben: 'Filtere reine Werbung und Sonderangebote heraus. Ignoriere Krypto. Fokussiere auf Berliner Lokalthemen.'",
            height=100,
            disabled=not is_admin,
        )

        if is_admin:
            col_save_p, col_reset_p = st.columns([1, 1])
            with col_save_p:
                if st.button("💾 Prompts in prompts.yaml speichern", key="btn_save_ki_prompts", use_container_width=True):
                    with st.spinner("Speichere Prompts in prompts.yaml..."):
                        save_prompts({
                            "custom_main_prompt": ki_main_prompt.strip(),
                            "custom_prompt_directives": ki_prompt_directives.strip(),
                        })
                        sync_sources_to_github(
                            commit_message="chore(prompt): update custom AI prompts via dashboard",
                        )
                        st.session_state["ki_notice"] = "Haupt-Prompt & Direktiven erfolgreich in prompts.yaml gespeichert!"
                        st.rerun()
            with col_reset_p:
                if st.button("↩️ Standard-Hauptprompt laden", key="btn_reset_ki_main_prompt", use_container_width=True):
                    with st.spinner("Setze Hauptprompt auf Standard zurück..."):
                        save_prompts({
                            "custom_main_prompt": DEFAULT_MAIN_PROMPT_TEMPLATE.strip(),
                            "custom_prompt_directives": ki_prompt_directives.strip(),
                        })
                        st.session_state["input_ki_main_prompt"] = DEFAULT_MAIN_PROMPT_TEMPLATE.strip()
                        st.session_state["ki_notice"] = "Standard-Hauptprompt in prompts.yaml wiederhergestellt!"
                        st.rerun()

    # Admin Generation Bar
    if is_admin:
        with st.expander("⚙️ Briefing-Generierung & Modellsteuerung", expanded=not bool(current_briefing)):
            col_m1, col_m2 = st.columns([3, 2], vertical_alignment="bottom")
            with col_m1:
                default_model = "gemini-3.5-flash-lite"
                default_idx = (
                    AVAILABLE_GEMINI_MODELS.index(default_model)
                    if default_model in AVAILABLE_GEMINI_MODELS
                    else len(AVAILABLE_GEMINI_MODELS) - 1
                )
                selected_model = st.selectbox(
                    "LLM-Modell:",
                    options=AVAILABLE_GEMINI_MODELS,
                    index=default_idx,
                    key="sel_ki_model",
                )

            with col_m2:
                is_generating = bool(st.session_state.get("is_generating_briefing", False))
                btn_generate = st.button(
                    "✨ Neues Briefing generieren",
                    type="primary",
                    use_container_width=True,
                    key="btn_generate_briefing",
                    disabled=is_generating,
                )

            if btn_generate:
                total_items = sum(len(v) for v in news_data.values())
                if total_items == 0:
                    st.warning("Keine aktuellen Artikel für das Briefing vorhanden.")
                else:
                    st.session_state["is_generating_briefing"] = True
                    with st.spinner(f"Generiere KI-Briefing mit {selected_model}..."):
                        t_start = time.perf_counter()
                        try:
                            summary = summarize_news_with_gemini(
                                news_data,
                                model=selected_model,
                                main_prompt_template=ki_main_prompt,
                                custom_directives=ki_prompt_directives,
                            )
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

                            st.session_state["is_generating_briefing"] = False
                            st.session_state["ki_notice"] = f"KI-Briefing erfolgreich mit {selected_model} generiert!"
                            st.rerun()
                        except Exception as exc:
                            st.session_state["is_generating_briefing"] = False
                            logger.error("AI briefing generation failed: %s", exc)
                            st.error(f"Fehler bei der Generierung: {exc}")

    # Display briefing content
    if current_briefing:
        st.markdown("---")
        st.markdown(current_briefing, unsafe_allow_html=True)
    else:
        if is_admin:
            st.info(
                "Aktuell liegt noch kein generiertes Briefing vor. "
                "Klicke oben auf 'Neues Briefing generieren', um ein Briefing mit Gemini zu erstellen."
            )
        else:
            st.info(
                "Aktuell liegt noch kein generiertes Briefing vor. "
                "Melde dich als Administrator an, um ein Briefing mit Gemini zu generieren."
            )
