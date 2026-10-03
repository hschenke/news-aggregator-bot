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
        """Prüft, dass get_news_data bei vorhandenen Artikeln in der DB schnell lädt ohne collect_all_news aufzurufen."""
        from unittest.mock import patch, MagicMock
        from src.models import Article
        from src.ui.state import get_news_data
        import streamlit as st
        import time

        mock_article = Article(
            title="Fast DB Article",
            link="https://example.com/fast-1",
            category="Tech & AI",
            source="Test Feed",
            timestamp=time.time(),
        )

        with patch("src.ui.state.get_storage") as mock_get_storage, \
             patch("src.ui.state.collect_all_news") as mock_collect:
            mock_storage = MagicMock()
            mock_storage.get_articles.return_value = [mock_article]
            mock_get_storage.return_value = mock_storage

            get_news_data.clear()
            st.cache_data.clear()
            data = get_news_data(force_live_fetch=False)

            self.assertIn("Tech & AI", data)
            self.assertEqual(data["Tech & AI"][0]["title"], "Fast DB Article")
            mock_collect.assert_not_called()

    def test_unconfigured_categories_and_test_articles_ignored(self):
        """Prüft, dass unkonfigurierte Kategorien (z. B. Allgemein) und Test-Dummies herausgefiltert werden."""
        from unittest.mock import patch, MagicMock
        from src.models import Article
        from src.ui.state import get_news_data
        import streamlit as st
        import time
        now = time.time()

        articles = [
            Article(title="Title 1", link="https://example.com/test-1", category="", source="", timestamp=now),
            Article(title="Dummy Allgemein", link="https://example.com/dummy", category="Allgemein", source="", timestamp=now),
            Article(title="Echter Tech Artikel", link="https://heise.de/news-123", category="Tech & AI", source="Heise Online News", timestamp=now),
        ]

        with patch("src.ui.state.get_storage") as mock_get_storage, \
             patch("src.ui.state.collect_all_news") as mock_collect:

            mock_storage = MagicMock()
            mock_storage.get_articles.return_value = articles
            mock_get_storage.return_value = mock_storage

            get_news_data.clear()
            st.cache_data.clear()
            data = get_news_data(force_live_fetch=False)

            self.assertNotIn("Allgemein", data)
            self.assertNotIn("", data)
            self.assertIn("Tech & AI", data)
            self.assertEqual(len(data["Tech & AI"]), 1)
            mock_collect.assert_not_called()

    def test_authenticated_app_renders(self):
        """Prüft das fehlerfreie Rendern des Dashboards im authentifizierten Zustand."""
        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.session_state["authenticated"] = True
        at.session_state["auth_role"] = "admin"
        at.run()
        if at.exception:
            error_msgs = [f"{exc.type}: {exc.value}" for exc in at.exception]
            self.fail(f"Authentifizierte App warf Exceptions: {error_msgs}")
        self.assertFalse(at.exception)

    def test_logged_out_state_shows_login_form(self):
        """Prüft, dass bei logged_out=True das Login-Formular gerendert und Auto-Logins ignoriert werden."""
        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.session_state["logged_out"] = True
        at.session_state["authenticated"] = False
        at.run()
        if at.exception:
            error_msgs = [f"{exc.type}: {exc.value}" for exc in at.exception]
            self.fail(f"Logout-Zustand warf Exceptions: {error_msgs}")
        # Prüfen, dass das Passwort-Feld gerendert wird
        password_inputs = [inp for inp in at.text_input if "Passwort" in (inp.label or "")]
        self.assertTrue(len(password_inputs) > 0, "Login-Formular sollte nach Logout angezeigt werden")

    def test_direct_background_persistence(self):
        """Prüft, dass Hintergrund-Threads für Feedback und Gelesen asynchron gestartet werden."""
        from unittest.mock import patch, MagicMock
        from src.ui.background import persist_feedback_async, persist_read_and_archive_async

        with patch("src.ui.background.get_storage") as mock_get_storage:
            mock_storage = MagicMock()
            mock_get_storage.return_value = mock_storage

            thread = persist_feedback_async("https://example.com/bg-test", 1, "Bg Test")
            thread.join(timeout=2.0)
            mock_storage.set_feedback.assert_called_with("https://example.com/bg-test", 1, "Bg Test")

            art_dict = {"title": "Read Test", "link": "https://example.com/read-test", "category": "Tech"}
            read_thread = persist_read_and_archive_async(art_dict)
            read_thread.join(timeout=2.0)
            self.assertTrue(mock_storage.archive_article.called)



if __name__ == "__main__":
    unittest.main()
