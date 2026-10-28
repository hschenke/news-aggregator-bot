"""
Offline-Archiv tab module for News Aggregator Bot UI.
Renders archived webpage snapshots (text & images) with non-blocking background actions,
3-month (90 days) retention, and instant client-side HTML download & new-tab browser view.
Modeled after articles_tab.py for maximum smoothness and zero UI blocking.
"""

from __future__ import annotations

import base64
import hashlib
import html
import logging
import re
import time
from typing import Any

import streamlit as st

from src.aggregator import (
    format_summary_html,
    get_offline_enabled_feeds,
    sync_sources_to_github,
    update_feed,
)
from src.models import OfflineArticle
from src.offline_archiver import (
    bump_offline_cache_version,
    generate_offline_article_html,
    generate_offline_feed_html,
    get_offline_cache_version,
    get_offline_task_status,
    repair_police_offline_article,
    start_offline_archive_task,
)
from src.storage import OFFLINE_RETENTION_DAYS, get_storage
from src.ui.background import run_in_background
from src.ui.state import format_local_dt
from src.ui.styles import render_dismissible_notice

logger = logging.getLogger(__name__)

DEFAULT_ARCHIVE_PAGE_SIZE: int = 20


def _slugify_filename(value: str, fallback: str = "offline-archiv") -> str:
    """Creates a safe filename slug from a feed or article title."""
    cleaned = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß_-]+", "_", (value or "").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return (cleaned[:60] or fallback).lower()


def _load_cached_offline_articles() -> list[OfflineArticle]:
    """
    Loads offline articles from in-memory session cache if up to date,
    or fetches once from storage and automatically repairs any incomplete Berlin police reports.
    """
    curr_ver = get_offline_cache_version()
    if (
        "cached_offline_articles" in st.session_state
        and st.session_state.get("_offline_cache_ver") == curr_ver
    ):
        return [
            OfflineArticle.from_dict(item)
            for item in st.session_state["cached_offline_articles"]
        ]

    storage = get_storage()
    raw_articles = storage.get_offline_articles(limit=1000)

    repaired_articles: list[OfflineArticle] = []
    to_persist: list[OfflineArticle] = []
    needs_network_repair: list[OfflineArticle] = []
    for art in raw_articles:
        fixed_art, changed = repair_police_offline_article(art, allow_network_lookup=False)
        repaired_articles.append(fixed_art)
        if changed:
            to_persist.append(fixed_art)
        if "berlin.de/polizei" in (fixed_art.url or "").lower():
            blocks = [b.strip() for b in (fixed_art.content_text or "").split("\n\n") if b.strip()]
            if (
                len(blocks) >= 2
                and blocks[0].lower().startswith("polizeimeldung vom")
                and blocks[1].lower().lstrip("*").strip().startswith("nr.")
            ):
                needs_network_repair.append(fixed_art)

    if to_persist or needs_network_repair:
        def _bg_repair_and_save() -> None:
            final_to_save = list(to_persist)
            any_net_changed = False
            for p_art in needs_network_repair:
                net_fixed, net_changed = repair_police_offline_article(p_art, allow_network_lookup=True)
                if net_changed:
                    final_to_save.append(net_fixed)
                    any_net_changed = True
            if final_to_save:
                storage.save_offline_articles(final_to_save)
            if any_net_changed:
                bump_offline_cache_version()

        run_in_background(_bg_repair_and_save)

    st.session_state["cached_offline_articles"] = repaired_articles
    st.session_state["_offline_cache_ver"] = curr_ver
    return repaired_articles


def on_clear_archive_search() -> None:
    """Resets the archive search term without blocking."""
    st.session_state["inp_archive_search"] = ""


def on_reset_archive_filters() -> None:
    """Resets category and feed filter selections in the Archive tab."""
    st.session_state["sel_archive_cat"] = "Alle Kategorien"
    st.session_state["sel_archive_feed"] = "Alle Feeds"


def on_delete_offline_article(article_url: str, category: str = "", feed_name: str = "") -> None:
    """Optimistically removes an offline article from session state and deletes it in the background."""
    clean_url = (article_url or "").strip()
    if not clean_url:
        return

    if "cached_offline_articles" in st.session_state:
        st.session_state["cached_offline_articles"] = [
            a for a in st.session_state["cached_offline_articles"]
            if a.url.strip() != clean_url
        ]

    if category:
        st.session_state.setdefault("persisted_open_archive_cats", set()).add(category)
    if feed_name:
        st.session_state.setdefault("persisted_open_archive_feeds", set()).add(feed_name)

    def _bg_del() -> None:
        get_storage().delete_offline_article(clean_url)
        bump_offline_cache_version()

    run_in_background(_bg_del)
    st.session_state["_offline_cache_ver"] = get_offline_cache_version()


