"""
Quellen & Feeds verwalten tab module for News Aggregator Bot UI.
Provides management of categories, feeds, global settings, database purge, and configuration persistence.
"""

from __future__ import annotations

import copy
import hashlib
import logging
from typing import Any

import yaml
import streamlit as st

from src.aggregator import (
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
    sync_sources_to_github,
    get_streamlit_app_url,
    DEFAULT_ARCHIVE_RETENTION_DAYS,
)
from src.storage import get_storage
from src.ui.styles import render_dismissible_notice

logger = logging.getLogger(__name__)


def render_feed_test_result(t_res: dict[str, Any]) -> None:
    """Renders a clean expandable infobox with stream test diagnostics."""
    if not t_res:
        return

    success = t_res.get("success", False)
    item_count = t_res.get("item_count", 0)
    title = t_res.get("title", "Unbekannter Titel")
    stream_type = t_res.get("stream_type", "Unbekannt")
    status_code = t_res.get("status_code", "-")
    latency_ms = t_res.get("latency_ms", 0)
    content_type = t_res.get("content_type", "")
    content_len = t_res.get("content_length", 0)
    err = t_res.get("error")

    icon = "✅" if (success and item_count > 0) else ("⚠️" if success else "❌")
    box_header = (
        f"{icon} Stream-Test: {title} ({stream_type} • {item_count} Artikel)"
        if (success and item_count > 0)
        else f"{icon} Stream-Test: {title} ({'0 Artikel' if success else err or 'Fehlgeschlagen'})"
    )

    with st.expander(box_header, expanded=True):
        if success and item_count > 0:
            st.success(f"**Stream erfolgreich verifiziert:** **{title}** ({stream_type}) — **{item_count} Einträge** gefunden!")
        elif success and item_count == 0:
            st.warning(f"**Stream erreichbar, aber leer:** **{title}** ({stream_type}) lieferte aktuell **0 Artikel**.")
        else:
            st.error(f"**Stream-Test fehlgeschlagen:** {err or 'Unbekannter Fehler'}")

        col_info1, col_info2 = st.columns(2)
        with col_info1:
            st.markdown(f"• **Stream-Format:** `{stream_type}`")
            st.markdown(f"• **Gefundene Artikel:** **{item_count}** Einträge")
            if t_res.get("site_url"):
                st.markdown(f"• **Website der Quelle:** [{t_res['site_url']}]({t_res['site_url']})")
        with col_info2:
            status_badge = f"`HTTP {status_code}`" if status_code else "`-`"
            st.markdown(f"• **Server-Status:** {status_badge} ({latency_ms} ms)")
            ct_clean = content_type.split(";")[0].strip() if content_type else "unbekannt"
            size_str = f" • {content_len / 1024:.1f} KB" if content_len else ""
            st.markdown(f"• **Content-Type:** `{ct_clean}`{size_str}")


