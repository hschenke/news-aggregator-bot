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
        import time
        now_ts = time.time()
        articles = [
            Article(
                title="Artikel 1",
                link="https://example.com/art1",
                summary="Zusammenfassung 1",
                source="Source A",
                category="Tech",
                timestamp=now_ts - 100.0,
                feedback=1,
            ),
            Article(
                title="Artikel 2",
                link="https://example.com/art2",
                summary="Zusammenfassung 2",
                source="Source B",
                category="Wirtschaft",
                timestamp=now_ts,
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

    def test_set_feedback_upsert_and_feedback_map(self):
        # 1. Feedback für bereits existierenden Artikel ändern
        self.storage.save_articles([Article(title="Existing", link="https://ex.com/exist", feedback=0)])
        self.storage.set_feedback("https://ex.com/exist", 1)
        self.assertEqual(self.storage.get_article("https://ex.com/exist").feedback, 1)

        # 2. Feedback für neuen / noch ungespeicherten Artikel (Upsert)
        self.storage.set_feedback("https://ex.com/brand_new", -1, title="Brand New Title")
        brand_new = self.storage.get_article("https://ex.com/brand_new")
        self.assertIsNotNone(brand_new)
        self.assertEqual(brand_new.feedback, -1)
        self.assertEqual(brand_new.title, "Brand New Title")

        # 3. get_feedback_map abfragen
        fb_map = self.storage.get_feedback_map()
        self.assertEqual(fb_map.get("https://ex.com/exist"), 1)
        self.assertEqual(fb_map.get("https://ex.com/brand_new"), -1)
        self.assertNotIn("https://ex.com/unrated", fb_map)

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

    def test_archive_article_moves_from_active_to_archive(self):
        import time
        now_ts = time.time()
        art = Article(
            title="Zu lesender Artikel",
            link="https://example.com/read-me",
            summary="Interessanter Inhalt",
            source="TestQuelle",
            category="Tech",
            timestamp=now_ts,
            feedback=1,
        )
        self.storage.save_articles([art])
        self.assertIsNotNone(self.storage.get_article("https://example.com/read-me"))
        self.assertFalse(self.storage.is_article_archived("https://example.com/read-me"))

        # Als gelesen archivieren
        res = self.storage.archive_article(art)
        self.assertTrue(res)

        # Aus aktiven Artikeln gelöscht
        self.assertIsNone(self.storage.get_article("https://example.com/read-me"))

        # Im Archiv vorhanden
        self.assertTrue(self.storage.is_article_archived("https://example.com/read-me"))
        self.assertIn("https://example.com/read-me", self.storage.get_archived_urls())
        archived_list = self.storage.get_archived_articles()
        self.assertEqual(len(archived_list), 1)
        self.assertEqual(archived_list[0].title, "Zu lesender Artikel")
        self.assertEqual(archived_list[0].feedback, 1)

    def test_save_articles_does_not_resurrect_archived(self):
        art = Article(
            title="Archivierter Artikel",
            link="https://example.com/archived",
            source="Quelle",
            category="News",
        )
        self.storage.archive_article(art)
        self.assertTrue(self.storage.is_article_archived("https://example.com/archived"))

        # Erneuter Feed-Import des Artikels
        saved_count = self.storage.save_articles([art])
        self.assertEqual(saved_count, 0)
        self.assertIsNone(self.storage.get_article("https://example.com/archived"))

    def test_is_url_known_and_get_known_urls_with_archive(self):
        import time
        now_ts = time.time()
        self.storage.save_articles([Article(title="Aktiv", link="https://example.com/active", timestamp=now_ts)])
        self.storage.archive_article(Article(title="Archiviert", link="https://example.com/archived"))

        self.assertTrue(self.storage.is_url_known("https://example.com/active"))
        self.assertTrue(self.storage.is_url_known("https://example.com/archived"))
        self.assertFalse(self.storage.is_url_known("https://example.com/unknown"))

        known = self.storage.get_known_urls()
        self.assertIn("https://example.com/active", known)
        self.assertIn("https://example.com/archived", known)

    def test_cleanup_archive_respects_max_age_days(self):
        import time
        now = time.time()
        SECONDS_PER_DAY = 24 * 3600

        # Älter als 7 Tage (z.B. 10 Tage alt)
        old_art = Article(
            title="Alt",
            link="https://example.com/old",
            timestamp=now - (10 * SECONDS_PER_DAY),
        )
        # Frisch archiviert (z.B. 2 Tage alt)
        recent_art = Article(
            title="Frisch",
            link="https://example.com/recent",
            timestamp=now - (2 * SECONDS_PER_DAY),
        )

        self.storage.archive_article(old_art)
        self.storage.archive_article(recent_art)

        self.assertEqual(len(self.storage.get_archived_articles()), 2)

        # Bereinigung mit max_age_days=7
        cleaned = self.storage.cleanup_archive(max_age_days=7)
        self.assertEqual(cleaned, 1)

        remaining = self.storage.get_archived_articles()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].link, "https://example.com/recent")

    def test_archive_old_articles_and_purge_tables(self):
        import time
        now = time.time()

        # Artikel anlegen: einer frisch (2h alt), einer älter als 24h (26h alt)
        # Da save_articles >24h abweist, fügen wir direkt ein oder nutzen DB-Verbindung
        with self.storage._get_connection() as conn:
            conn.execute(
                "INSERT INTO articles (url, title, summary, source, category, timestamp, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("https://example.com/old-active", "Old Active", "", "S", "Tech", now - (26 * 3600), "2026-10-01", "2026-10-01")
            )
            conn.execute(
                "INSERT INTO articles (url, title, summary, source, category, timestamp, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("https://example.com/fresh-active", "Fresh Active", "", "S", "Tech", now - (2 * 3600), "2026-10-03", "2026-10-03")
            )

        self.assertEqual(len(self.storage.get_articles()), 2)
        # archive_old_articles aufrufen: verschiebt >24h ins Archiv
        archived_count = self.storage.archive_old_articles(max_age_seconds=86400.0)
        self.assertEqual(archived_count, 1)

        remaining_active = self.storage.get_articles()
        self.assertEqual(len(remaining_active), 1)
        self.assertEqual(remaining_active[0].link, "https://example.com/fresh-active")
        self.assertTrue(self.storage.is_article_archived("https://example.com/old-active"))

        # purge_tables testen: leert alle Tabellen
        purged = self.storage.purge_tables()
        self.assertGreaterEqual(purged.get("articles", 0), 1)
        self.assertEqual(len(self.storage.get_articles()), 0)
        self.assertEqual(len(self.storage.get_archived_articles()), 0)



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

    @patch("requests.Session.post")
    def test_turso_get_feedback_map(self, mock_post):
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
                                [{"type": "text", "value": "https://ex.com/like"}, {"type": "integer", "value": "1"}],
                                [{"type": "text", "value": "https://ex.com/dislike"}, {"type": "integer", "value": "-1"}],
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
        fb_map = turso.get_feedback_map()
        self.assertEqual(fb_map, {"https://ex.com/like": 1, "https://ex.com/dislike": -1})

    @patch("requests.Session.post")
    def test_turso_archive_article(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "type": "ok",
                    "response": {
                        "type": "execute",
                        "result": {
                            "cols": [],
                            "rows": [],
                            "affected_row_count": 1,
                            "last_insert_rowid": 1,
                        }
                    }
                },
                {
                    "type": "ok",
                    "response": {
                        "type": "execute",
                        "result": {
                            "cols": [],
                            "rows": [],
                            "affected_row_count": 1,
                            "last_insert_rowid": None,
                        }
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        turso = TursoStorage("libsql://mock.turso.io", "mock-token")
        art = Article(title="Test", link="https://ex.com/archive-turso")
        res = turso.archive_article(art)
        self.assertTrue(res)
        self.assertTrue(mock_post.called)
        payload = mock_post.call_args[1]["json"]
        self.assertIn("archived_articles", payload["requests"][0]["stmt"]["sql"])
        self.assertIn("DELETE FROM articles", payload["requests"][1]["stmt"]["sql"])

    @patch("requests.Session.post")
    def test_turso_cleanup_archive(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "type": "ok",
                    "response": {
                        "type": "execute",
                        "result": {
                            "cols": [],
                            "rows": [],
                            "affected_row_count": 3,
                            "last_insert_rowid": None,
                        }
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        turso = TursoStorage("libsql://mock.turso.io", "mock-token")
        cleaned = turso.cleanup_archive(max_age_weeks=20)
        self.assertEqual(cleaned, 3)
        payload = mock_post.call_args[1]["json"]
        self.assertIn("DELETE FROM archived_articles", payload["requests"][0]["stmt"]["sql"])


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