def on_clear_feed_archive(feed_name: str, category: str = "") -> None:
    """Optimistically clears all offline articles of a feed and deletes them in the background."""
    if not feed_name:
        return

    if "cached_offline_articles" in st.session_state:
        st.session_state["cached_offline_articles"] = [
            a for a in st.session_state["cached_offline_articles"]
            if a.feed_name != feed_name
        ]

    if category:
        st.session_state.setdefault("persisted_open_archive_cats", set()).add(category)

    def _bg_clear() -> None:
        get_storage().delete_offline_articles_by_feed(feed_name)
        bump_offline_cache_version()

    run_in_background(_bg_clear)
    st.session_state["archive_notice"] = f"Offline-Archiv für '{feed_name}' wurde geleert."


def on_cleanup_expired_offline() -> None:
    """Optimistically removes expired (>90 days) offline articles and runs DB cleanup in the background."""
    cutoff_ts = time.time() - (float(OFFLINE_RETENTION_DAYS) * 86400.0)
    if "cached_offline_articles" in st.session_state:
        before_cnt = len(st.session_state["cached_offline_articles"])
        st.session_state["cached_offline_articles"] = [
            a for a in st.session_state["cached_offline_articles"]
            if not (a.timestamp > 0.0 and a.timestamp < cutoff_ts)
        ]
        removed_est = max(0, before_cnt - len(st.session_state["cached_offline_articles"]))
    else:
        removed_est = 0

    def _bg_cleanup() -> None:
        get_storage().cleanup_offline_articles(max_age_days=OFFLINE_RETENTION_DAYS)
        bump_offline_cache_version()

    run_in_background(_bg_cleanup)
    st.session_state["archive_notice"] = (
        f"Bereinigung im Hintergrund gestartet ({removed_est} abgelaufene Artikel > {OFFLINE_RETENTION_DAYS} Tage entfernt)."
    )


def on_toggle_feed_offline(
    cat_name: str,
    f_name: str,
    f_url: str,
    new_state: bool,
    working_config: dict[str, Any],
) -> None:
    """Toggles offline_download in memory immediately and persists/syncs in the background."""
    update_feed(
        cat_name,
        f_url,
        offline_download=new_state,
        config=working_config,
        save_to_disk=False,
    )
    config_copy = dict(working_config)

    def _bg_persist() -> None:
        from src.aggregator import save_sources
        save_sources(config_copy)
        sync_sources_to_github(
            config_dict=config_copy,
            commit_message=f"chore(archive): set offline_download={new_state} for {f_name}",
            include_rss_feeds=False,
        )

    run_in_background(_bg_persist)
    if new_state:
        start_offline_archive_task(config=working_config, target_feed_url=f_url)
        st.session_state["archive_notice"] = (
            f"Offline-Download für '{f_name}' aktiviert — Hintergrund-Archivierung läuft!"
        )
    else:
        st.session_state["archive_notice"] = f"Offline-Download für '{f_name}' deaktiviert."


