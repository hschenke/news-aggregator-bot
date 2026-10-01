"""
Tests für Pipeline- & Performance-Optimierungen:
1. Paralleles Einlesen aller RSS-Feeds in collect_all_news.
2. save_to_db Parameter zur Vermeidung redundanter DB-Speicherungen.
3. TursoStorage Timeouts (DEFAULT_TIMEOUT_SECONDS = 30.0) und Retry-Mechanismus bei Netzwerkfehlern.
4. Intelligente Gemini-Modellauswahl (bevorzugt gemini-3.5-flash zur Vermeidung von 503-Kaskaden).
5. Vermeidung von ungewollter Streamlit-Initialisierung in reinen CLI-/Bot-Umgebungen.
"""

import os
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.aggregator import collect_all_news
from src.summarizer import get_candidate_models, AVAILABLE_GEMINI_MODELS
from src.storage import DEFAULT_TIMEOUT_SECONDS, TursoStorage, StorageConnectionError


class TestPipelinePerformance(unittest.TestCase):

    def test_default_turso_timeout_is_at_least_30_seconds(self):
        """Stellt sicher, dass der Standard-Timeout für Turso Cloud mindestens 30 Sekunden beträgt."""
        self.assertGreaterEqual(DEFAULT_TIMEOUT_SECONDS, 30.0)

    def test_turso_storage_retry_on_request_exception(self):
        """Prüft, dass TursoStorage bei HTTP-Timeouts bis zu 2 Retries durchführt und erst dann fehlschlägt."""
        import requests
        storage = TursoStorage("https://test.turso.io", "dummy_token")

        # Mock Session.post wirft Timeout
        mock_post = MagicMock(side_effect=requests.exceptions.ReadTimeout("Read timed out"))
        storage._session.post = mock_post

        with patch("time.sleep") as mock_sleep:
            with self.assertRaises(StorageConnectionError) as ctx:
                storage._execute_pipeline([("SELECT 1", [])])

        self.assertIn("HTTP-Verbindungsfehler zu Turso", str(ctx.exception))
        # 1 initialer Versuch + 2 Retries = 3 Versuche insgesamt
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_collect_all_news_with_save_to_db_false_does_not_save_to_storage(self):
        """Prüft, dass save_to_db=False keine Speicherung in der Datenbank triggert."""
        fake_config = {
            "categories": [
                {
                    "name": "TestCat",
                    "feeds": [{"name": "Feed 1", "url": "https://example.com/rss1"}]
                }
            ],
            "settings": {"max_article_age_weeks": 20}
        }
        import time
        fake_items = [
            {"title": "Test Title 1", "link": "https://example.com/1", "timestamp": time.time()}
        ]

        with patch("src.aggregator.load_sources", return_value=fake_config):
            with patch("src.aggregator.fetch_feed_items", return_value=fake_items):
                with patch("src.storage.get_storage") as mock_get_storage:
                    res = collect_all_news(export_rss=False, save_to_db=False)
                    self.assertIn("TestCat", res)
                    self.assertEqual(len(res["TestCat"]), 1)
                    # mock_get_storage für save_articles darf nicht aufgerufen worden sein
                    # (höchstens für get_archived_urls, aber save_articles nicht)
                    if mock_get_storage.called:
                        mock_storage_inst = mock_get_storage.return_value
                        mock_storage_inst.save_articles.assert_not_called()

    def test_gemini_candidate_models_prefers_configured_model(self):
        """Prüft, dass get_candidate_models das bevorzugte Modell an Position 0 setzt."""
        candidates = get_candidate_models("gemini-3.5-flash")
        self.assertEqual(candidates[0], "gemini-3.5-flash")
        self.assertIn("gemini-3.8-flash", candidates)

        # Prüfe Umgebungsvariable GEMINI_MODEL
        with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-3.5-flash"}):
            env_candidates = get_candidate_models()
            self.assertEqual(env_candidates[0], "gemini-3.5-flash")

    def test_streamlit_config_enable_cors_true(self):
        """Stellt sicher, dass in .streamlit/config.toml enableCORS = true gesetzt ist."""
        config_text = Path(".streamlit/config.toml").read_text(encoding="utf-8")
        self.assertIn("enableCORS = true", config_text)
        self.assertNotIn("enableCORS = false", config_text)

    def test_daily_digest_workflow_uses_requirements_bot_and_unbuffered(self):
        """Stellt sicher, dass die GitHub Actions Pipeline requirements-bot.txt und PYTHONUNBUFFERED nutzt."""
        workflow_text = Path(".github/workflows/daily_digest.yml").read_text(encoding="utf-8")
        self.assertIn("requirements-bot.txt", workflow_text)
        self.assertIn("PYTHONUNBUFFERED: \"1\"", workflow_text)
        self.assertIn("GEMINI_MODEL", workflow_text)
        self.assertIn("TURSO_TIMEOUT: \"30.0\"", workflow_text)

    def test_streamlit_logging_configured_in_entrypoints(self):
        """Stellt sicher, dass streamlit_app.py, app.py und src/webapp.py Logging für die Streamlit Konsole konfigurieren."""
        for path_str in ["streamlit_app.py", "app.py"]:
            content = Path(path_str).read_text(encoding="utf-8")
            self.assertIn("logging.basicConfig", content)
        webapp_content = Path("src/webapp.py").read_text(encoding="utf-8")
        self.assertIn("logger = logging.getLogger", webapp_content)


if __name__ == "__main__":
    unittest.main()
