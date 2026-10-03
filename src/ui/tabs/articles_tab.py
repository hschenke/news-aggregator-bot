"""
Articles tab module for News Aggregator Bot UI.
Renders active articles limited to the last 24 hours with search, category filtering,
direct non-blocking feedback and archiving, and responsive mobile-first layouts.
"""

from __future__ import annotations

import re
import hashlib
import time
from typing import Any

import streamlit as st

from src.models import Article
from src.aggregator import (
    get_article_timestamp,
    get_canonical_url,
    clean_html_text,
    format_summary_html,
)
from src.ui.styles import embed_client_script
from src.ui.background import (
    persist_read_and_archive_async,
    persist_feedback_async,
)


def on_article_feedback_change(article_url: str, fb_widget_key: str, article_title: str = "") -> None:
    """Updates feedback in session state and persists directly in the background."""
    raw_val = st.session_state.get(fb_widget_key)
    # st.feedback("thumbs") returns 1 for thumbs up, 0 for thumbs down, None for cleared
    if raw_val == 1:
        new_fb = 1
    elif raw_val == 0:
        new_fb = -1
    else:
        new_fb = 0

    if "feedback_map" not in st.session_state:
        st.session_state["feedback_map"] = {}
    st.session_state["feedback_map"][article_url] = new_fb

    persist_feedback_async(article_url, new_fb, article_title)


def on_article_read_and_archive(article_item: dict[str, Any], category: str = "", feed_name: str = "") -> None:
    """Marks article as read, immediately hides it from active view, and archives it in background."""
    item_url = (article_item.get("link") or "").strip()
    if not item_url:
        return

    if "archived_urls" not in st.session_state:
        st.session_state["archived_urls"] = set()
    st.session_state["archived_urls"].add(item_url)

    if "read_urls" not in st.session_state:
        st.session_state["read_urls"] = set()
    st.session_state["read_urls"].add(item_url)

    if category:
        if "persisted_open_categories" not in st.session_state:
            st.session_state["persisted_open_categories"] = set()
        st.session_state["persisted_open_categories"].add(category)
    if feed_name:
        if "persisted_open_feeds" not in st.session_state:
            st.session_state["persisted_open_feeds"] = set()
        st.session_state["persisted_open_feeds"].add(feed_name)
        feed_slug = "".join(c if c.isalnum() else "_" for c in feed_name)
        st.session_state["last_read_feed_slug"] = feed_slug

    persist_read_and_archive_async(article_item)


def on_clear_search() -> None:
    """Resets the search term and rating filter."""
    st.session_state["input_search_query"] = ""
    st.session_state["sel_articles_rating"] = "Alle Bewertungen"


def format_article_date(item: dict[str, Any]) -> str:
    """Formats the publication timestamp in local time."""
    from src.ui.state import format_local_dt
    ts = get_article_timestamp(item)
    return format_local_dt(ts)


