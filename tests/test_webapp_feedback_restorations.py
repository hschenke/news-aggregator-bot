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
        """Articles tab must sort categories alphabetically and articles oldest first, with clean caption."""
        self.assertIn("sorted(news_data.keys(), key=lambda x: x.strip().lower())", self.articles_tab_py)
        self.assertIn("reverse=False", self.articles_tab_py)
        self.assertIn('st.caption(f"Zeige **{displayed_count}** Artikel in **{categories_rendered}** Kategorien")', self.articles_tab_py)
        self.assertNotIn("der letzten 24 Stunden", self.articles_tab_py)

    def test_ki_tab_models_prompts_and_state(self) -> None:
        """KI tab must support Gemini 3.8-3.5 models with 3.5-flash-lite default, prompt editing, and disabled button."""
        self.assertIn("gemini-3.5-flash-lite", AVAILABLE_GEMINI_MODELS)
        self.assertIn("gemini-3.8-flash", AVAILABLE_GEMINI_MODELS)
        self.assertIn("AVAILABLE_GEMINI_MODELS", self.ki_tab_py)
        self.assertIn("default_model = \"gemini-3.5-flash-lite\"", self.ki_tab_py)
        self.assertIn("input_ki_main_prompt", self.ki_tab_py)
        self.assertIn("input_ki_prompt_directives", self.ki_tab_py)
        self.assertIn("disabled=is_generating", self.ki_tab_py)
        # Tailored admin message
        self.assertIn("Klicke oben auf 'Neues Briefing generieren'", self.ki_tab_py)

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
        self.assertIn('buttons[i].setAttribute("disabled", "true")', self.styles_py)

    def test_manage_tab_collapsible_sections_and_no_unnecessary_toast_text(self) -> None:
        """Categories and Add Feed must be collapsible and collapsed by default; toast must omit redundant sentence."""
        self.assertIn('with st.expander("📁 Kategorien verwalten", expanded=False):', self.manage_tab_py)
        self.assertIn('with st.expander("➕ Neuen RSS-Feed hinzufügen", expanded=False):', self.manage_tab_py)
        self.assertNotIn("Der Bearbeiten-Block bleibt geöffnet", self.manage_tab_py)
        self.assertIn("manage_notice", self.manage_tab_py)
        # Discard resets widget keys and triggers reload
        self.assertIn("window.location.reload()", self.manage_tab_py)

    def test_prominent_notices_in_tabs(self) -> None:
        """KI and Feedly tabs must display prominent notice banners when actions complete."""
        self.assertIn("ki_notice", self.ki_tab_py)
        self.assertIn("feedly_notice", self.feedly_tab_py)

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


if __name__ == "__main__":
    unittest.main()
