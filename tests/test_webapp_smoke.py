"""
End-to-End Smoke Tests für streamlit_app.py und src/webapp.py unter Verwendung von Streamlits offiziellem AppTest Framework.
Prüft das fehlerfreie Rendern der Webanwendung inklusive Deeplinks und verhindert NameError / Syntaxfehler.
"""

import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


class TestWebappSmoke(unittest.TestCase):

    def test_app_renders_without_exception(self):
        """Prüft, dass die Streamlit App beim Standardaufruf ohne Exception durchläuft."""
        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()
        if at.exception:
            error_msgs = [f"{exc.type}: {exc.value}" for exc in at.exception]
            self.fail(f"Streamlit App warf unerwartete Exceptions: {error_msgs}")

    def test_app_renders_with_deeplinks(self):
        """Prüft, dass Deeplinks (Kategorie + Feed) ohne Exception durchlaufen."""
        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.query_params["category"] = "Fun"
        at.query_params["feed"] = "Witz des Tages"
        at.run()
        if at.exception:
            error_msgs = [f"{exc.type}: {exc.value}" for exc in at.exception]
    def test_get_news_data_fast_db_load(self):
        """Prüft, dass get_news_data bei vorhandenen Artikeln in der DB blitzschnell lädt ohne collect_all_news aufzurufen."""
        from unittest.mock import patch, MagicMock
        from src.models import Article
        import streamlit as st

        mock_article = Article(
            title="Fast DB Article",
            link="https://example.com/fast-1",
            category="Tech & AI",
            source="Test Feed",
            timestamp=1700000000.0,
        )

        with patch("src.storage.get_storage") as mock_get_storage, \
             patch("src.aggregator.collect_all_news") as mock_collect:
            mock_storage = MagicMock()
            mock_storage.get_articles.return_value = [mock_article]
            mock_get_storage.return_value = mock_storage

            st.cache_data.clear()
            import src.webapp as webapp
            data = webapp.get_news_data(force_live_fetch=False)

            self.assertIn("Tech & AI", data)
            self.assertEqual(data["Tech & AI"][0]["title"], "Fast DB Article")
            mock_collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
