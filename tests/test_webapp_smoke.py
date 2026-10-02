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

    def test_unconfigured_categories_and_test_articles_ignored(self):
        """Prüft, dass unkonfigurierte Kategorien (z. B. Allgemein) und Test-Dummies herausgefiltert werden."""
        from unittest.mock import patch, MagicMock
        from src.models import Article
        import streamlit as st

        articles = [
            Article(title="Title 1", link="https://example.com/test-1", category="", source=""),
            Article(title="Dummy Allgemein", link="https://example.com/dummy", category="Allgemein", source=""),
            Article(title="Echter Tech Artikel", link="https://heise.de/news-123", category="Tech & AI", source="Heise Online News"),
        ]

        with patch("src.storage.get_storage") as mock_get_storage, \
             patch("src.aggregator.collect_all_news") as mock_collect:
            mock_storage = MagicMock()
            mock_storage.get_articles.return_value = articles
            mock_get_storage.return_value = mock_storage

            st.cache_data.clear()
            import src.webapp as webapp
            data = webapp.get_news_data(force_live_fetch=False)

            self.assertNotIn("Allgemein", data)
            self.assertNotIn("", data)
            self.assertIn("Tech & AI", data)
            self.assertEqual(len(data["Tech & AI"]), 1)
            mock_collect.assert_not_called()

    def test_authenticated_app_renders(self):
        """Prüft das fehlerfreie Rendern des Dashboards im authentifizierten Zustand inklusive Aktions-Puffer."""
        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.session_state["authenticated"] = True
        at.session_state["auth_role"] = "admin"
        at.run()
        if at.exception:
            error_msgs = [f"{exc.type}: {exc.value}" for exc in at.exception]
            self.fail(f"Authentifizierte App warf Exceptions: {error_msgs}")
        # Prüfen, dass der Synchronisieren-Button vorhanden ist
        sync_btns = [b for b in at.button if b.key == "btn_sync_buffer_now"]
        self.assertTrue(len(sync_btns) > 0, "Button btn_sync_buffer_now sollte im Artikel-Tab gerendert werden")


if __name__ == "__main__":
    unittest.main()
