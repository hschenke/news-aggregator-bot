"""
Unittests für den Aktions-Puffer (ActionBuffer) und Batching-System.
Testet Puffer-Queue, Undo, Flush, Concurrency und Bulk-DB-Aufrufe.
"""

import time
import unittest
from unittest.mock import MagicMock
from src.action_buffer import ActionBuffer
from src.models import Article


class TestActionBuffer(unittest.TestCase):

    def setUp(self):
        self.buffer = ActionBuffer(interval_seconds=60)
        self.mock_storage = MagicMock()
        self.mock_storage.set_feedback_bulk.return_value = 2
        self.mock_storage.archive_articles_bulk.return_value = 2

    def tearDown(self):
        self.buffer.stop_periodic_timer()
        self.buffer.clear()

    def test_queue_read_and_is_read_queued(self):
        art = Article(title="Test 1", link="https://example.com/1")
        self.buffer.queue_read(art)

        self.assertTrue(self.buffer.is_read_queued("https://example.com/1"))
        self.assertFalse(self.buffer.is_read_queued("https://example.com/2"))
        self.assertEqual(self.buffer.get_queued_read_urls(), {"https://example.com/1"})
        r_cnt, fb_cnt = self.buffer.get_pending_counts()
        self.assertEqual(r_cnt, 1)
        self.assertEqual(fb_cnt, 0)

    def test_unqueue_read(self):
        art = Article(title="Test 1", link="https://example.com/1")
        self.buffer.queue_read(art)
        self.assertTrue(self.buffer.is_read_queued("https://example.com/1"))

        # Undo
        removed = self.buffer.unqueue_read("https://example.com/1")
        self.assertTrue(removed)
        self.assertFalse(self.buffer.is_read_queued("https://example.com/1"))
        self.assertEqual(self.buffer.get_pending_counts(), (0, 0))

    def test_queue_feedback(self):
        self.buffer.queue_feedback("https://example.com/art1", 1, "Title 1")
        self.buffer.queue_feedback("https://example.com/art2", -1, "Title 2")

        r_cnt, fb_cnt = self.buffer.get_pending_counts()
        self.assertEqual(r_cnt, 0)
        self.assertEqual(fb_cnt, 2)

    def test_flush_calls_bulk_storage_methods(self):
        art1 = Article(title="Test 1", link="https://example.com/1")
        art2 = Article(title="Test 2", link="https://example.com/2")
        self.buffer.queue_read(art1)
        self.buffer.queue_read(art2)
        self.buffer.queue_feedback("https://example.com/3", 1, "Test 3")

        archived, feedback = self.buffer.flush(self.mock_storage)

        self.mock_storage.archive_articles_bulk.assert_called_once()
        self.mock_storage.set_feedback_bulk.assert_called_once()
        self.assertEqual(self.buffer.get_pending_counts(), (0, 0))

    def test_concurrency_collect_while_flushing(self):
        """
        Prüft, dass während eines laufenden Flushs weitere Aktionen eingereiht werden
        können und diese nach dem Flush im Puffer verbleiben.
        """
        def slow_archive_bulk(articles):
            # Simuliere langsame DB-Operation und füge währenddessen neue Aktionen hinzu
            self.buffer.queue_read(Article(title="New during flush", link="https://example.com/during"))
            time.sleep(0.05)
            return len(articles)

        self.mock_storage.archive_articles_bulk.side_effect = slow_archive_bulk

        art1 = Article(title="Initial", link="https://example.com/initial")
        self.buffer.queue_read(art1)

        self.buffer.flush(self.mock_storage)

        # Der während des Flushs eingetroffene Artikel muss weiterhin im Puffer vorhanden sein
        self.assertTrue(self.buffer.is_read_queued("https://example.com/during"))
        self.assertFalse(self.buffer.is_read_queued("https://example.com/initial"))
        r_cnt, _ = self.buffer.get_pending_counts()
        self.assertEqual(r_cnt, 1)

    def test_flush_remerges_on_error(self):
        self.mock_storage.archive_articles_bulk.side_effect = RuntimeError("DB Network Error")
        art1 = Article(title="Fail Test", link="https://example.com/fail")
        self.buffer.queue_read(art1)

        archived, feedback = self.buffer.flush(self.mock_storage)

        # Bei Fehler sollten die Items für einen späteren Versuch im Puffer bleiben
        self.assertEqual(archived, 0)
        self.assertTrue(self.buffer.is_read_queued("https://example.com/fail"))

    def test_interval_settings(self):
        self.buffer.set_interval_minutes(10)
        self.assertEqual(self.buffer.get_interval_minutes(), 10)
        self.assertGreaterEqual(self.buffer.get_seconds_until_next_flush(), 0)


if __name__ == "__main__":
    unittest.main()
