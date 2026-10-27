"""
Offline-Archiv tab module for News Aggregator Bot UI.
Manages background offline feed downloads, 3-month (90 days) retention,
full-text & image inspection, and HTML / PDF export for entire feeds or single articles.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import streamlit as st

from src.aggregator import (
    get_offline_enabled_feeds,
    sync_sources_to_github,
    update_feed,
)
from src.models import OfflineArticle
from src.offline_archiver import (
    generate_offline_article_html,
    generate_offline_article_pdf,
    generate_offline_feed_html,
    generate_offline_feed_pdf,
    get_offline_task_status,
    start_offline_archive_task,
)
from src.storage import OFFLINE_RETENTION_DAYS, get_storage
from src.ui.state import format_local_dt
from src.ui.styles import render_dismissible_notice

logger = logging.getLogger(__name__)


def _slugify_filename(value: str, fallback: str = "offline-archiv") -> str:
    """Creates a safe filename slug from a feed or article title."""
    cleaned = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß_-]+", "_", (value or "").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return (cleaned[:60] or fallback).lower()


@st.cache_data(ttl=600, show_spinner=False)
def _cached_article_pdf_bytes(article_dict: dict[str, Any]) -> bytes:
    """Generates and caches PDF bytes for a single OfflineArticle."""
    article = OfflineArticle.from_dict(article_dict)
    return generate_offline_article_pdf(article)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_feed_pdf_bytes(feed_name: str, articles_tuple: tuple[dict[str, Any], ...]) -> bytes:
    """Generates and caches PDF bytes for all OfflineArticles of a feed."""
    articles = [OfflineArticle.from_dict(item) for item in articles_tuple]
    return generate_offline_feed_pdf(feed_name, articles)


def render_archive_tab(
    working_config: dict[str, Any],
    is_admin: bool,
) -> None:
    """Renders the Offline Archive management and export tab."""
    st.subheader("📦 Offline-Archiv")
    st.caption(
        f"Gespeicherte Webseiten-Abbilder (Text & Bilder) pro Feed · "
        f"Automatische Aufbewahrung für 3 Monate ({OFFLINE_RETENTION_DAYS} Tage) · HTML- & PDF-Abruf."
    )

    if not is_admin:
        st.info("🔒 Das Offline-Archiv erfordert eine Administrator-Anmeldung. Bitte melde dich links in der Leiste an.")
        return

    if st.session_state.get("archive_notice"):
        render_dismissible_notice(st.session_state["archive_notice"], notice_key="archive_notice", icon="📦")

    storage = get_storage()
    task_status = get_offline_task_status()
    offline_feeds = get_offline_enabled_feeds(working_config)
    all_offline_articles = storage.get_offline_articles(limit=1000)

    # --- 1. Status- & Steuerungs-Panel (Hintergrundtask) ---
    with st.container(border=True):
        col_stat1, col_stat2, col_stat3 = st.columns([2.4, 1.3, 1.3], vertical_alignment="center")
        is_running = bool(task_status.get("is_running", False))
        with col_stat1:
            if is_running:
                curr_feed = task_status.get("current_feed") or "Initialisiere..."
                curr_art = task_status.get("current_article") or ""
                processed_a = int(task_status.get("processed_articles", 0))
                total_a = int(task_status.get("total_articles", 0))
                saved_a = int(task_status.get("saved_articles", 0))
                art_hint = f" — *{curr_art[:45]}*" if curr_art else ""
                st.info(
                    f"🔄 **Hintergrund-Task läuft:** Feed **{curr_feed}**{art_hint} "
                    f"({processed_a}/{total_a} Artikel geprüft · {saved_a} neu gespeichert). "
                    f"Die Anwendung bleibt vollständig bedienbar."
                )
            else:
                last_finished = task_status.get("last_run_at")
                last_str = f" · Letzter Lauf: {format_local_dt(last_finished)}" if last_finished else ""
                saved_last = int(task_status.get("saved_articles", 0))
                cleaned_last = int(task_status.get("cleaned_articles", 0))
                extra_stats = ""
                if last_finished:
                    extra_stats = f" ({saved_last} neu archiviert, {cleaned_last} > 3 Mon. entfernt)"
                st.success(
                    f"✅ **Hintergrund-Archivierung bereit** · "
                    f"**{len(offline_feeds)}** Offline-Feeds aktiv · "
                    f"**{len(all_offline_articles)}** Artikel im Archiv{last_str}{extra_stats}"
                )
                if task_status.get("last_error"):
                    st.warning(f"⚠️ Letzter Hinweis: {task_status['last_error']}")

        with col_stat2:
            if st.button(
                "🔄 Jetzt im Hintergrund laden",
                key="btn_archive_start_bg",
                type="primary",
                use_container_width=True,
                disabled=is_running or len(offline_feeds) == 0,
                help="Startet den nicht-blockierenden Hintergrund-Task für alle aktivierten Offline-Feeds.",
            ):
                thread = start_offline_archive_task(config=working_config)
                if thread is not None:
                    st.session_state["archive_notice"] = (
                        f"Hintergrund-Download für {len(offline_feeds)} Offline-Feed(s) gestartet!"
                    )
                else:
                    st.session_state["archive_notice"] = "Hintergrund-Download läuft bereits."
                st.rerun()

        with col_stat3:
            col_sub1, col_sub2 = st.columns(2)
            with col_sub1:
                if st.button(
                    "🔃 Status",
                    key="btn_archive_refresh_ui",
                    use_container_width=True,
                    help="Aktualisiert die Anzeige und den Fortschritt des Hintergrund-Tasks.",
                ):
                    st.rerun()
            with col_sub2:
                if st.button(
                    "🧹 >90T",
                    key="btn_archive_cleanup_90d",
                    use_container_width=True,
                    help=f"Entfernt sofort alle Offline-Artikel, die älter als {OFFLINE_RETENTION_DAYS} Tage (3 Monate) sind.",
                ):
                    removed = storage.cleanup_offline_articles(max_age_days=OFFLINE_RETENTION_DAYS)
                    st.session_state["archive_notice"] = (
                        f"Bereinigung abgeschlossen: {removed} Artikel älter als 3 Monate ({OFFLINE_RETENTION_DAYS} Tage) entfernt."
                    )
                    st.rerun()

    # --- 2. Schnellverwaltung: Welche Feeds sind für Offline-Download aktiviert? ---
    with st.expander(f"⚙️ Offline-Download Feeds konfigurieren ({len(offline_feeds)} aktiv)", expanded=len(offline_feeds) == 0):
        st.caption(
            "Hier (oder im Tab **⚙️ Verwalten** beim Anlegen/Bearbeiten eines Feeds) kannst du festlegen, "
            "welche Feeds automatisch im Hintergrund mit komplettem Text und Bildern für 3 Monate archiviert werden."
        )
        categories_cfg = sorted(
            working_config.get("categories", []),
            key=lambda c: c.get("name", "").strip().lower(),
        )
        any_feeds_configured = False
        for cat in categories_cfg:
            cat_name = cat.get("name", "Allgemein")
            feeds_list = sorted(cat.get("feeds", []), key=lambda f: f.get("name", "").strip().lower())
            if not feeds_list:
                continue
            any_feeds_configured = True
            st.markdown(f"**📁 {cat_name}**")
            for feed in feeds_list:
                f_name = feed.get("name", "Unbenannt")
                f_url = feed.get("url", "")
                f_off = bool(feed.get("offline_download", False))
                f_hash = hashlib.md5(f_url.encode("utf-8")).hexdigest()[:8]

                col_qf1, col_qf2, col_qf3 = st.columns([3, 1.2, 1.2], vertical_alignment="center")
                with col_qf1:
                    badge = "🟢 **Offline-Archiv aktiv**" if f_off else "⚪ Standard (nur RSS)"
                    st.markdown(f"**{f_name}** · {badge}  \n`{f_url}`")
                with col_qf2:
                    toggle_label = "Deaktivieren" if f_off else "📥 Aktivieren"
                    if st.button(
                        toggle_label,
                        key=f"arch_toggle_off_{f_hash}",
                        type="secondary" if f_off else "primary",
                        use_container_width=True,
                    ):
                        new_state = not f_off
                        update_feed(
                            cat_name,
                            f_url,
                            offline_download=new_state,
                            config=working_config,
                            save_to_disk=True,
                        )
                        sync_sources_to_github(
                            config_dict=working_config,
                            commit_message=f"chore(archive): set offline_download={new_state} for {f_name}",
                            include_rss_feeds=False,
                        )
                        if new_state:
                            start_offline_archive_task(config=working_config, target_feed_url=f_url)
                            st.session_state["archive_notice"] = (
                                f"Offline-Download für '{f_name}' aktiviert & Hintergrund-Archivierung gestartet!"
                            )
                        else:
                            st.session_state["archive_notice"] = f"Offline-Download für '{f_name}' deaktiviert."
                        st.rerun()
                with col_qf3:
                    if st.button(
                        "🔄 Feed jetzt laden",
                        key=f"arch_sync_single_{f_hash}",
                        disabled=not f_off or is_running,
                        use_container_width=True,
                        help="Startet den Hintergrund-Download gezielt für diesen Feed.",
                    ):
                        start_offline_archive_task(config=working_config, target_feed_url=f_url)
                        st.session_state["archive_notice"] = f"Hintergrund-Download für '{f_name}' gestartet!"
                        st.rerun()

        if not any_feeds_configured:
            st.info("Noch keine RSS-Feeds konfiguriert. Lege zuerst im Tab '⚙️ Verwalten' Feeds an.")

    st.markdown("---")

    # --- 3. Filter & Suche über gespeicherte Offline-Artikel ---
    if not all_offline_articles:
        st.info(
            "📭 **Noch keine gespeicherten Offline-Artikel im Archiv.**  \n"
            "Aktiviere oben oder unter **⚙️ Verwalten** bei einem Feed die Option **📥 Offline-Download** "
            "und klicke auf **🔄 Jetzt im Hintergrund laden**."
        )
        return

    available_feeds = sorted({art.feed_name for art in all_offline_articles if art.feed_name})
    available_cats = sorted({art.category for art in all_offline_articles if art.category})

    col_flt1, col_flt2, col_flt3 = st.columns([1.3, 1.3, 2.0])
    with col_flt1:
        selected_feed = st.selectbox(
            "Feed filtern:",
            options=["Alle Feeds"] + available_feeds,
            key="sel_archive_feed",
        )
    with col_flt2:
        selected_cat = st.selectbox(
            "Kategorie filtern:",
            options=["Alle Kategorien"] + available_cats,
            key="sel_archive_cat",
        )
    with col_flt3:
        search_query = st.text_input(
            "Im Offline-Volltext & Titel suchen:",
            placeholder="Suchbegriff eingeben...",
            key="inp_archive_search",
        )

    # Artikel nach Filterkriterien einschränken
    filtered_articles: list[OfflineArticle] = []
    q_norm = (search_query or "").strip().lower()
    for art in all_offline_articles:
        if selected_feed != "Alle Feeds" and art.feed_name != selected_feed:
            continue
        if selected_cat != "Alle Kategorien" and art.category != selected_cat:
            continue
        if q_norm:
            haystack = f"{art.title} {art.content_text} {art.feed_name} {art.category}".lower()
            if q_norm not in haystack:
                continue
        filtered_articles.append(art)

    # Gruppierung nach Feed
    grouped_by_feed: dict[str, list[OfflineArticle]] = {}
    for art in filtered_articles:
        f_key = art.feed_name or "Unbekannter Feed"
        grouped_by_feed.setdefault(f_key, []).append(art)

    st.caption(
        f"Zeige **{len(filtered_articles)}** gespeicherte Offline-Artikel in **{len(grouped_by_feed)}** Feeds "
        f"(Aufbewahrungsdauer: {OFFLINE_RETENTION_DAYS} Tage / 3 Monate)."
    )

    # --- 4. Darstellung pro Feed inkl. Feed-Gesamtexport (HTML & PDF) und Einzelartikel-Abruf ---
    for feed_name in sorted(grouped_by_feed.keys(), key=lambda x: x.lower()):
        feed_articles = grouped_by_feed[feed_name]
        feed_hash = hashlib.md5(feed_name.encode("utf-8")).hexdigest()[:8]
        total_images = sum(len(a.images) for a in feed_articles)
        feed_slug = _slugify_filename(feed_name, fallback="feed")

        is_expanded = selected_feed != "Alle Feeds" or bool(q_norm) or len(grouped_by_feed) == 1
        expander_title = (
            f"📡 **{feed_name}** ({len(feed_articles)} Offline-Artikel · {total_images} gespeicherte Bilder)"
        )

        with st.expander(expander_title, expanded=is_expanded):
            # Feed-Aktionsleiste: Alle Artikel des Feeds als HTML oder PDF herunterladen
            with st.container(border=True):
                st.markdown(f"**📦 Gesamtabbild für Feed `{feed_name}` ({len(feed_articles)} Artikel)**")
                col_fa1, col_fa2, col_fa3 = st.columns([1.6, 1.6, 1.0], vertical_alignment="center")

                with col_fa1:
                    feed_html_str = generate_offline_feed_html(feed_name, feed_articles)
                    st.download_button(
                        label=f"🌐 Alle als HTML laden ({len(feed_articles)} Artikel + Bilder)",
                        data=feed_html_str.encode("utf-8"),
                        file_name=f"offline_feed_{feed_slug}.html",
                        mime="text/html",
                        key=f"dl_feed_html_{feed_hash}",
                        use_container_width=True,
                        type="primary",
                        help="Lädt eine eigenständige Offline-HTML-Datei mit allen Artikeln, eingebetteten Bildern und direkter PDF-Druckfunktion herunter.",
                    )

                with col_fa2:
                    articles_tuple = tuple(a.to_dict() for a in feed_articles)
                    feed_pdf_bytes = _cached_feed_pdf_bytes(feed_name, articles_tuple)
                    st.download_button(
                        label=f"📄 Alle als PDF laden ({len(feed_articles)} Artikel)",
                        data=feed_pdf_bytes,
                        file_name=f"offline_feed_{feed_slug}.pdf",
                        mime="application/pdf",
                        key=f"dl_feed_pdf_{feed_hash}",
                        use_container_width=True,
                        help="Lädt alle gespeicherten Artikel dieses Feeds inklusive Bildern als zusammengefasstes PDF-Dokument herunter.",
                    )

                with col_fa3:
                    with st.popover("🗑️ Feed-Archiv leeren", use_container_width=True):
                        st.markdown(f"Alle **{len(feed_articles)}** Offline-Artikel von **{feed_name}** löschen?")
                        if st.button(
                            "Endgültig löschen",
                            key=f"del_all_feed_{feed_hash}",
                            type="primary",
                            use_container_width=True,
                        ):
                            deleted_cnt = storage.delete_offline_articles_by_feed(feed_name)
                            st.session_state["archive_notice"] = (
                                f"{deleted_cnt} Offline-Artikel aus '{feed_name}' gelöscht."
                            )
                            st.rerun()

            # Einzelne Artikel des Feeds auflisten
            for art_idx, art in enumerate(feed_articles):
                art_hash = hashlib.md5(art.url.encode("utf-8")).hexdigest()[:10]
                art_slug = _slugify_filename(art.title, fallback=f"artikel_{art_idx}")
                pub_label = format_local_dt(art.timestamp) if art.timestamp else art.published
                img_count = len(art.images)
                char_count = len(art.content_text or "")

                with st.container(border=True):
                    col_a1, col_a2 = st.columns([3.2, 2.2], vertical_alignment="center")
                    with col_a1:
                        st.markdown(f"**{art.title}**")
                        st.caption(
                            f"🕒 {pub_label} · 📁 {art.category} · 🖼️ {img_count} Bild(er) · "
                            f"📝 {char_count} Zeichen · [🔗 Original-Webseite]({art.url})"
                        )
                    with col_a2:
                        col_btn_html, col_btn_pdf, col_btn_del = st.columns([1.2, 1.2, 0.6])
                        with col_btn_html:
                            art_html_str = generate_offline_article_html(art)
                            st.download_button(
                                label="🌐 HTML",
                                data=art_html_str.encode("utf-8"),
                                file_name=f"artikel_{art_slug}.html",
                                mime="text/html",
                                key=f"dl_art_html_{art_hash}",
                                use_container_width=True,
                                help="Einzelnen Artikel inkl. eingebetteter Bilder als Offline-HTML speichern (mit Druck-/PDF-Button).",
                            )
                        with col_btn_pdf:
                            art_pdf_bytes = _cached_article_pdf_bytes(art.to_dict())
                            st.download_button(
                                label="📄 PDF",
                                data=art_pdf_bytes,
                                file_name=f"artikel_{art_slug}.pdf",
                                mime="application/pdf",
                                key=f"dl_art_pdf_{art_hash}",
                                use_container_width=True,
                                help="Einzelnen Artikel inkl. Bildern direkt als PDF herunterladen.",
                            )
                        with col_btn_del:
                            if st.button(
                                "🗑️",
                                key=f"del_art_{art_hash}",
                                help="Diesen Offline-Artikel aus dem Archiv entfernen",
                                use_container_width=True,
                            ):
                                storage.delete_offline_article(art.url)
                                st.session_state["archive_notice"] = f"Artikel '{art.title[:40]}...' entfernt."
                                st.rerun()

                    with st.expander("📖 Gespeichertes Webseiten-Abbild anzeigen (Text & Bilder)", expanded=False):
                        if art.images:
                            img_cols = st.columns(min(len(art.images), 3))
                            for i_idx, img_entry in enumerate(art.images):
                                if isinstance(img_entry, dict):
                                    b64 = img_entry.get("data_b64", "")
                                    mime = img_entry.get("mime_type", "image/jpeg")
                                    data_uri = f"data:{mime};base64,{b64}" if b64 else ""
                                else:
                                    data_uri = str(img_entry)
                                if data_uri:
                                    with img_cols[i_idx % len(img_cols)]:
                                        st.markdown(
                                            f'<img src="{data_uri}" style="max-width:100%; border-radius:8px; margin-bottom:8px;" alt="Archivbild {i_idx + 1}" />',
                                            unsafe_allow_html=True,
                                        )
                        if art.content_text:
                            for paragraph in art.content_text.split("\n\n"):
                                p_clean = paragraph.strip()
                                if p_clean:
                                    st.markdown(p_clean)
                        else:
                            st.caption("Kein Textinhalt extrahiert.")