def render_articles_tab(
    news_data: dict[str, list[dict[str, Any]]],
    working_config: dict[str, Any],
) -> None:
    """Renders the active 24h articles grouped by categories and feeds."""
    archived_urls_set = set(st.session_state.get("archived_urls", set())) | set(
        st.session_state.get("read_urls", set())
    )

    qp_category = st.query_params.get("category", "").strip()
    qp_feed = st.query_params.get("feed", "").strip()

    # Configured categories
    configured_cats = [
        c.get("name", "").strip()
        for c in working_config.get("categories", [])
        if c.get("name", "").strip()
    ]
    known_cats_set = set(configured_cats) if configured_cats else {k.strip() for k in news_data.keys() if k.strip()}
    sorted_all_categories = sorted(list(known_cats_set), key=lambda x: x.strip().lower())
    category_options = ["Alle Kategorien"] + sorted_all_categories

    if qp_category:
        for opt in category_options:
            if opt.strip().lower() == qp_category.lower():
                st.session_state["sel_articles_category"] = opt
                break

    current_cat = st.session_state.get("sel_articles_category", "Alle Kategorien")
    if current_cat not in category_options:
        current_cat = "Alle Kategorien"
        st.session_state["sel_articles_category"] = current_cat

    # Feeds for current category
    if current_cat == "Alle Kategorien":
        cat_feed_names: set[str] = set()
        for c in working_config.get("categories", []):
            for f in c.get("feeds", []):
                fn = f.get("name") or f.get("url")
                if fn:
                    cat_feed_names.add(fn.strip())
        for c_name, items in news_data.items():
            for it in items:
                src = it.get("source", "").strip()
                if src:
                    cat_feed_names.add(src)
    else:
        cat_feed_names = set()
        for c in working_config.get("categories", []):
            if c.get("name", "").strip().lower() == current_cat.lower():
                for f in c.get("feeds", []):
                    fn = f.get("name") or f.get("url")
                    if fn:
                        cat_feed_names.add(fn.strip())
        for it in news_data.get(current_cat, []):
            src = it.get("source", "").strip()
            if src:
                cat_feed_names.add(src)

    sorted_cat_feeds = sorted(list(cat_feed_names), key=lambda x: x.strip().lower())
    feed_options = ["Alle Feeds"] + sorted_cat_feeds

    feed_widget_key = f"sel_articles_feed_{current_cat}"
    if "articles_cat_feed_memory" not in st.session_state:
        st.session_state["articles_cat_feed_memory"] = {}
    remembered_feed = st.session_state["articles_cat_feed_memory"].get(current_cat, "Alle Feeds")

    qp_feed_canonical = None
    if qp_feed:
        for fo in feed_options:
            if fo.strip().lower() == qp_feed.lower():
                qp_feed_canonical = fo
                break
    if qp_feed_canonical and current_cat != "Alle Kategorien":
        remembered_feed = qp_feed_canonical

    if remembered_feed not in feed_options:
        remembered_feed = "Alle Feeds"

    if feed_widget_key not in st.session_state or (qp_feed_canonical and st.session_state.get(feed_widget_key) != qp_feed_canonical):
        st.session_state[feed_widget_key] = remembered_feed

    # Filter summary & criteria
    filter_summary_items = []
    if current_cat != "Alle Kategorien":
        filter_summary_items.append(f"📁 {current_cat}")
    curr_selected_feed = st.session_state.get(feed_widget_key, "Alle Feeds")
    if curr_selected_feed != "Alle Feeds":
        filter_summary_items.append(f"📡 {curr_selected_feed}")
    curr_rating = st.session_state.get("sel_articles_rating", "Alle Bewertungen")
    if curr_rating == "Nur Favoriten 👍":
        filter_summary_items.append("⭐ Nur Favoriten")
    elif curr_rating == "Nur Irrelevante 👎":
        filter_summary_items.append("👎 Nur Irrelevante")
    active_search_text = st.session_state.get("input_search_query", "").strip()
    if active_search_text:
        filter_summary_items.append(f"🔍 '{active_search_text}'")

    is_filtering = bool(
        current_cat != "Alle Kategorien"
        or curr_selected_feed != "Alle Feeds"
        or curr_rating != "Alle Bewertungen"
        or active_search_text
    )

    with st.expander("🔍 Filter & Suche", expanded=False, key="expander_filter_search"):
        filter_col_cat, filter_col_feed, filter_col_rating = st.columns([1.2, 1.2, 1.0])
        with filter_col_cat:
            selected_cat = st.selectbox(
                "Kategorie:",
                options=category_options,
                key="sel_articles_category",
            )
            if qp_category and selected_cat.strip().lower() != qp_category.lower():
                if "category" in st.query_params:
                    del st.query_params["category"]
                if "feed" in st.query_params:
                    del st.query_params["feed"]

        with filter_col_feed:
            selected_feed = st.selectbox(
                "Feed / Quelle:",
                options=feed_options,
                key=feed_widget_key,
            )
            st.session_state["articles_cat_feed_memory"][selected_cat] = selected_feed
            if qp_feed and selected_feed.strip().lower() != qp_feed.lower():
                if "feed" in st.query_params:
                    del st.query_params["feed"]

        with filter_col_rating:
            st.selectbox(
                "Bewertung:",
                options=["Alle Bewertungen", "Nur Favoriten 👍", "Nur Irrelevante 👎"],
                key="sel_articles_rating",
            )

        col_search_inp, col_search_btn = st.columns([5, 1], vertical_alignment="bottom")
        with col_search_inp:
            st.text_input(
                "Suchbegriff:",
                placeholder="In Titel oder Text suchen...",
                key="input_search_query",
            )
        with col_search_btn:
            if st.button("Zurücksetzen", key="btn_search_clear", use_container_width=True, on_click=on_clear_search):
                st.rerun()

    # Status summary
    col_stat_placeholder = st.empty()
    search_query = active_search_text.lower()
    descending_sort = not bool(st.session_state.get("chk_sort_oldest", False))

    displayed_count = 0
    categories_rendered = 0
    rendered_element_keys: set[str] = set()

    for category, items in news_data.items():
        if selected_cat != "Alle Kategorien" and category != selected_cat:
            continue

        cat_matching = []
        for it in items:
            item_url = (it.get("link") or "").strip()
            if item_url in archived_urls_set or get_canonical_url(item_url) in archived_urls_set:
                continue

            feed_name = it.get("source", "Unbekannt")
            if selected_feed != "Alle Feeds" and feed_name != selected_feed:
                continue

            fb_val = st.session_state.get("feedback_map", {}).get(item_url, it.get("feedback", 0))
            if curr_rating == "Nur Favoriten 👍" and fb_val != 1:
                continue
            if curr_rating == "Nur Irrelevante 👎" and fb_val != -1:
                continue

            if search_query:
                t = (it.get("title") or "").lower()
                s = (it.get("summary") or "").lower()
                if search_query not in t and search_query not in s:
                    continue

            cat_matching.append(it)

        if not cat_matching:
            continue

        categories_rendered += 1

        cat_is_open = True if (
            is_filtering
            or (qp_category and category.strip().lower() == qp_category.lower())
            or bool(st.session_state.get("chk_expand_all", False))
            or category in st.session_state.get("persisted_open_categories", set())
        ) else False

        feed_count_in_cat = len({it.get("source", "Unbekannt") for it in cat_matching})
        feed_label = f"{feed_count_in_cat} Feeds" if feed_count_in_cat != 1 else "1 Feed"
        item_label = f"{len(cat_matching)} Artikel" if len(cat_matching) != 1 else "1 Artikel"

        with st.expander(f"📁 **{category}** ({feed_label}, {item_label})", expanded=cat_is_open):
            feeds_dict: dict[str, list[dict[str, Any]]] = {}
            for item in cat_matching:
                src = item.get("source", "Unbekannt")
                feeds_dict.setdefault(src, []).append(item)

            sorted_feed_names = sorted(feeds_dict.keys(), key=lambda x: x.strip().lower())

            for feed_name in sorted_feed_names:
                f_items_raw = feeds_dict[feed_name]
                seen_f_urls = set()
                f_items = []
                for it in f_items_raw:
                    u = (it.get("link") or "").strip()
                    if u and u in seen_f_urls:
                        continue
                    if u:
                        seen_f_urls.add(u)
                    f_items.append(it)

                f_items.sort(key=lambda x: get_article_timestamp(x), reverse=descending_sort)

                feed_slug = "".join(c if c.isalnum() else "_" for c in feed_name)
                feed_limit_key = f"feed_limit_{feed_slug}"
                DEFAULT_FEED_PAGE_SIZE = 20
                current_feed_limit = st.session_state.get(feed_limit_key, DEFAULT_FEED_PAGE_SIZE)

                if search_query or (curr_rating and curr_rating != "Alle Bewertungen"):
                    visible_items = f_items
                else:
                    visible_items = f_items[:current_feed_limit]

                feed_is_open = True if (
                    is_filtering
                    or (qp_feed and feed_name.strip().lower() == qp_feed.lower())
                    or bool(st.session_state.get("chk_expand_feeds", False))
                    or feed_name in st.session_state.get("persisted_open_feeds", set())
                ) else False

                with st.expander(f"📡 **{feed_name}** ({len(f_items)} Artikel)", expanded=feed_is_open):
                    st.html(f'<div id="anchor-feed-{feed_slug}" style="height:0; margin:0; padding:0;"></div>')
                    cols = st.columns(2)
                    for idx, item in enumerate(visible_items):
                        displayed_count += 1
                        with cols[idx % 2]:
                            with st.container(border=True):
                                item_url = (item.get("link") or "").strip()
                                clean_title = clean_html_text(item.get("title", "Kein Titel"))
                                clean_summary = format_summary_html(item.get("summary", ""))
                                pdate = format_article_date(item)
                                date_str = (
                                    f"<div style='font-size:0.8rem; color:#64748b; margin-top:0.2rem; margin-bottom:0.35rem;'>🕒 {pdate}</div>"
                                    if pdate
                                    else ""
                                )
                                summary_str = (
                                    f"<div style='font-size:0.88rem; line-height:1.45; margin-bottom:0.75rem;'>{clean_summary}</div>"
                                    if clean_summary
                                    else "<div style='margin-bottom:0.5rem;'></div>"
                                )
                                st.markdown(
                                    f"**[{clean_title}]({item['link']})**\n\n{date_str}{summary_str}",
                                    unsafe_allow_html=True,
                                )

                                cur_fb = st.session_state.get("feedback_map", {}).get(item_url, item.get("feedback", 0))
                                default_fb = 1 if cur_fb == 1 else (0 if cur_fb == -1 else None)
                                item_url_hash = hashlib.md5(item_url.encode("utf-8")).hexdigest()[:12] if item_url else f"item_{displayed_count}"
                                fb_key = f"fb_{item_url_hash}"
                                read_key = f"read_{item_url_hash}"
                                if fb_key in rendered_element_keys:
                                    dup_cnt = 1
                                    while f"{fb_key}_{dup_cnt}" in rendered_element_keys:
                                        dup_cnt += 1
                                    fb_key = f"{fb_key}_{dup_cnt}"
                                rendered_element_keys.add(fb_key)
                                if read_key in rendered_element_keys:
                                    dup_cnt = 1
                                    while f"{read_key}_{dup_cnt}" in rendered_element_keys:
                                        dup_cnt += 1
                                    read_key = f"{read_key}_{dup_cnt}"
                                rendered_element_keys.add(read_key)

                                col_fb, col_read = st.columns([1, 1], vertical_alignment="center", wrap=False)
                                with col_fb:
                                    st.feedback(
                                        "thumbs",
                                        key=fb_key,
                                        default=default_fb,
                                        on_change=on_article_feedback_change,
                                        args=(item_url, fb_key, clean_title),
                                    )
                                with col_read:
                                    st.button(
                                        "",
                                        icon=":material/check:",
                                        key=read_key,
                                        type="tertiary",
                                        help="Artikel als gelesen markieren & archivieren",
                                        on_click=on_article_read_and_archive,
                                        args=(item, category, feed_name),
                                    )

                    if len(f_items) > len(visible_items):
                        remaining_count = len(f_items) - len(visible_items)
                        batch_count = min(DEFAULT_FEED_PAGE_SIZE, remaining_count)
                        c_m1, c_m2, c_m3 = st.columns([1, 2, 1])
                        with c_m2:
                            if st.button(
                                f"▼ Weitere {batch_count} von {remaining_count} Artikeln laden",
                                key=f"btn_more_{feed_slug}",
                                use_container_width=True,
                                help="Lädt weitere Artikel dieser Quelle in die Ansicht",
                            ):
                                st.session_state[feed_limit_key] = current_feed_limit + DEFAULT_FEED_PAGE_SIZE
                                if "persisted_open_feeds" not in st.session_state:
                                    st.session_state["persisted_open_feeds"] = set()
                                st.session_state["persisted_open_feeds"].add(feed_name)
                                st.rerun()

    if "last_read_feed_slug" in st.session_state:
        target_slug = st.session_state.pop("last_read_feed_slug")
        embed_client_script(f"""
        (function() {{
            setTimeout(function() {{
                var el = document.getElementById("anchor-feed-{target_slug}");
                if (el) {{
                    el.scrollIntoView({{ behavior: 'instant', block: 'nearest' }});
                }}
            }}, 30);
        }})();
        """)

    with col_stat_placeholder:
        if displayed_count > 0:
            st.caption(f"Zeige **{displayed_count}** Artikel der letzten 24 Stunden in **{categories_rendered}** Kategorien")
        else:
            if selected_feed != "Alle Feeds":
                st.warning(f"Keine Artikel für den Feed '{selected_feed}' gefunden (0 Treffer).")
            elif selected_cat != "Alle Kategorien":
                st.warning(f"Keine Artikel für die Kategorie '{selected_cat}' gefunden (0 Treffer).")
            else:
                st.warning("Keine aktuellen Artikel gefunden, die den Suchkriterien entsprechen (0 Treffer).")
