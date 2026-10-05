"""
Unit tests verifying the UI restorations, alignments, and cleanup requested for v0.10.1.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.summarizer import AVAILABLE_GEMINI_MODELS


class TestWebappFeedbackRestorations(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent.parent
        self.webapp_py = (self.root / "src" / "webapp.py").read_text(encoding="utf-8")
        self.styles_py = (self.root / "src" / "ui" / "styles.py").read_text(encoding="utf-8")
        self.articles_tab_py = (self.root / "src" / "ui" / "tabs" / "articles_tab.py").read_text(encoding="utf-8")
        self.ki_tab_py = (self.root / "src" / "ui" / "tabs" / "ki_tab.py").read_text(encoding="utf-8")
        self.manage_tab_py = (self.root / "src" / "ui" / "tabs" / "manage_tab.py").read_text(encoding="utf-8")
        self.feedly_tab_py = (self.root / "src" / "ui" / "tabs" / "feedly_tab.py").read_text(encoding="utf-8")

    def test_sidebar_caption_and_reload_button(self) -> None:
        """Sidebar caption must be shortened to '24h Newsfeed', and reload feeds button restored."""
        self.assertIn('st.sidebar.caption("24h Newsfeed")', self.webapp_py)
        self.assertNotIn("Kompakter News-Aggregator & 24h Newsfeed", self.webapp_py)
        self.assertIn("sb_btn_refresh_feeds", self.webapp_py)
        self.assertIn("🔄 Feeds neu laden", self.webapp_py)
        # Mark seen button must be gone
        self.assertNotIn("sb_btn_mark_seen", self.webapp_py)
        # Version badge behind News Bot must be present with proper spacing and NO inline styles in webapp.py
        self.assertIn("app_version = get_app_version()", self.webapp_py)
        self.assertIn("{app_version}", self.webapp_py)
        self.assertNotIn('style="display:flex', self.webapp_py)
        self.assertNotIn('style="margin:0', self.webapp_py)
        self.assertIn(".sidebar-header-container", self.styles_py)
        self.assertIn(".sidebar-version-badge", self.styles_py)
        self.assertIn("margin-left: 10px !important", self.styles_py)
        # Reload feeds button must only be available in admin mode
        self.assertIn("if is_admin:", self.webapp_py)
        self.assertIn("key=\"sb_btn_refresh_feeds\"", self.webapp_py)
        self.assertTrue(self.webapp_py.find("if is_admin:") < self.webapp_py.find("key=\"sb_btn_refresh_feeds\""))

    def test_styles_read_button_right_alignment_and_thumbs_colors(self) -> None:
        """CSS must ensure last-child column alignment and green/red thumbs colors."""
        self.assertIn("#16a34a", self.styles_py)
        self.assertIn("#dc2626", self.styles_py)
        self.assertIn("justify-content: flex-end !important", self.styles_py)
        self.assertIn("margin-left: auto !important", self.styles_py)
        # Ensure kpi-chip has proper closing brace
        self.assertIn(".kpi-chip {", self.styles_py)
        self.assertIn("background-color: rgba(128, 128, 128, 0.1);", self.styles_py)

    def test_articles_tab_alphabetical_and_oldest_first(self) -> None:
        """Articles tab must sort categories alphabetically and articles oldest first, with clean caption and no spurious warning."""
        self.assertIn("sorted(news_data.keys(), key=lambda x: x.strip().lower())", self.articles_tab_py)
        self.assertIn("reverse=False", self.articles_tab_py)
        self.assertIn('st.caption(f"Zeige **{displayed_count}** Artikel in **{categories_rendered}** Kategorien")', self.articles_tab_py)
        self.assertNotIn("der letzten 24 Stunden", self.articles_tab_py)
        # Ensure warnings are strictly rendered in an else-branch when displayed_count is 0
        self.assertIn("if displayed_count > 0:\n            st.caption(f\"Zeige **{displayed_count}** Artikel in **{categories_rendered}** Kategorien\")\n        else:", self.articles_tab_py)

    def test_ki_tab_models_prompts_and_state(self) -> None:
        """KI tab must support Gemini 3.8-3.5 models with 3.5-flash-lite default, prompt editing, and disabled button."""
        self.assertIn("gemini-3.5-flash-lite", AVAILABLE_GEMINI_MODELS)
        self.assertIn("gemini-3.8-flash", AVAILABLE_GEMINI_MODELS)
        self.assertIn("AVAILABLE_GEMINI_MODELS", self.ki_tab_py)
        self.assertIn("default_model = \"gemini-3.5-flash-lite\"", self.ki_tab_py)
        self.assertIn("input_ki_main_prompt", self.ki_tab_py)
        self.assertIn("input_ki_prompt_directives", self.ki_tab_py)
        self.assertIn("disabled=is_generating", self.ki_tab_py)
        # Concise briefing message
        self.assertIn("Aktuell nichts neues generiert.", self.ki_tab_py)

    def test_manage_tab_no_purge_and_disabled_save_when_no_changes(self) -> None:
        """Manage tab must not have purge block, and save button must be disabled when no changes."""
        self.assertNotIn("purge_tables", self.manage_tab_py)
        self.assertNotIn("btn_confirm_db_purge", self.manage_tab_py)
        self.assertIn("disabled=btn_save_disabled", self.manage_tab_py)
        self.assertIn("btn_save_label = \"💾 Jetzt sichern\" if has_unsaved_changes else \"💾 Gespeichert\"", self.manage_tab_py)
        # Feed edit block retains state
        self.assertIn("editing_feed_key", self.manage_tab_py)

    def test_feedly_tab_only_browser_button_and_font_size(self) -> None:
        """Feedly tab must only provide 'Im Browser öffnen', disable during actions, and format count in bold."""
        self.assertIn("st.link_button(\"↗️ Im Browser öffnen\"", self.feedly_tab_py)
        self.assertNotIn("📥 XML herunterladen", self.feedly_tab_py)
        self.assertNotIn("➕ Zu Feedly hinzufügen", self.feedly_tab_py)
        self.assertNotIn("frisch", self.feedly_tab_py)
        # Bold numbers instead of code backticks (Bild 5 fix)
        self.assertIn("— **{all_count}** Artikel", self.feedly_tab_py)
        self.assertIn("— **{briefing_count}** Eintrag / Top-Meldungen", self.feedly_tab_py)
    def test_loading_overlay_and_button_disabling(self) -> None:
        """Loading overlay CSS and JS click interceptor must exist to disable UI and show spinner."""
        self.assertIn("#news-bot-loading-overlay", self.styles_py)
        self.assertIn(".action-spinner-circle", self.styles_py)
        self.assertIn(".action-spinner-title", self.styles_py)
        self.assertIn("function showActionOverlay(title, subtitle)", self.styles_py)
        # Full-screen backdrop intercepts pointer events
        self.assertIn("pointer-events: all !important", self.styles_py)
        self.assertIn("button:disabled", self.styles_py)

    def test_manage_tab_collapsible_sections_and_no_unnecessary_toast_text(self) -> None:
        """Categories and Add Feed must be collapsible and collapsed by default; toast must omit redundant sentence."""
        self.assertIn('with st.expander("📁 Kategorien verwalten", expanded=False):', self.manage_tab_py)
        self.assertIn('with st.expander("➕ Neuen RSS-Feed hinzufügen", expanded=False):', self.manage_tab_py)
        self.assertNotIn("Der Bearbeiten-Block bleibt geöffnet", self.manage_tab_py)
        self.assertIn("manage_notice", self.manage_tab_py)
        # Discard resets widget keys and triggers reload
        self.assertIn("window.location.reload()", self.manage_tab_py)

    def test_prominent_notices_in_tabs(self) -> None:
        """KI, Feedly, and Manage tabs must use client-side instant dismissible notice banners."""
        self.assertIn("render_dismissible_notice", self.manage_tab_py)
        self.assertIn("embed_client_script", self.manage_tab_py)
        self.assertIn("render_dismissible_notice", self.ki_tab_py)
        self.assertIn("render_dismissible_notice", self.feedly_tab_py)
        self.assertNotIn('st.success("RSS-Feeds erfolgreich zu GitHub & CDN synchronisiert!")', self.feedly_tab_py)
        self.assertIn("render_dismissible_notice", self.styles_py)
        self.assertIn(".persistent-dismissible-notice", self.styles_py)
        self.assertIn(".notice-close-btn", self.styles_py)
        # High contrast readable color for light mode and auto-dismiss timer
        self.assertIn("#065f46", self.styles_py)
        self.assertIn("handleNoticeClose", self.styles_py)
        self.assertIn("10000", self.styles_py)

    def test_toast_removal_and_overlay_release(self) -> None:
        """st.toast must be completely eliminated across all UI modules and overlay auto-released."""
        auth_py = (self.root / "src" / "ui" / "auth.py").read_text(encoding="utf-8")
        self.assertNotIn("st.toast", self.manage_tab_py, "manage_tab.py must not contain any st.toast calls")
        self.assertNotIn("st.toast", self.ki_tab_py, "ki_tab.py must not contain any st.toast calls")
        self.assertNotIn("st.toast", self.feedly_tab_py, "feedly_tab.py must not contain any st.toast calls")
        self.assertNotIn("st.toast", self.webapp_py, "webapp.py must not contain any st.toast calls")
        self.assertNotIn("st.toast", auth_py, "auth.py must not contain any st.toast calls")

        # Global toast CSS suppression
        self.assertIn('[data-testid="stToast"]', self.styles_py)
        self.assertIn("display: none !important", self.styles_py)

        # Overlay release mechanics
        self.assertIn("hideActionOverlay", self.styles_py)
        self.assertIn("release_action_overlay", self.styles_py)
        self.assertIn("release_action_overlay()", self.webapp_py)

    def test_overlay_safety_timeout_at_least_30s(self) -> None:
        """Action overlay fallback timeout must be >= 30000ms (35s)."""
        self.assertIn("35000", self.styles_py)

    def test_header_status_and_no_slang(self) -> None:
        """Header status line under Daily News Briefing must show Stand and Artikel verfügbar; no slang 'frisch' in webapp."""
        self.assertIn('st.title("📰 Daily News", anchor=False)', self.webapp_py)
        self.assertIn("🕒 Stand:", self.webapp_py)
        self.assertIn("Artikel verfügbar", self.webapp_py)
        self.assertIn("🕒 Last:", self.webapp_py)
        self.assertNotIn("frisch", self.webapp_py)
        self.assertNotIn("frisch", self.styles_py)

    def test_displayed_count_matches_categories_and_last_update_ts(self) -> None:
        """Displayed count must match category totals, and timestamp must be resolved effectively."""
        self.assertIn("displayed_count += len(cat_matching)", self.articles_tab_py)
        self.assertIn("get_effective_last_update_ts", self.webapp_py)
        main_py = (self.root / "src" / "main.py").read_text(encoding="utf-8")
        self.assertIn('storage.set_metadata("last_feed_refresh_time", str(time.time()))', main_py)

    def test_filter_search_rating_removed_and_reset_buttons(self) -> None:
        """Rating dropdown must be removed, search clear button must be 'X', and category/feed reset button must exist."""
        self.assertNotIn("sel_articles_rating", self.articles_tab_py)
        self.assertIn('st.button("X", key="btn_search_clear"', self.articles_tab_py)
        self.assertIn('key="btn_reset_cat_feed"', self.articles_tab_py)
        self.assertIn("def on_reset_category_and_feed()", self.articles_tab_py)

    def test_compact_layout_and_shortened_texts(self) -> None:
        """Verifies balanced CSS rules, divider spacing, and concise status texts without '(gespeichert)'."""
        # CSS rules for balanced spacing
        self.assertIn('hr, [data-testid="stDivider"], .stMarkdown hr', self.styles_py)
        self.assertIn('margin-top: 0.65rem !important;', self.styles_py)
        self.assertIn('margin-bottom: 0.65rem !important;', self.styles_py)
        self.assertIn('section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]', self.styles_py)
        self.assertIn('gap: 0.45rem !important;', self.styles_py)
        self.assertIn('[data-testid="stAlert"]', self.styles_py)
        self.assertIn('padding: 0.5rem 0.8rem !important;', self.styles_py)

        # Sidebar dividers above navigation and before refresh feeds
        self.assertIn('st.sidebar.caption("24h Newsfeed")', self.webapp_py)
        self.assertIn('st.sidebar.markdown("---")', self.webapp_py)

        # Concise text in manage_tab
        self.assertIn("Alle Feeds & Einstellungen sind aktuell.", self.manage_tab_py)
        self.assertNotIn("(gespeichert)", self.manage_tab_py)
        self.assertIn("Ungespeicherte Änderungen.", self.manage_tab_py)
        self.assertIn("Kategorien, Feeds und Einstellungen verwalten.", self.manage_tab_py)

        # Concise text in feedly_tab
        self.assertIn("RSS 2.0 XML-Feeds für Feedly, Inoreader und alle Newsreader.", self.feedly_tab_py)
        self.assertIn("Feeds erfolgreich neu generiert.", self.feedly_tab_py)


if __name__ == "__main__":
    unittest.main()
