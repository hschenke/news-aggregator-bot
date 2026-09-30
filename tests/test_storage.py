"""
Unittests für das Storage-Modul (SqliteStorage, TursoStorage & get_storage Fallback).
"""

import unittest
from unittest.mock import patch, MagicMock
from src.models import Article
from src.storage import (
    SqliteStorage,
    TursoStorage,
    get_storage,
    get_safe_db_path,
)
from src.exceptions import StorageError, StorageConnectionError


class TestSqliteStorage(unittest.TestCase):
    def setUp(self):
        self.storage = SqliteStorage(":memory:")
        self.storage.init_db()

    def test_save_and_retrieve_articles(self):
        articles = [
            Article(
                title="Artikel 1",
                link="https://example.com/art1",
                summary="Zusammenfassung 1",
                source="Source A",
                category="Tech",
                timestamp=1700000000.0,
                feedback=1,
            ),
            Article(
                title="Artikel 2",
                link="https://example.com/art2",
                summary="Zusammenfassung 2",
                source="Source B",
                category="Wirtschaft",
                timestamp=1700001000.0,
                feedback=0,
            ),
        ]
        saved = self.storage.save_articles(articles)
        self.assertEqual(saved, 2)

        fetched = self.storage.get_articles()
        self.assertEqual(len(fetched), 2)
        # Sortiert nach timestamp DESC -> Artikel 2 zuerst
        self.assertEqual(fetched[0].link, "https://example.com/art2")
        self.assertEqual(fetched[1].link, "https://example.com/art1")
        self.assertEqual(fetched[1].feedback, 1)

    def test_upsert_preserves_feedback_and_bookmark(self):
        art = Article(
            title="Ursprünglicher Titel",
            link="https://example.com/test",
            source="Source",
            category="News",
            feedback=1,
        )
        self.storage.save_articles([art])
        self.storage.set_bookmark("https://example.com/test", True)

        # Erneuter Fetch des Feeds mit aktualisiertem Titel, aber default feedback=0
        updated_art = Article(
            title="Aktualisierter Titel",
            link="https://example.com/test",
            source="Source",
            category="News",
            feedback=0,
        )
        self.storage.save_articles([updated_art])

        retrieved = self.storage.get_article("https://example.com/test")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.title, "Aktualisierter Titel")
        # Bestehendes Feedback und Bookmark müssen erhalten bleiben
        self.assertEqual(retrieved.feedback, 1)
        self.assertTrue(retrieved.get("is_bookmarked"))

    def test_filter_by_category_and_feedback(self):
        articles = [
            Article(title="T1", link="https://ex.com/1", category="Tech", feedback=1),
            Article(title="T2", link="https://ex.com/2", category="Tech", feedback=-1),
            Article(title="W1", link="https://ex.com/3", category="Wirtschaft", feedback=1),
        ]
        self.storage.save_articles(articles)

        tech_arts = self.storage.get_articles(category="Tech")
        self.assertEqual(len(tech_arts), 2)

        liked_arts = self.storage.get_articles(feedback=1)
        self.assertEqual(len(liked_arts), 2)

        liked_tech = self.storage.get_articles(category="Tech", feedback=1)
        self.assertEqual(len(liked_tech), 1)
        self.assertEqual(liked_tech[0].link, "https://ex.com/1")

    def test_known_urls_and_deduplication(self):
        self.storage.save_articles([
            Article(title="T", link="https://example.com/known")
        ])
        self.assertTrue(self.storage.is_url_known("https://example.com/known"))
        self.assertFalse(self.storage.is_url_known("https://example.com/unknown"))
        self.assertIn("https://example.com/known", self.storage.get_known_urls())

    def test_briefings(self):
        self.storage.save_briefing(
            briefing_date="2026-09-30",
            content_markdown="## Tagesüberblick",
            model_used="gemini-3.8-flash"
        )
        latest = self.storage.get_latest_briefing()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["briefing_date"], "2026-09-30")
        self.assertEqual(latest["model_used"], "gemini-3.8-flash")
        self.assertEqual(len(self.storage.get_briefings()), 1)


class TestTursoStorage(unittest.TestCase):
    def test_url_normalization(self):
        norm1 = TursoStorage._normalize_pipeline_url("libsql://my-db.turso.io")
        self.assertEqual(norm1, "https://my-db.turso.io/v2/pipeline")

        norm2 = TursoStorage._normalize_pipeline_url("https://my-db.turso.io")
        self.assertEqual(norm2, "https://my-db.turso.io/v2/pipeline")

        norm3 = TursoStorage._normalize_pipeline_url("my-db.turso.io")
        self.assertEqual(norm3, "https://my-db.turso.io/v2/pipeline")

    def test_turso_arg_mapping(self):
        self.assertEqual(TursoStorage._to_turso_arg("hallo"), {"type": "text", "value": "hallo"})
        self.assertEqual(TursoStorage._to_turso_arg(42), {"type": "integer", "value": "42"})
        self.assertEqual(TursoStorage._to_turso_arg(3.14), {"type": "float", "value": 3.14})
        self.assertEqual(TursoStorage._to_turso_arg(True), {"type": "integer", "value": "1"})
        self.assertEqual(TursoStorage._to_turso_arg(False), {"type": "integer", "value": "0"})
        self.assertEqual(TursoStorage._to_turso_arg(None), {"type": "null"})

    def test_turso_cell_mapping(self):
        self.assertEqual(TursoStorage._from_turso_cell({"type": "text", "value": "text"}), "text")
        self.assertEqual(TursoStorage._from_turso_cell({"type": "integer", "value": "123"}), 123)
        self.assertEqual(TursoStorage._from_turso_cell({"type": "float", "value": 1.5}), 1.5)
        self.assertIsNone(TursoStorage._from_turso_cell({"type": "null"}))

    @patch("requests.Session.post")
    def test_turso_pipeline_execution(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "type": "ok",
                    "response": {
                        "type": "execute",
                        "result": {
                            "cols": [{"name": "url"}, {"name": "feedback"}],
                            "rows": [
                                [{"type": "text", "value": "https://ex.com/1"}, {"type": "integer", "value": "1"}]
                            ],
                            "affected_row_count": 0,
                            "last_insert_rowid": None
                        }
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        turso = TursoStorage("libsql://mock.turso.io", "mock-token")
        results = turso._execute_pipeline([("SELECT url, feedback FROM articles", [])])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["rows"][0]["url"], "https://ex.com/1")
        self.assertEqual(results[0]["rows"][0]["feedback"], 1)


class TestStorageFactory(unittest.TestCase):
    @patch("src.storage.get_turso_config")
    def test_fallback_to_sqlite_when_no_credentials(self, mock_cfg):
        mock_cfg.return_value = (None, None)
        storage = get_storage(db_path=":memory:")
        self.assertIsInstance(storage, SqliteStorage)

    @patch("src.storage.TursoStorage.init_db")
    @patch("src.storage.get_turso_config")
    def test_fallback_to_sqlite_when_turso_fails(self, mock_cfg, mock_turso_init):
        mock_cfg.return_value = ("libsql://test.turso.io", "test-token")
        mock_turso_init.side_effect = StorageConnectionError("Network unreachable")

        storage = get_storage(db_path=":memory:")
        self.assertIsInstance(storage, SqliteStorage)


if __name__ == "__main__":
    unittest.main()
