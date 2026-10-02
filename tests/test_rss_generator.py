"""
Unittests für rss_generator.py, insbesondere den 24h-Filter für das RSS Exposure (Feedly).
"""

import time
import unittest
from src.rss_generator import (
    filter_articles_last_24h,
    EXPOSURE_MAX_AGE_SECONDS,
    generate_rss_xml,
)


class TestRssGenerator(unittest.TestCase):

    def test_filter_articles_last_24h(self):
        now = time.time()
        art_recent_1 = {
            "title": "Artikel vor 2 Stunden",
            "link": "https://example.com/2h",
            "timestamp": now - 2 * 3600,
        }
        art_recent_2 = {
            "title": "Artikel vor 23 Stunden",
            "link": "https://example.com/23h",
            "timestamp": now - 23 * 3600,
        }
        art_old = {
            "title": "Artikel vor 2 Tagen",
            "link": "https://example.com/48h",
            "timestamp": now - 48 * 3600,
        }
        art_very_old = {
            "title": "Artikel vor 1 Woche",
            "link": "https://example.com/1w",
            "timestamp": now - 7 * 24 * 3600,
        }

        news_data = {
            "Tech": [art_recent_1, art_old],
            "News": [art_recent_2, art_very_old],
            "EmptyCat": [art_old],
        }

        filtered = filter_articles_last_24h(news_data, reference_time=now)

        self.assertEqual(len(filtered["Tech"]), 1)
        self.assertEqual(filtered["Tech"][0]["link"], "https://example.com/2h")

        self.assertEqual(len(filtered["News"]), 1)
        self.assertEqual(filtered["News"][0]["link"], "https://example.com/23h")

        self.assertEqual(len(filtered["EmptyCat"]), 0)

    def test_generate_rss_xml_structure(self):
        items = [
            {
                "title": "Test Title",
                "link": "https://example.com/test",
                "summary": "Short summary",
                "published_parsed": time.gmtime(),
            }
        ]
        xml = generate_rss_xml(
            title="Feed Title",
            link="https://example.com",
            description="Feed Desc",
            items=items,
        )
        self.assertIn("<title>Test Title</title>", xml)
        self.assertIn("<link>https://example.com/test</link>", xml)
        self.assertIn("version=\"2.0\"", xml)


if __name__ == "__main__":
    unittest.main()