def _render_html_action_buttons(
    html_document: str,
    file_name: str,
    btn_id_suffix: str,
    open_label: str = "↗️ Im Browser öffnen",
    dl_label: str = "⬇️ HTML-Download",
) -> None:
    """
    Renders two zero-latency client-side buttons for an HTML snapshot:
    1) Opens the self-contained HTML directly in a new browser tab via Blob URL (no popup blocker, no server rerun).
    2) Downloads the self-contained HTML file directly via Blob URL (no server rerun).
    """
    b64_payload = base64.b64encode(html_document.encode("utf-8")).decode("ascii")
    safe_file = html.escape(file_name)
    open_btn_id = f"open_html_{btn_id_suffix}"
    dl_btn_id = f"dl_html_{btn_id_suffix}"
    payload_id = f"html_b64_{btn_id_suffix}"

    st.html(
        f"""
        <div class="archive-html-actions" style="display:flex;gap:0.45rem;align-items:center;flex-wrap:wrap;margin:0.15rem 0;">
            <script type="text/plain" id="{payload_id}">{b64_payload}</script>
            <button type="button" id="{open_btn_id}" class="arch-html-btn arch-html-btn-open" title="Öffnet das komplette Offline-HTML-Abbild sofort in einem neuen Browser-Tab">
                {html.escape(open_label)}
            </button>
            <button type="button" id="{dl_btn_id}" class="arch-html-btn arch-html-btn-dl" title="Lädt die eigenständige Offline-HTML-Datei herunter">
                {html.escape(dl_label)}
            </button>
        </div>
        <style>
            .arch-html-btn {{
                display: inline-flex;
                align-items: center;
                justify-content: center;
                padding: 0.3rem 0.68rem;
                font-size: 0.82rem;
                font-weight: 500;
                line-height: 1.25;
                border-radius: 0.4rem;
                cursor: pointer;
                transition: all 0.12s ease-in-out;
                font-family: inherit;
                white-space: nowrap;
            }}
            .arch-html-btn-open {{
                background-color: rgba(37, 99, 235, 0.1);
                color: #2563eb;
                border: 1px solid rgba(37, 99, 235, 0.3);
            }}
            .arch-html-btn-open:hover {{
                background-color: #2563eb;
                color: #ffffff;
                border-color: #1d4ed8;
            }}
            .arch-html-btn-dl {{
                background-color: rgba(100, 116, 139, 0.08);
                color: inherit;
                border: 1px solid rgba(128, 128, 128, 0.25);
            }}
            .arch-html-btn-dl:hover {{
                background-color: rgba(37, 99, 235, 0.08);
                border-color: #2563eb;
                color: #2563eb;
            }}
        </style>
        <script>
        (function() {{
            function getBlobUrl() {{
                var el = document.getElementById("{payload_id}");
                if (!el) return null;
                var b64 = el.textContent || "";
                var binStr = atob(b64);
                var len = binStr.length;
                var bytes = new Uint8Array(len);
                for (var i = 0; i < len; i++) {{
                    bytes[i] = binStr.charCodeAt(i);
                }}
                var blob = new Blob([bytes], {{ type: "text/html;charset=utf-8" }});
                return URL.createObjectURL(blob);
            }}

            var openBtn = document.getElementById("{open_btn_id}");
            if (openBtn) {{
                openBtn.onclick = function(e) {{
                    e.preventDefault();
                    e.stopPropagation();
                    var url = getBlobUrl();
                    if (url) {{
                        window.open(url, "_blank", "noopener");
                    }}
                }};
            }}

            var dlBtn = document.getElementById("{dl_btn_id}");
            if (dlBtn) {{
                dlBtn.onclick = function(e) {{
                    e.preventDefault();
                    e.stopPropagation();
                    var url = getBlobUrl();
                    if (url) {{
                        var a = document.createElement("a");
                        a.href = url;
                        a.download = "{safe_file}";
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                    }}
                }};
            }}
        }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def render_archive_tab(
    working_config: dict[str, Any],
    is_admin: bool,
) -> None:
    """Renders the Offline Archive tab with non-blocking actions and HTML export/view."""
    st.subheader("📦 Offline-Archiv")
    st.caption(
        f"Gespeicherte Webseiten-Abbilder (Text & Bilder) pro Feed · "
        f"3 Monate ({OFFLINE_RETENTION_DAYS} Tage) Aufbewahrung · Direkt im Browser öffnen oder als HTML herunterladen."
    )

    if not is_admin:
        st.info("🔒 Das Offline-Archiv erfordert eine Administrator-Anmeldung. Bitte melde dich links in der Leiste an.")
        return

    if st.session_state.get("archive_notice"):
        render_dismissible_notice(st.session_state["archive_notice"], notice_key="archive_notice", icon="📦")

    task_status = get_offline_task_status()
    offline_feeds = get_offline_enabled_feeds(working_config)
    all_offline_articles = _load_cached_offline_articles()
    is_running = bool(task_status.get("is_running", False))

    # --- 1. Kompakte, nicht-blockierende Status- & Aktionsleiste ---
    col_bar1, col_bar2, col_bar3, col_bar4 = st.columns([2.8, 1.2, 0.8, 0.8], vertical_alignment="center")
    with col_bar1:
        if is_running:
            curr_feed = task_status.get("current_feed") or "Initialisiere..."
            processed_a = int(task_status.get("processed_articles", 0))
            total_a = int(task_status.get("total_articles", 0))
            saved_a = int(task_status.get("saved_articles", 0))
            st.caption(
                f"🔄 **Hintergrund-Sync aktiv:** `{curr_feed}` ({processed_a}/{total_a} geprüft · {saved_a} gespeichert)"
            )
        else:
            last_finished = task_status.get("last_run_at")
            last_str = f" · Letzter Lauf: {format_local_dt(last_finished)}" if last_finished else ""
            st.caption(
                f"✅ **{len(offline_feeds)} Offline-Feeds aktiv** · **{len(all_offline_articles)} Artikel im Archiv**{last_str}"
            )
    with col_bar2:
        if st.button(
            "🔄 Hintergrund-Sync",
            key="btn_archive_start_bg",
            type="primary",
            use_container_width=True,
            disabled=is_running or len(offline_feeds) == 0,
            help="Startet den Offline-Download im Hintergrund ohne die App zu blockieren.",
        ):
            start_offline_archive_task(config=working_config)
            st.session_state["archive_notice"] = (
                f"Hintergrund-Synchronisation für {len(offline_feeds)} Offline-Feed(s) gestartet!"
            )
            st.rerun()
    with col_bar3:
        if st.button(
            "🔃 Aktualisieren",
            key="btn_archive_refresh_ui",
            use_container_width=True,
            help="Lädt neu gespeicherte Artikel aus dem Hintergrund-Task in die Ansicht.",
        ):
            bump_offline_cache_version()
            st.rerun()
    with col_bar4:
        st.button(
            f"🧹 >{OFFLINE_RETENTION_DAYS}T",
            key="btn_archive_cleanup_90d",
            use_container_width=True,
            on_click=on_cleanup_expired_offline,
            help=f"Entfernt im Hintergrund alle Offline-Artikel älter als {OFFLINE_RETENTION_DAYS} Tage (3 Monate).",
        )

    # --- 2. Kompakte Filter, Suche & Feed-Konfiguration (wie im Artikel-Tab) ---
    available_cats = sorted({art.category for art in all_offline_articles if art.category}, key=lambda x: x.lower())
    available_feeds = sorted({art.feed_name for art in all_offline_articles if art.feed_name}, key=lambda x: x.lower())

    col_exp_flt, col_exp_cfg = st.columns(2)
    with col_exp_flt:
        with st.expander("🔍 Filter & Suche", expanded=False):
            f_col1, f_col2, f_col3 = st.columns([1.3, 1.3, 0.9], vertical_alignment="bottom")
            with f_col1:
                selected_cat = st.selectbox(
                    "Kategorie:",
                    options=["Alle Kategorien"] + available_cats,
                    key="sel_archive_cat",
                )
            with f_col2:
                selected_feed = st.selectbox(
                    "Feed / Quelle:",
                    options=["Alle Feeds"] + available_feeds,
                    key="sel_archive_feed",
                )
            with f_col3:
                st.button(
                    "Reset",
                    key="btn_reset_archive_filters",
                    use_container_width=True,
                    on_click=on_reset_archive_filters,
                )

            s_col1, s_col2 = st.columns([5, 1], vertical_alignment="bottom")
            with s_col1:
                search_query = st.text_input(
                    "Volltext- & Titelsuche:",
                    placeholder="Im gespeicherten Artikeltext suchen...",
                    key="inp_archive_search",
                )
            with s_col2:
                st.button(
                    "X",
                    key="btn_clear_archive_search",
                    use_container_width=True,
                    on_click=on_clear_archive_search,
                    help="Suchbegriff löschen",
                )

    with col_exp_cfg:
        with st.expander(f"⚙️ Offline-Feeds auswählen ({len(offline_feeds)} aktiv)", expanded=len(offline_feeds) == 0):
            categories_cfg = sorted(
                working_config.get("categories", []),
                key=lambda c: c.get("name", "").strip().lower(),
            )
            for cat in categories_cfg:
                cat_name = cat.get("name", "Allgemein")
                feeds_list = sorted(cat.get("feeds", []), key=lambda f: f.get("name", "").strip().lower())
                if not feeds_list:
                    continue
                st.caption(f"📁 **{cat_name}**")
                for feed in feeds_list:
                    f_name = feed.get("name", "Unbenannt")
                    f_url = feed.get("url", "")
                    f_off = bool(feed.get("offline_download", False))
                    f_hash = hashlib.md5(f_url.encode("utf-8")).hexdigest()[:8]

                    c_qf1, c_qf2 = st.columns([2.8, 1.2], vertical_alignment="center")
                    with c_qf1:
                        status_dot = "🟢" if f_off else "⚪"
                        st.markdown(f"{status_dot} **{f_name}**")
                    with c_qf2:
                        st.button(
                            "Deaktivieren" if f_off else "📥 Aktivieren",
                            key=f"arch_toggle_off_{f_hash}",
                            type="secondary" if f_off else "primary",
                            use_container_width=True,
                            on_click=on_toggle_feed_offline,
                            args=(cat_name, f_name, f_url, not f_off, working_config),
                        )

    if not all_offline_articles:
        st.info(
            "📭 **Noch keine gespeicherten Offline-Artikel im Archiv.**  \n"
            "Aktiviere oben unter **⚙️ Offline-Feeds auswählen** (oder im Tab **⚙️ Verwalten**) einen Feed für den Offline-Download."
        )
        return

    # --- 3. Filterung & Kategorien-/Feed-Hierarchie analog zum Artikel-Tab ---
    q_norm = (search_query or "").strip().lower()
    is_filtering = bool(
        selected_cat != "Alle Kategorien"
        or selected_feed != "Alle Feeds"
        or q_norm
    )

    by_category: dict[str, list[OfflineArticle]] = {}
    for art in all_offline_articles:
        cat_label = (art.category or "Allgemein").strip()
        if selected_cat != "Alle Kategorien" and cat_label != selected_cat:
            continue
        if selected_feed != "Alle Feeds" and art.feed_name != selected_feed:
            continue
        if q_norm:
            haystack = f"{art.title} {art.content_text} {art.feed_name} {cat_label}".lower()
            if q_norm not in haystack:
                continue
        by_category.setdefault(cat_label, []).append(art)

    total_displayed = sum(len(v) for v in by_category.values())
    if total_displayed == 0:
        st.warning("Keine passenden Offline-Artikel für die gewählten Filter gefunden.")
        return

    st.caption(f"Zeige **{total_displayed}** Offline-Artikel in **{len(by_category)}** Kategorien")

    persisted_cats: set[str] = st.session_state.get("persisted_open_archive_cats", set())
    persisted_feeds: set[str] = st.session_state.get("persisted_open_archive_feeds", set())

    for category in sorted(by_category.keys(), key=lambda x: x.lower()):
        cat_articles = by_category[category]
        feeds_in_cat: dict[str, list[OfflineArticle]] = {}
        for art in cat_articles:
            feeds_in_cat.setdefault(art.feed_name or "Unbekannt", []).append(art)

        feed_cnt = len(feeds_in_cat)
        feed_lbl = "1 Feed" if feed_cnt == 1 else f"{feed_cnt} Feeds"
        item_lbl = "1 Artikel" if len(cat_articles) == 1 else f"{len(cat_articles)} Artikel"
        cat_open = is_filtering or (category in persisted_cats) or len(by_category) == 1

        with st.expander(f"📁 **{category}** ({feed_lbl}, {item_lbl})", expanded=cat_open):
            for feed_name in sorted(feeds_in_cat.keys(), key=lambda x: x.lower()):
                feed_articles = feeds_in_cat[feed_name]
                # Chronologisch sortieren (neueste zuerst)
                feed_articles.sort(key=lambda a: a.timestamp if a.timestamp > 0 else 0.0, reverse=True)

                feed_hash = hashlib.md5(f"{category}_{feed_name}".encode("utf-8")).hexdigest()[:8]
                feed_slug = _slugify_filename(feed_name, fallback="feed")
                feed_open = is_filtering or (feed_name in persisted_feeds) or len(feeds_in_cat) == 1

                with st.expander(f"📡 **{feed_name}** ({len(feed_articles)} Artikel)", expanded=feed_open):
                    # Kopfzeile des Feeds: Gesamtes Feed-Abbild im Browser öffnen oder als HTML laden + Archiv leeren
                    col_fh1, col_fh2 = st.columns([4.2, 1.0], vertical_alignment="center")
                    with col_fh1:
                        feed_html_doc = generate_offline_feed_html(feed_name, feed_articles)
                        _render_html_action_buttons(
                            html_document=feed_html_doc,
                            file_name=f"offline_feed_{feed_slug}.html",
                            btn_id_suffix=f"feed_{feed_hash}",
                            open_label=f"↗️ Alle {len(feed_articles)} Artikel im Browser öffnen",
                            dl_label=f"⬇️ Alle als HTML herunterladen ({len(feed_articles)})",
                        )
                    with col_fh2:
                        st.button(
                            "🗑️ Feed leeren",
                            key=f"del_all_feed_{feed_hash}",
                            use_container_width=True,
                            on_click=on_clear_feed_archive,
                            args=(feed_name, category),
                            help=f"Alle gespeicherten Offline-Artikel von '{feed_name}' löschen.",
                        )

                    # Paginierung pro Feed (wie im Artikel-Tab: max. 20 Cards initial rendern für maximale Performance)
                    limit_key = f"archive_feed_limit_{feed_hash}"
                    curr_limit = int(st.session_state.get(limit_key, DEFAULT_ARCHIVE_PAGE_SIZE))
                    visible_articles = feed_articles if q_norm else feed_articles[:curr_limit]

                    cols = st.columns(2)
                    for idx, art in enumerate(visible_articles):
                        art_hash = hashlib.md5(art.url.encode("utf-8")).hexdigest()[:10]
                        art_slug = _slugify_filename(art.title, fallback=f"artikel_{idx}")
                        pub_str = format_local_dt(art.timestamp) if art.timestamp else art.published
                        img_cnt = len(art.images)
                        char_cnt = len(art.content_text or "")

                        with cols[idx % 2]:
                            with st.container(border=True):
                                clean_title = html.escape(art.title)
                                safe_link = html.escape(art.url)
                                meta_parts = [f"🕒 {html.escape(pub_str)}"] if pub_str else []
                                if img_cnt > 0:
                                    meta_parts.append(f"🖼️ {img_cnt} Bild(er)")
                                meta_parts.append(f"📝 {char_cnt} Zeichen")
                                meta_line = " · ".join(meta_parts)

                                st.markdown(
                                    f"**[{clean_title}]({safe_link})**\n\n"
                                    f"<div style='font-size:0.8rem; color:#64748b; margin-top:0.15rem; margin-bottom:0.4rem;'>{meta_line}</div>",
                                    unsafe_allow_html=True,
                                )

                                with st.expander("📖 Gespeichertes Webseiten-Abbild anzeigen (Text & Bilder)", expanded=False):
                                    if art.images:
                                        img_cols = st.columns(min(len(art.images), 2))
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
                                                        f'<img src="{data_uri}" style="max-width:100%; border-radius:8px; margin-bottom:6px;" alt="Archivbild {i_idx + 1}" />',
                                                        unsafe_allow_html=True,
                                                    )
                                    if art.content_text:
                                        for paragraph in art.content_text.split("\n\n"):
                                            p_clean = paragraph.strip()
                                            if p_clean:
                                                st.markdown(p_clean)
                                    else:
                                        st.caption("Kein Textinhalt gespeichert.")

                                # Aktionszeile unten in der Card: HTML im Browser öffnen + HTML Download + Löschen-Icon rechts
                                col_act_html, col_act_del = st.columns([4.5, 0.8], vertical_alignment="center", wrap=False)
                                with col_act_html:
                                    art_html_doc = generate_offline_article_html(art)
                                    _render_html_action_buttons(
                                        html_document=art_html_doc,
                                        file_name=f"artikel_{art_slug}.html",
                                        btn_id_suffix=f"art_{art_hash}_{idx}",
                                        open_label="↗️ Im Tab öffnen",
                                        dl_label="⬇️ HTML-Download",
                                    )
                                with col_act_del:
                                    st.button(
                                        "",
                                        icon=":material/delete:",
                                        key=f"read_del_arch_{art_hash}_{idx}",
                                        type="tertiary",
                                        help="Diesen Offline-Artikel aus dem Archiv entfernen",
                                        on_click=on_delete_offline_article,
                                        args=(art.url, category, feed_name),
                                    )

                    if len(feed_articles) > len(visible_articles):
                        rem = len(feed_articles) - len(visible_articles)
                        nxt = min(DEFAULT_ARCHIVE_PAGE_SIZE, rem)
                        c_m1, c_m2, c_m3 = st.columns([1, 2, 1])
                        with c_m2:
                            if st.button(
                                f"▼ Weitere {nxt} von {rem} Offline-Artikeln laden",
                                key=f"btn_more_arch_{feed_hash}",
                                use_container_width=True,
                            ):
                                st.session_state[limit_key] = curr_limit + DEFAULT_ARCHIVE_PAGE_SIZE
                                st.session_state.setdefault("persisted_open_archive_cats", set()).add(category)
                                st.session_state.setdefault("persisted_open_archive_feeds", set()).add(feed_name)
                                st.rerun()
