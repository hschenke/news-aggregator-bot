"""
Tests für Performance-Optimierungen:
1. Keine Toasts mehr bei Like / Dislike und Gelesen-Aktionen.
2. Asynchrone Datenbank-Persistierung von Nutzer-Feedback über Hintergrund-Threads.
3. CSS-Regeln zur Vermeidung des 1-3 sekündigen Ergrauens / Verblassens (Stale State Opacity).
4. LRU-Cache für clean_html_text und format_summary_html.
"""

import unittest
from pathlib import Path
from src.aggregator import clean_html_text, format_summary_html


class TestPerformanceFeedbackOptimizations(unittest.TestCase):

    def setUp(self):
        self.articles_tab_code = Path("src/ui/tabs/articles_tab.py").read_text(encoding="utf-8")
        self.styles_code = Path("src/ui/styles.py").read_text(encoding="utf-8")

    def test_no_toasts_in_feedback_and_read_callbacks(self):
        """Stellt sicher, dass bei Like/Dislike und Gelesen keine st.toast() Aufrufe mehr existieren."""
        feedback_func_start = self.articles_tab_code.find("def on_article_feedback_change(")
        read_func_start = self.articles_tab_code.find("def on_article_read_and_archive(")
        render_start = self.articles_tab_code.find("def render_articles_tab(")

        self.assertNotEqual(feedback_func_start, -1)
        self.assertNotEqual(read_func_start, -1)
        self.assertNotEqual(render_start, -1)

        feedback_code = self.articles_tab_code[feedback_func_start:read_func_start]
        read_code = self.articles_tab_code[read_func_start:render_start]

        # Keine st.toast Aufrufe in beiden Callbacks
        self.assertNotIn("st.toast", feedback_code, "In on_article_feedback_change darf kein st.toast vorkommen!")
        self.assertNotIn("st.toast", read_code, "In on_article_read_and_archive darf kein st.toast vorkommen!")

    def test_async_feedback_persistence(self):
        """Stellt sicher, dass das Speichern von Like/Dislike nicht-blockierend im Hintergrund läuft."""
        feedback_func_start = self.articles_tab_code.find("def on_article_feedback_change(")
        read_func_start = self.articles_tab_code.find("def on_article_read_and_archive(")
        feedback_code = self.articles_tab_code[feedback_func_start:read_func_start]

        self.assertIn("persist_feedback_async", feedback_code)

    def test_anti_stale_greying_css_rules(self):
        """Stellt sicher, dass CSS-Regeln gegen das Ergrauen bei Reruns aktiv sind."""
        # Stale Container Opacity Override
        self.assertIn('[data-stale="true"]', self.styles_code)
        self.assertIn('[data-testid="stElementContainer"][data-stale="true"]', self.styles_code)
        self.assertIn('[data-testid="stVerticalBlockBorderWrapper"][data-stale="true"]', self.styles_code)
        self.assertIn('opacity: 1 !important;', self.styles_code)
        self.assertIn('transition: none !important;', self.styles_code)

        # Disabled Button Opacity Override
        self.assertIn('[data-testid="stFeedback"] button:disabled', self.styles_code)
        self.assertIn('div[class*="st-key-read_"] button:disabled', self.styles_code)

    def test_lru_caching_on_html_cleaning_functions(self):
        """Stellt sicher, dass clean_html_text und format_summary_html memoized sind."""
        self.assertTrue(hasattr(clean_html_text, "cache_info"), "clean_html_text muss mit @lru_cache dekoriert sein")
        self.assertTrue(hasattr(format_summary_html, "cache_info"), "format_summary_html muss mit @lru_cache dekoriert sein")

        # Test Cache Hits
        info_before = clean_html_text.cache_info()
        clean_html_text("<b>Performance Test</b>")
        clean_html_text("<b>Performance Test</b>")
        info_after = clean_html_text.cache_info()
        self.assertGreater(info_after.hits, info_before.hits)


if __name__ == "__main__":
    unittest.main()
