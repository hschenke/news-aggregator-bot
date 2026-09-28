"""
Automatisierte Unittests für die Stream-Erkennung, Feed-Verbindungstests und Auto-Discovery.
"""

import unittest
from unittest.mock import patch, MagicMock
from src.aggregator import (
    determine_stream_type,
    autodiscover_rss_feeds,
    test_feed_connection,
    fetch_feed_raw,
    fetch_feed_items,
)


class TestFeedConnection(unittest.TestCase):

    def test_determine_stream_type(self):
        # Erkennung anhand von feedparser version
        self.assertEqual(determine_stream_type("rss20", "", b""), "RSS 2.0")
        self.assertEqual(determine_stream_type("atom10", "", b""), "Atom 1.0")
        self.assertEqual(determine_stream_type("rss10", "", b""), "RSS 1.0 (RDF)")
        self.assertEqual(determine_stream_type("rss091", "", b""), "RSS 0.9x")

        # Erkennung anhand des Inhalts
        self.assertEqual(determine_stream_type("", "text/xml", b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'), "RSS 2.0")
        self.assertEqual(determine_stream_type("", "application/atom+xml", b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'), "Atom 1.0")
        self.assertEqual(determine_stream_type("", "text/html", b'<!DOCTYPE html><html><head><title>Test</title></head><body>Hello</body></html>'), "HTML-Webseite (Kein RSS-Stream)")

    def test_autodiscover_rss_feeds(self):
        html = b"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Test Page</title>
            <link rel="alternate" type="application/rss+xml" title="Haupt-News" href="/rss/news.xml">
            <link rel="alternate" type="application/atom+xml" title="Atom Feed" href="https://example.com/atom.xml">
        </head>
        <body></body>
        </html>
        """
        feeds = autodiscover_rss_feeds(html, "https://example.com/blog/")
        self.assertEqual(len(feeds), 2)
        self.assertEqual(feeds[0]["title"], "Haupt-News")
        self.assertEqual(feeds[0]["url"], "https://example.com/rss/news.xml")
        self.assertEqual(feeds[1]["title"], "Atom Feed")
        self.assertEqual(feeds[1]["url"], "https://example.com/atom.xml")

    def test_test_feed_connection_empty_or_invalid_url(self):
        res_empty = test_feed_connection("")
        self.assertFalse(res_empty["success"])
        self.assertIn("leer", res_empty["error"])

        res_invalid = test_feed_connection("ftp://example.com/feed")
        self.assertFalse(res_invalid["success"])
        self.assertIn("http", res_invalid["error"])

    @patch("src.aggregator.fetch_feed_raw")
    def test_test_feed_connection_html_error(self, mock_raw):
        mock_raw.return_value = {
            "success": True,
            "status_code": 200,
            "content": b"<!DOCTYPE html><html><body><h1>Access Denied / Cloudflare</h1></body></html>",
            "headers": {"content-type": "text/html; charset=utf-8"},
            "final_url": "https://example.com/news",
            "is_redirected": False,
            "content_type": "text/html; charset=utf-8",
            "latency_ms": 50,
            "error": None,
        }
        res = test_feed_connection("https://example.com/news")
        self.assertFalse(res["success"])
        self.assertFalse(res["is_valid_feed"])
        self.assertIn("HTML-Webseite", res["stream_type"])
        self.assertEqual(res["item_count"], 0)
        self.assertIn("HTML-Webseite statt eines RSS-Streams", res["error"])

    @patch("src.aggregator.fetch_feed_raw")
    def test_test_feed_connection_valid_rss(self, mock_raw):
        xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0">
          <channel>
            <title>Test Sport Feed</title>
            <link>https://example.com</link>
            <description>Aktuelle Sportnachrichten</description>
            <item>
              <title>Erster Artikel</title>
              <link>https://example.com/artikel-1</link>
              <pubDate>Mon, 28 Sep 2026 10:00:00 +0200</pubDate>
              <description>Inhalt des Artikels 1</description>
            </item>
          </channel>
        </rss>
        """
        mock_raw.return_value = {
            "success": True,
            "status_code": 200,
            "content": xml_content,
            "headers": {"content-type": "application/rss+xml; charset=utf-8"},
            "final_url": "https://example.com/rss",
            "is_redirected": False,
            "content_type": "application/rss+xml; charset=utf-8",
            "latency_ms": 60,
            "error": None,
        }
        res = test_feed_connection("https://example.com/rss")
        self.assertTrue(res["success"])
        self.assertTrue(res["is_valid_feed"])
        self.assertEqual(res["title"], "Test Sport Feed")
        self.assertEqual(res["stream_type"], "RSS 2.0")
        self.assertEqual(res["item_count"], 1)
        self.assertEqual(len(res["sample_items"]), 1)
        self.assertEqual(res["sample_items"][0]["title"], "Erster Artikel")


if __name__ == "__main__":
    unittest.main()
