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

    def test_action_buffer_singleton_persistence(self):
        """Prüft, dass der Aktions-Puffer thread-sicher und persistent in builtins erhalten bleibt."""
        from src.action_buffer import get_action_buffer
        buf = get_action_buffer()
        buf.clear()
        self.assertEqual(buf.get_pending_counts(), (0, 0))

        test_item = {
            "title": "Buffer Test Artikel",
            "link": "https://example.com/buffer-test-1",
            "category": "Tech & AI",
        }
        buf.queue_read(test_item)
        buf.queue_feedback("https://example.com/buffer-test-1", 1, "Buffer Test Artikel")

        # Zweiter Abruf der Singleton-Instanz
        buf2 = get_action_buffer()
        self.assertIs(buf, buf2, "get_action_buffer muss die identische Singleton-Instanz zurückgeben")
        reads_cnt, fb_cnt = buf2.get_pending_counts()
        self.assertEqual(reads_cnt, 1)
        self.assertEqual(fb_cnt, 1)

        # Test: Feedback zurück auf neutral (0) setzen -> muss aus dem Puffer verschwinden
        buf.queue_feedback("https://example.com/buffer-test-1", 0, "Buffer Test Artikel", persisted_feedback=0)
        reads_cnt, fb_cnt = buf.get_pending_counts()
        self.assertEqual(fb_cnt, 0, "Feedback auf neutral (0) muss Eintrag aus Puffer entfernen")

        # Test: Explizites unqueue_feedback
        buf.queue_feedback("https://example.com/buffer-test-2", 1, "Artikel 2")
        self.assertEqual(buf.get_pending_counts()[1], 1)
        self.assertTrue(buf.unqueue_feedback("https://example.com/buffer-test-2"))
        self.assertEqual(buf.get_pending_counts()[1], 0)
        buf.clear()


if __name__ == "__main__":
    unittest.main()
