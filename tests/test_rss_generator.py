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

    def test_extract_briefing_articles_from_markdown(self):
        from src.rss_generator import extract_briefing_articles

        md = """## 🤖 Tech & AI
> 💡 **Kompakt:** Wichtige Neuerungen im Bereich Künstliche Intelligenz.
> 🔗 [Streamlit App](https://app/?category=Tech) · Feeds: [Heise](https://app/?feed=Heise)

- **[Gemini 4 Argon vorgestellt](https://techcrunch.com/2026/09/30/gemini-4/)**: Google bringt neues Modell heraus.
- **[OpenAI startet Dots](https://heise.de/news/dots.html)**: Dauerhaft aktive KI-Agenten für komplexe Workflows.

## ⚽ Fußball
> 💡 **Kompakt:** Aktuelles aus der Bundesliga.

- **[Musiala Marktwerte Update](https://transfermarkt.de/musiala/123)**: Anpassung nach den letzten Spielen.
"""
        articles = extract_briefing_articles(md, known_categories=["Tech & AI", "Fußball"])
        self.assertEqual(len(articles), 3)

        self.assertEqual(articles[0]["category"], "Tech & AI")
        self.assertEqual(articles[0]["title"], "Gemini 4 Argon vorgestellt")
        self.assertEqual(articles[0]["link"], "https://techcrunch.com/2026/09/30/gemini-4/")
        self.assertEqual(articles[0]["summary"], "Google bringt neues Modell heraus.")

        self.assertEqual(articles[1]["title"], "OpenAI startet Dots")
        self.assertEqual(articles[2]["category"], "Fußball")
        self.assertEqual(articles[2]["title"], "Musiala Marktwerte Update")

    def test_extract_briefing_articles_from_html(self):
        from src.rss_generator import extract_briefing_articles

        html = """
        <h2>Berlin</h2>
        <blockquote><p>💡 <strong>Kompakt:</strong> Zusammenfassung.</p></blockquote>
        <ul>
            <li><strong><a href="https://berlin.de/presse1">Meldung 1</a></strong>: Unfall im Zentrum.</li>
            <li><strong><a href="https://berlin.de/presse2">Meldung 2</a></strong>: Festnahme gelungen.</li>
        </ul>
        """
        articles = extract_briefing_articles(html, known_categories=["Berlin"])
        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0]["category"], "Berlin")
        self.assertEqual(articles[0]["title"], "Meldung 1")
        self.assertEqual(articles[0]["link"], "https://berlin.de/presse1")
        self.assertEqual(articles[0]["summary"], "Unfall im Zentrum.")

    def test_export_briefing_rss_multi_item_and_metadata_enrichment(self):
        import tempfile
        from pathlib import Path
        from src.rss_generator import export_briefing_rss
        import xml.etree.ElementTree as ET

        md = """## Tech & AI
- **[Neues KI-Modell](https://example.com/ai)**: Revolutionäre Architektur veröffentlicht.
- **[Hardware Innovation](https://example.com/hardware)**: Neue Chipgeneration für Datencenter.
"""
        news_data = {
            "Tech & AI": [
                {
                    "title": "Neues KI-Modell",
                    "link": "https://example.com/ai",
                    "source": "Tech News Daily",
                    "source_url": "https://example.com/rss",
                    "published": "Fri, 02 Oct 2026 12:00:00 +0000",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_target = Path(tmp_dir) / "briefing.xml"
            res = export_briefing_rss(
                md,
                base_url="https://test-app.com",
                news_data=news_data,
                target_file=test_target,
            )
            self.assertEqual(res["item_count"], 2)
            self.assertTrue(test_target.exists())

            root = ET.fromstring(res["xml_preview"])
            channel = root.find("channel")
            self.assertIsNotNone(channel)
            items = channel.findall("item")
            self.assertEqual(len(items), 2)

            item1 = items[0]
            self.assertEqual(item1.find("title").text, "[Tech & AI] Neues KI-Modell")
            self.assertEqual(item1.find("link").text, "https://example.com/ai")
            self.assertEqual(item1.find("category").text, "Tech & AI")
            self.assertEqual(item1.find("source").text, "Tech News Daily")
            self.assertEqual(item1.find("source").get("url"), "https://example.com/rss")
            self.assertIn("Revolutionäre Architektur veröffentlicht.", item1.find("description").text)

            item2 = items[1]
            self.assertEqual(item2.find("title").text, "[Tech & AI] Hardware Innovation")
            self.assertEqual(item2.find("link").text, "https://example.com/hardware")
            self.assertEqual(item2.find("source").text, "KI-Briefing")

    def test_export_briefing_rss_fallback_when_no_links(self):
        import tempfile
        from pathlib import Path
        from src.rss_generator import export_briefing_rss
        import xml.etree.ElementTree as ET

        empty_md = "Aktuell liegen keine Meldungen vor."
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_target = Path(tmp_dir) / "briefing.xml"
            res = export_briefing_rss(
                empty_md,
                base_url="https://test-app.com",
                target_file=test_target,
            )
            self.assertEqual(res["item_count"], 1)
            self.assertTrue(test_target.exists())

            root = ET.fromstring(res["xml_preview"])
            items = root.find("channel").findall("item")
            self.assertEqual(len(items), 1)
            self.assertIn("KI-Briefing", items[0].find("title").text)

    def test_purge_jsdelivr_cache_success(self):
        from unittest.mock import patch, MagicMock
        from src.aggregator import purge_jsdelivr_cache

        with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(status_code=202, text='{"status":"pending"}')
            mock_get.return_value = MagicMock(status_code=200, text='{"status":"finished"}')

            res = purge_jsdelivr_cache(
                paths=["static/rss/briefing.xml", "static/rss/all.xml"],
                repo="test/repo",
                branch="main",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["purged_count"], 2)
            mock_post.assert_called_once()
            call_json = mock_post.call_args[1]["json"]
            self.assertIn("/gh/test/repo@main/static/rss/briefing.xml", call_json["path"])
            self.assertIn("/gh/test/repo@main/static/rss/all.xml", call_json["path"])
            self.assertEqual(mock_get.call_count, 2)

    def test_purge_jsdelivr_cache_handles_failure(self):
        from unittest.mock import patch
        import requests
        from src.aggregator import purge_jsdelivr_cache

        with patch("requests.post", side_effect=requests.RequestException("Network error")), \
             patch("requests.get", side_effect=requests.RequestException("Timeout")):

            res = purge_jsdelivr_cache(
                paths=["static/rss/briefing.xml"],
                repo="test/repo",
                branch="main",
            )
            self.assertFalse(res["success"])
            self.assertTrue(len(res["errors"]) > 0)


if __name__ == "__main__":
    unittest.main()