def render_manage_tab(
    working_config: dict[str, Any],
    is_admin: bool,
) -> None:
    """Renders the settings and feed management tab."""
    st.subheader("⚙️ Quellen & Feeds verwalten")
    st.caption("Verwalte deine Kategorien, Feeds und Einstellungen. Änderungen werden im Arbeitsentwurf gesammelt.")

    if not is_admin:
        st.info("🔒 Dieser Bereich erfordert eine Administrator-Anmeldung. Bitte melde dich links in der Leiste an.")
        return

    # Prominenter Erfolgs- / Status-Hinweis nach Aktionen
    if st.session_state.get("manage_notice"):
        render_dismissible_notice(st.session_state["manage_notice"], notice_key="manage_notice", icon="✅")

    has_unsaved_changes = bool(st.session_state.get("has_unsaved_changes", False))

    # Top Status & Save Bar
    with st.container(border=True):
        col_st1, col_st2, col_st3 = st.columns([3, 1, 1], vertical_alignment="center")
        with col_st1:
            if has_unsaved_changes:
                st.warning("⚠️ **Ungespeicherte Änderungen vorhanden!** (Noch nicht in `sources.yaml` geschrieben)")
            else:
                st.success("✅ **Alle Feeds & Einstellungen sind auf dem aktuellen Stand (gespeichert).**")
        with col_st2:
            btn_save_label = "💾 Jetzt sichern" if has_unsaved_changes else "💾 Gespeichert"
            btn_save_disabled = not has_unsaved_changes or bool(st.session_state.get("is_saving_sources", False))
            if st.button(
                btn_save_label,
                type="primary" if has_unsaved_changes else "secondary",
                use_container_width=True,
                key="top_save_sources_btn",
                disabled=btn_save_disabled,
                help="Sichert alle Änderungen dauerhaft in sources.yaml" if has_unsaved_changes else "Alle Feeds & Einstellungen sind aktuell gespeichert.",
            ):
                st.session_state["is_saving_sources"] = True
                with st.spinner("Sichere Feeds & Einstellungen nach sources.yaml..."):
                    save_sources(working_config)
                    sync_res = sync_sources_to_github(
                        config_dict=working_config,
                        commit_message="chore(config): update sources.yaml and RSS feeds via web dashboard",
                        include_rss_feeds=True,
                    )
                    st.session_state["has_unsaved_changes"] = False
                    st.session_state["is_saving_sources"] = False
                    if sync_res.get("success"):
                        st.session_state["manage_notice"] = "Änderungen erfolgreich in sources.yaml gespeichert & zu GitHub synchronisiert!"
                    else:
                        st.session_state["manage_notice"] = "Änderungen lokal in sources.yaml gespeichert!"
                    st.rerun()
        with col_st3:
            if has_unsaved_changes:
                if st.button("↩️ Verwerfen", use_container_width=True, key="top_discard_sources_btn"):
                    with st.spinner("Verwerfe ungespeicherte Änderungen..."):
                        from src.aggregator import load_sources
                        st.session_state["working_sources_config"] = load_sources()
                        st.session_state["has_unsaved_changes"] = False
                        # Lösche alle Formular-Keys im Session State, damit alle Textfelder sofort zurückgesetzt werden
                        keys_to_clear = [
                            k for k in list(st.session_state.keys())
                            if k.startswith(("ed_", "inp_set_", "inp_new_", "sel_ren_cat", "sel_new_feed_cat"))
                        ]
                        for k in keys_to_clear:
                            del st.session_state[k]
                        st.session_state.pop("editing_feed_key", None)
                        st.session_state.pop("editing_feed_url", None)
                        st.session_state.pop("editing_feed_name", None)
                        st.session_state.pop("editing_feed_category", None)
                        st.session_state.pop("last_edited_category", None)
                        st.session_state["manage_notice"] = "Alle ungespeicherten Änderungen wurden verworfen."
                        embed_client_script("setTimeout(function(){ window.location.reload(); }, 60);")
                        st.rerun()

    st.markdown("---")

    # --- Sektion 1: Kategorien verwalten (standardmäßig zugeklappt) ---
    with st.expander("📁 Kategorien verwalten", expanded=False):
        if st.session_state.get("manage_cat_notice"):
            render_dismissible_notice(st.session_state["manage_cat_notice"], notice_key="manage_cat_notice", icon="📁")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            new_cat_name = st.text_input("Neue Kategorie anlegen:", placeholder="z. B. Wirtschaft & Finanzen", key="inp_new_cat_name")
            if st.button("➕ Kategorie hinzufügen", key="btn_add_cat", use_container_width=True):
                if new_cat_name.strip():
                    with st.spinner("Füge Kategorie hinzu..."):
                        add_category(new_cat_name.strip(), config=working_config, save_to_disk=False)
                        st.session_state["has_unsaved_changes"] = True
                        st.session_state["manage_cat_notice"] = f"Kategorie '{new_cat_name.strip()}' hinzugefügt."
                        st.session_state["manage_notice"] = f"Kategorie '{new_cat_name.strip()}' hinzugefügt."
                        st.rerun()
                else:
                    st.error("Bitte einen Kategorienamen angeben.")

        with col_c2:
            cat_names = [c.get("name", "").strip() for c in working_config.get("categories", []) if c.get("name")]
            if cat_names:
                col_ren1, col_ren2 = st.columns([1, 1])
                with col_ren1:
                    cat_to_rename = st.selectbox("Kategorie umbenennen:", options=cat_names, key="sel_ren_cat")
                with col_ren2:
                    cat_new_name = st.text_input("Neuer Name:", placeholder="Neuer Name...", key="inp_ren_cat_name")
                if st.button("✏️ Umbenennen", key="btn_ren_cat", use_container_width=True):
                    if cat_new_name.strip() and cat_to_rename:
                        with st.spinner("Benenne Kategorie um..."):
                            rename_category(cat_to_rename, cat_new_name.strip(), config=working_config, save_to_disk=False)
                            st.session_state["has_unsaved_changes"] = True
                            st.session_state["manage_cat_notice"] = f"Kategorie umbenannt in '{cat_new_name.strip()}'."
                            st.session_state["manage_notice"] = f"Kategorie umbenannt in '{cat_new_name.strip()}'."
                            st.rerun()

    # --- Sektion 2: Neuen RSS-Feed hinzufügen (standardmäßig zugeklappt) ---
    with st.expander("➕ Neuen RSS-Feed hinzufügen", expanded=False):
        if st.session_state.get("manage_new_feed_notice"):
            render_dismissible_notice(st.session_state["manage_new_feed_notice"], notice_key="manage_new_feed_notice", icon="➕")
        col_f1, col_f2 = st.columns([1, 1])
        with col_f1:
            feed_url_input = st.text_input("Feed-URL:", placeholder="https://example.com/feed.xml", key="inp_new_feed_url")
            feed_name_input = st.text_input("Feed-Name:", placeholder="z. B. TechCrunch News", key="inp_new_feed_name")
        with col_f2:
            target_cat = st.selectbox("Ziel-Kategorie:", options=cat_names if cat_names else ["Allgemein"], key="sel_new_feed_cat")
            col_kw1, col_kw2 = st.columns(2)
            with col_kw1:
                inc_kw_input = st.text_input("🟢 Nur mit Keywords (Komma):", placeholder="z. B. KI, Python", key="inp_new_feed_inc")
            with col_kw2:
                exc_kw_input = st.text_input("🔴 Ohne Keywords (Komma):", placeholder="z. B. Krypto, Sport", key="inp_new_feed_exc")

        col_tst, col_add = st.columns([1, 1])
        with col_tst:
            if st.button("🔍 Feed testen", key="btn_test_new_feed", use_container_width=True):
                if feed_url_input.strip():
                    with st.spinner("Prüfe Feed-Verbindung..."):
                        t_res = test_feed_connection(feed_url_input.strip())
                        render_feed_test_result(t_res)
                else:
                    st.error("Bitte eine Feed-URL eingeben.")
        with col_add:
            if st.button("➕ Feed hinzufügen", type="primary", key="btn_submit_new_feed", use_container_width=True):
                if feed_url_input.strip() and feed_name_input.strip():
                    with st.spinner("Füge Feed hinzu..."):
                        add_feed(
                            category_name=target_cat,
                            feed_name=feed_name_input.strip(),
                            feed_url=feed_url_input.strip(),
                            include_keywords=inc_kw_input.strip(),
                            exclude_keywords=exc_kw_input.strip(),
                            config=working_config,
                            save_to_disk=False,
                        )
                        st.session_state["has_unsaved_changes"] = True
                        st.session_state["manage_notice"] = f"Feed '{feed_name_input.strip()}' hinzugefügt!"
                        st.rerun()
                else:
                    st.error("Bitte Feed-URL und Feed-Name ausfüllen.")

    st.markdown("---")

    # --- Sektion 3: Aktive Feeds nach Kategorien bearbeiten & löschen ---
    st.markdown("### 📋 Aktive Feeds nach Kategorien")
    categories = sorted(working_config.get("categories", []), key=lambda c: c.get("name", "").strip().lower())

    for cat_idx, cat in enumerate(categories):
        cat_name = cat.get("name", "Allgemein")
        feeds = sorted(cat.get("feeds", []), key=lambda f: f.get("name", "").strip().lower())

        is_cat_expanded = (
            st.session_state.get("last_edited_category") == cat_name
            or st.session_state.get("editing_feed_category") == cat_name
        )

        with st.expander(f"📁 **{cat_name}** ({len(feeds)} Feeds)", expanded=is_cat_expanded):
            col_cinf, col_cdel = st.columns([5, 1], vertical_alignment="center")
            with col_cinf:
                st.caption(f"{len(feeds)} konfigurierte Feeds in dieser Kategorie.")
            with col_cdel:
                with st.popover("🗑️ Kategorie löschen", use_container_width=True):
                    st.markdown(f"Kategorie **'{cat_name}'** samt aller Feeds wirklich löschen?")
                    if st.button("Kategorie löschen", key=f"del_cat_{cat_idx}", type="primary", use_container_width=True):
                        delete_category(cat_name, config=working_config, save_to_disk=False)
                        st.session_state["has_unsaved_changes"] = True
                        st.session_state["manage_notice"] = f"Kategorie '{cat_name}' gelöscht."
                        st.rerun()

            for feed_idx, feed in enumerate(feeds):
                f_name = feed.get("name", "Unbenannt")
                f_url = feed.get("url", "")
                f_inc = feed.get("include_keywords", [])
                f_exc = feed.get("exclude_keywords", [])
                key_hash = hashlib.md5(f_url.encode("utf-8")).hexdigest()[:8]

                with st.container(border=True):
                    col_top1, col_top2 = st.columns([5, 1], vertical_alignment="center")
                    with col_top1:
                        st.markdown(f"**{f_name}**")
                        st.caption(f"🔗 [{f_url}]({f_url})")
                    with col_top2:
                        with st.popover("🗑️ Löschen", use_container_width=True):
                            st.markdown(f"Feed **'{f_name}'** wirklich entfernen?")
                            if st.button("Löschen bestätigen", key=f"del_feed_{cat_idx}_{feed_idx}", type="primary", use_container_width=True):
                                delete_feed(cat_name, f_url, config=working_config, save_to_disk=False)
                                st.session_state["has_unsaved_changes"] = True
                                st.session_state["manage_notice"] = f"Feed '{f_name}' entfernt."
                                st.rerun()

                    # Der Bearbeiten-Block: Bleibt bei Änderungen explizit OFFEN!
                    is_feed_expanded = (
                        st.session_state.get("editing_feed_key") == key_hash
                        or st.session_state.get("editing_feed_url") == f_url
                        or st.session_state.get("editing_feed_name") == f_name
                    )
                    with st.expander("🛠️ Details & URL bearbeiten / Feed testen", expanded=is_feed_expanded):
                        col_ed1, col_ed2 = st.columns(2)
                        with col_ed1:
                            edit_name_val = st.text_input("Name:", value=f_name, key=f"ed_name_{key_hash}")
                            edit_url_val = st.text_input("URL:", value=f_url, key=f"ed_url_{key_hash}")
                        with col_ed2:
                            cat_opts = cat_names if cat_names else ["Allgemein"]
                            default_cat_idx = cat_opts.index(cat_name) if cat_name in cat_opts else 0
                            edit_cat_val = st.selectbox("Kategorie:", options=cat_opts, index=default_cat_idx, key=f"ed_cat_{key_hash}")
                            col_e_kw1, col_e_kw2 = st.columns(2)
                            with col_e_kw1:
                                edit_inc_val = st.text_input(
                                    "🟢 Nur Keywords:",
                                    value=", ".join(f_inc) if isinstance(f_inc, list) else str(f_inc or ""),
                                    key=f"ed_inc_{key_hash}",
                                )
                            with col_e_kw2:
                                edit_exc_val = st.text_input(
                                    "🔴 Ohne Keywords:",
                                    value=", ".join(f_exc) if isinstance(f_exc, list) else str(f_exc or ""),
                                    key=f"ed_exc_{key_hash}",
                                )

                        col_eb1, col_eb2 = st.columns([1, 1])
                        with col_eb1:
                            if st.button("🔍 Feed testen", key=f"btn_tst_{key_hash}", use_container_width=True):
                                st.session_state["editing_feed_key"] = key_hash
                                st.session_state["editing_feed_url"] = f_url
                                st.session_state["editing_feed_name"] = f_name
                                st.session_state["editing_feed_category"] = cat_name
                                st.session_state["last_edited_category"] = cat_name
                                with st.spinner("Teste Feed..."):
                                    res = test_feed_connection(edit_url_val.strip())
                                    render_feed_test_result(res)
                        with col_eb2:
                            if st.session_state.get("last_saved_feed_key") == key_hash:
                                st.success("✅ Feed-Änderungen im Entwurf gemerkt!")
                            if st.button("✔️ Im Entwurf merken", key=f"btn_save_feed_{key_hash}", type="primary", use_container_width=True):
                                if edit_name_val.strip() and edit_url_val.strip():
                                    with st.spinner("Merke Feed-Änderungen im Arbeitsentwurf..."):
                                        update_feed(
                                            cat_name,
                                            f_url,
                                            new_name=edit_name_val.strip(),
                                            new_url=edit_url_val.strip(),
                                            new_category=edit_cat_val.strip(),
                                            include_keywords=edit_inc_val.strip(),
                                            exclude_keywords=edit_exc_val.strip(),
                                            config=working_config,
                                            save_to_disk=False,
                                        )
                                        new_hash = hashlib.md5(edit_url_val.strip().encode("utf-8")).hexdigest()[:8]
                                        # State merken, damit der Expander OFFEN bleibt!
                                        st.session_state["editing_feed_key"] = new_hash
                                        st.session_state["last_saved_feed_key"] = new_hash
                                        st.session_state["editing_feed_url"] = edit_url_val.strip()
                                        st.session_state["editing_feed_name"] = edit_name_val.strip()
                                        st.session_state["editing_feed_category"] = edit_cat_val.strip()
                                        st.session_state["last_edited_category"] = edit_cat_val.strip()
                                        st.session_state["has_unsaved_changes"] = True
                                        st.session_state["manage_notice"] = f"Feed-Änderungen für '{edit_name_val.strip()}' im Entwurf gemerkt!"
                                        st.rerun()
                                else:
                                    st.error("Name und URL dürfen nicht leer sein.")

    st.markdown("---")

    # --- Sektion 4: Globale Einstellungen ---
    st.markdown("### ⚙️ Globale Einstellungen")
    with st.container(border=True):
        if st.session_state.get("manage_settings_notice"):
            render_dismissible_notice(st.session_state["manage_settings_notice"], notice_key="manage_settings_notice", icon="⚙️")
        settings = working_config.get("settings", {})

        col_s1, col_s2 = st.columns(2)
        with col_s1:
            app_url_val = st.text_input(
                "Streamlit App URL:",
                value=settings.get("streamlit_app_url", ""),
                help="Öffentliche Basis-URL der Streamlit Cloud App für Deeplinks.",
                key="inp_set_app_url",
            )
            lang_val = st.text_input("Sprache:", value=settings.get("language", "de"), key="inp_set_lang")
        with col_s2:
            # Archiv-Aufbewahrung in Tagen (Wochenschema vollständig eliminiert!)
            curr_retention = int(settings.get("archive_retention_days", DEFAULT_ARCHIVE_RETENTION_DAYS))
            retention_val = st.number_input(
                "Archiv-Aufbewahrung (Tage):",
                min_value=1,
                max_value=365,
                value=curr_retention,
                help="Archivierte Artikel, die älter als diese Anzahl an Tagen sind, werden beim morgendlichen Lauf automatisch aus der Datenbank gelöscht.",
                key="inp_set_retention_days",
            )
            style_val = st.text_input("Zusammenfassungs-Stil:", value=settings.get("summary_style", "tldr"), key="inp_set_style")

        if st.button("✔️ Einstellungen im Entwurf übernehmen", key="btn_apply_settings", use_container_width=True):
            with st.spinner("Übernehme Einstellungen im Arbeitsentwurf..."):
                settings["streamlit_app_url"] = app_url_val.strip()
                settings["language"] = lang_val.strip()
                settings["archive_retention_days"] = int(retention_val)
                settings["summary_style"] = style_val.strip()
                # Wochenschema sicherstellen, dass es weg ist
                settings.pop("max_article_age_weeks", None)
                settings.pop("max_age_weeks", None)
                settings.pop("batch_sync_interval_minutes", None)
                working_config["settings"] = settings
                st.session_state["has_unsaved_changes"] = True
                st.session_state["manage_settings_notice"] = "Globale Einstellungen erfolgreich im Entwurf übernommen!"
                st.session_state["manage_notice"] = "Globale Einstellungen erfolgreich im Entwurf übernommen!"
                st.rerun()

    st.markdown("---")

    # --- Sektion 5: Live YAML Preview ---
    with st.expander("📄 Vorschau der `sources.yaml` Datei", expanded=False):
        yaml_content = yaml.dump(working_config, allow_unicode=True, sort_keys=False)
        st.code(yaml_content, language="yaml")
