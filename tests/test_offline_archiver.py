"""
Unit tests for the Offline Download & Archiving feature:
- OfflineArticle model serialization
- Feed configuration (offline_download flag in add_feed, update_feed, get_offline_enabled_feeds)
- SqliteStorage offline_articles table, CRUD, and automatic 3-month (90 days) retention cleanup
- SSRF validation (is_safe_external_url)
- Webpage snapshot extraction (text + compressed Base64 images)
- Berlin Police report extraction & repair (preserving district line like 'Marzahn-Hellersdorf' and '**Nr. 1396**')
- Pure HTML generation for single articles and entire feeds (no PDF overhead)
- Client-side Blob HTML download & new-tab browser preview in archive_tab.py
- Navigation tab '📦 Archiv' positioned before '📡 Feedly' in webapp.py and state.py
"""

from __future__ import annotations

import base64
import io
import json
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from src.models import OfflineArticle
from src.offline_archiver import (
    _extract_article_paragraphs_from_html,
    fetch_article_snapshot,
    generate_offline_article_html,
    generate_offline_feed_html,
    get_offline_task_status,
    is_safe_external_url,
    repair_police_offline_article,
    run_offline_archive_for_feeds,
)
from src.sources_manager import add_feed, get_offline_enabled_feeds, update_feed
from src.storage.base import OFFLINE_RETENTION_DAYS
from src.storage.sqlite import SqliteStorage


def _create_sample_image_bytes() -> bytes:
    """Creates a valid PNG image (>= 100x100 px and > 800 bytes) in memory for testing."""
    img = Image.new("RGB", (240, 180), color=(30, 120, 200))
    pixels = img.load()
    for x in range(240):
        for y in range(180):
            pixels[x, y] = ((x * 7) % 255, (y * 11) % 255, ((x + y) * 5) % 255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_sample_image_dict() -> dict:
    """Creates a valid image dict with data_b64 for OfflineArticle testing."""
    img = Image.new("RGB", (120, 90), color=(200, 80, 40))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "url": "https://example.com/img.jpg",
        "alt": "Testbild",
        "mime_type": "image/jpeg",
        "width": 120,
        "height": 90,
        "data_b64": b64,
    }


class TestOfflineArchiverFeature(unittest.TestCase):
    def test_retention_constant_is_90_days(self) -> None:
        """Offline retention must be configured to 90 days (3 months)."""
        self.assertEqual(OFFLINE_RETENTION_DAYS, 90)

    def test_offline_article_model_roundtrip(self) -> None:
        """OfflineArticle must serialize and deserialize cleanly with embedded images."""
        img_dict = _create_sample_image_dict()
        art = OfflineArticle(
            url="https://example.com/news/1",
            title="Test Offline Artikel",
            feed_name="Example Tech",
            feed_url="https://example.com/rss.xml",
            category="Tech & AI",
            published="Mon, 27 Oct 2026 10:00:00 GMT",
            timestamp=time.time(),
            content_text="Erster Absatz mit spannenden Details.\n\nZweiter Absatz mit Fazit.",
            content_html="<article><p>Erster Absatz</p></article>",
            images_json=json.dumps([img_dict]),
            created_at="2026-10-27T10:00:00+00:00",
        )
        self.assertEqual(len(art.images), 1)
        self.assertEqual(art.images[0]["data_b64"], img_dict["data_b64"])

        as_dict = art.to_dict()
        restored = OfflineArticle.from_dict(as_dict)
        self.assertEqual(restored.url, art.url)
        self.assertEqual(restored.title, art.title)
        self.assertEqual(restored.feed_name, art.feed_name)
        self.assertEqual(len(restored.images), 1)

    def test_sources_manager_offline_download_flag(self) -> None:
        """add_feed and update_feed must persist offline_download and get_offline_enabled_feeds must return them."""
        config: dict = {"categories": [{"name": "Tech", "feeds": []}], "settings": {}}

        add_feed(
            category_name="Tech",
            feed_name="Heise",
            feed_url="https://www.heise.de/rss/heise.rdf",
            offline_download=True,
            config=config,
            save_to_disk=False,
        )
        add_feed(
            category_name="Tech",
            feed_name="Golem",
            feed_url="https://rss.golem.de/rss.php",
            offline_download=False,
            config=config,
            save_to_disk=False,
        )

        enabled = get_offline_enabled_feeds(config=config)
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0]["name"], "Heise")
        self.assertTrue(enabled[0]["offline_download"])

        update_feed(
            category_name="Tech",
            old_url="https://www.heise.de/rss/heise.rdf",
            offline_download=False,
            config=config,
            save_to_disk=False,
        )
        update_feed(
            category_name="Tech",
            old_url="https://rss.golem.de/rss.php",
            offline_download=True,
            config=config,
            save_to_disk=False,
        )

        enabled_after = get_offline_enabled_feeds(config=config)
        self.assertEqual(len(enabled_after), 1)
        self.assertEqual(enabled_after[0]["name"], "Golem")

    def test_sqlite_storage_offline_crud_and_3_month_cleanup(self) -> None:
        """SqliteStorage must store offline articles and automatically purge entries older than 3 months (90 days) on save."""
        storage = SqliteStorage(db_path=":memory:")
        storage.init_db()

        now_ts = time.time()
        expired_ts = now_ts - (95 * 86400.0)
        with storage._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO offline_articles
                (url, title, feed_name, feed_url, category, published, timestamp, content_text, content_html, images_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "https://example.com/old-article",
                    "Alter Artikel (> 3 Monate)",
                    "Feed A",
                    "https://example.com/rss",
                    "Tech",
                    "Old Date",
                    expired_ts,
                    "Alter Text",
                    "<p>Alter Text</p>",
                    "[]",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            conn.commit()

        self.assertEqual(len(storage.get_offline_articles()), 1)

        fresh_art = OfflineArticle(
            url="https://example.com/fresh-article",
            title="Frischer Artikel",
            feed_name="Feed A",
            feed_url="https://example.com/rss",
            category="Tech",
            published="Today",
            timestamp=now_ts,
            content_text="Frischer Volltext des Artikels.",
            content_html="<p>Frischer Volltext des Artikels.</p>",
            images_json=json.dumps([_create_sample_image_dict()]),
        )
        saved_ok = storage.save_offline_article(fresh_art)
        self.assertTrue(saved_ok)

        remaining = storage.get_offline_articles()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].url, "https://example.com/fresh-article")

        single = storage.get_offline_article("https://example.com/fresh-article")
        self.assertIsNotNone(single)
        self.assertEqual(single.title, "Frischer Artikel")
        self.assertIn("https://example.com/fresh-article", storage.get_offline_urls())

        self.assertTrue(storage.delete_offline_article("https://example.com/fresh-article"))
        self.assertEqual(len(storage.get_offline_articles()), 0)

    def test_ssrf_url_validation(self) -> None:
        """is_safe_external_url must reject private/loopback IPs and non-HTTP schemes."""
        self.assertFalse(is_safe_external_url(""))
        self.assertFalse(is_safe_external_url("file:///etc/passwd"))
        self.assertFalse(is_safe_external_url("javascript:alert(1)"))
        self.assertFalse(is_safe_external_url("http://localhost:8080/test"))
        self.assertFalse(is_safe_external_url("http://127.0.0.1/admin"))
        self.assertFalse(is_safe_external_url("http://169.254.169.254/latest/meta-data/"))
        self.assertFalse(is_safe_external_url("http://192.168.1.100/feed.xml"))
        self.assertFalse(is_safe_external_url("http://10.0.0.5/internal"))

    def test_berlin_police_report_extraction_and_repair(self) -> None:
        """
        Berlin police reports must preserve the district line (e.g. 'Marzahn-Hellersdorf')
        between 'Polizeimeldung vom ...' and '**Nr. 1396**', and repair existing entries.
        """
        police_html = """
        <html>
          <body>
            <article>
              <h1>Flucht mit E-Scootern endet mit Festnahmen</h1>
              <p class="polizeimeldung">Polizeimeldung vom 20.10.2026</p>
              <p class="polizeimeldung" title="Ereignisort">Marzahn-Hellersdorf</p>
              <div class="textile">
                <p><strong>Nr. 1396</strong><br />
                In der vergangenen Nacht nahmen Einsatzkräfte in Biesdorf zwei Jugendliche nach einer Flucht fest.</p>
              </div>
            </article>
          </body>
        </html>
        """
        paragraphs = _extract_article_paragraphs_from_html(police_html)
        self.assertEqual(paragraphs[0], "Polizeimeldung vom 20.10.2026")
        self.assertEqual(paragraphs[1], "Marzahn-Hellersdorf")
        self.assertEqual(paragraphs[2], "**Nr. 1396**")
        self.assertTrue(paragraphs[3].startswith("In der vergangenen Nacht nahmen Einsatzkräfte"))

        # Test repairing an already-archived police article that missed 'Marzahn-Hellersdorf' and merged 'Nr. 1396'
        legacy_art = OfflineArticle(
            url="https://www.berlin.de/polizei/polizeimeldungen/2026/pressemitteilung.1396.php",
            title="Flucht mit E-Scootern endet mit Festnahmen",
            feed_name="Polizeimeldungen Berlin",
            category="Berlin",
            content_text=(
                "Polizeimeldung vom 20.10.2026\n\n"
                "Nr. 1396 In der vergangenen Nacht nahmen Einsatzkräfte in Biesdorf zwei Jugendliche fest."
            ),
        )
        with patch.dict(
            "src.offline_archiver._POLICE_TEASER_CACHE",
            {legacy_art.url: "📍 **Marzahn-Hellersdorf** – In der vergangenen Nacht..."},
            clear=False,
        ):
            repaired_art, changed = repair_police_offline_article(legacy_art, allow_network_lookup=False)
            self.assertTrue(changed)
            repaired_blocks = repaired_art.content_text.split("\n\n")
            self.assertEqual(repaired_blocks[0], "Polizeimeldung vom 20.10.2026")
            self.assertEqual(repaired_blocks[1], "Marzahn-Hellersdorf")
            self.assertEqual(repaired_blocks[2], "**Nr. 1396**")
            self.assertTrue(repaired_blocks[3].startswith("In der vergangenen Nacht"))

    @patch("src.offline_archiver.is_safe_external_url", return_value=True)
    @patch("src.offline_archiver.requests.Session.get")
    def test_fetch_article_snapshot_extracts_text_and_images(
        self,
        mock_get: MagicMock,
        _mock_safe: MagicMock,
    ) -> None:
        """fetch_article_snapshot must extract main article paragraphs and convert images to Base64 JPEG."""
        sample_html = """
        <html>
          <head>
            <meta property="og:image" content="https://example.com/hero.png" />
          </head>
          <body>
            <nav>Navigation Menu</nav>
            <article>
              <h1>Wichtige Schlagzeile zur KI-Entwicklung</h1>
              <p>Dies ist der erste ausführliche Absatz des Artikels mit mehr als vierzig Zeichen Länge.</p>
              <p>Dies ist der zweite ausführliche Absatz, der weitere technische Hintergründe beleuchtet.</p>
            </article>
            <footer>Footer Copyright</footer>
          </body>
        </html>
        """
        img_bytes = _create_sample_image_bytes()

        def side_effect(url: str, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.url = url
            if url.endswith(".png"):
                resp.headers = {"Content-Type": "image/png"}
                resp.iter_content = lambda chunk_size=16384: [img_bytes]
            else:
                resp.headers = {"Content-Type": "text/html; charset=utf-8"}
                resp.encoding = "utf-8"
                resp.iter_content = lambda chunk_size=16384: [sample_html.encode("utf-8")]
            return resp

        mock_get.side_effect = side_effect

        snapshot = fetch_article_snapshot(
            url="https://example.com/article-1",
            title="Wichtige Schlagzeile zur KI-Entwicklung",
            fallback_summary="Fallback Teaser",
        )
        self.assertIn("Dies ist der erste ausführliche Absatz", snapshot["content_text"])
        self.assertIn("Dies ist der zweite ausführliche Absatz", snapshot["content_text"])
        self.assertEqual(len(snapshot["images"]), 1)
        self.assertIn("data_b64", snapshot["images"][0])
        self.assertIn("<img src=\"data:image/jpeg;base64,", snapshot["content_html"])

    def test_generate_html_for_single_article_and_feed_without_pdf(self) -> None:
        """HTML generators must produce valid self-contained HTML for single articles and feeds."""
        img_dict = _create_sample_image_dict()
        art1 = OfflineArticle(
            url="https://example.com/a1",
            title="Erster Offline-Artikel mit Umlauten äöü ÄÖÜ ß €",
            feed_name="Test Feed",
            feed_url="https://example.com/rss",
            category="Wirtschaft",
            published="27.10.2026",
            timestamp=time.time(),
            content_text="Polizeimeldung vom 20.10.2026\n\nMarzahn-Hellersdorf\n\n**Nr. 1396**\n\nInhalt des ersten Artikels.",
            content_html="<p>Absatz eins</p>",
            images_json=json.dumps([img_dict]),
        )
        art2 = OfflineArticle(
            url="https://example.com/a2",
            title="Zweiter Offline-Artikel im selben Feed",
            feed_name="Test Feed",
            feed_url="https://example.com/rss",
            category="Wirtschaft",
            published="27.10.2026",
            timestamp=time.time() - 60,
            content_text="Inhalt des zweiten Artikels.",
            content_html="<p>Inhalt des zweiten Artikels.</p>",
            images_json="[]",
        )

        # Single article HTML
        html_single_str = generate_offline_article_html(art1)
        self.assertIn("<!DOCTYPE html>", html_single_str)
        self.assertIn("Erster Offline-Artikel", html_single_str)
        self.assertIn("Marzahn-Hellersdorf", html_single_str)
        self.assertIn("<strong>Nr. 1396</strong>", html_single_str)
        self.assertIn(img_dict["data_b64"], html_single_str)

        # Feed HTML
        html_feed_str = generate_offline_feed_html("Test Feed", [art1, art2])
        self.assertIn("Erster Offline-Artikel", html_feed_str)
        self.assertIn("Zweiter Offline-Artikel", html_feed_str)
        self.assertIn("Inhaltsverzeichnis (2 Artikel)", html_feed_str)
        self.assertIn('id="toc-top"', html_feed_str)
        self.assertIn('class="floating-toc-btn"', html_feed_str)
        self.assertIn("⬆️ Zum Inhaltsverzeichnis", html_feed_str)

    @patch("src.offline_archiver.fetch_article_snapshot")
    @patch("src.aggregator.fetch_feed_items")
    def test_background_worker_archives_feed_articles(
        self,
        mock_fetch_feed_items: MagicMock,
        mock_snapshot: MagicMock,
    ) -> None:
        """run_offline_archive_for_feeds must iterate feed articles, snapshot them, and store in offline_articles."""
        storage = SqliteStorage(db_path=":memory:")
        storage.init_db()

        mock_fetch_feed_items.return_value = [
            {
                "title": "Background Artikel 1",
                "link": "https://example.com/bg-1",
                "published": "Today",
                "timestamp": time.time(),
                "summary": "Kurzinfo",
            }
        ]
        img_dict = _create_sample_image_dict()
        mock_snapshot.return_value = {
            "content_text": "Vollständiger Artikeltext aus dem Hintergrundtask.",
            "content_html": "<p>Vollständiger Artikeltext aus dem Hintergrundtask.</p>",
            "images": [img_dict],
            "images_json": json.dumps([img_dict]),
        }

        config = {
            "categories": [
                {
                    "name": "Tech",
                    "feeds": [
                        {
                            "name": "BG Feed",
                            "url": "https://example.com/rss",
                            "offline_download": True,
                        }
                    ],
                }
            ],
            "settings": {"filter_ads": False},
        }

        result = run_offline_archive_for_feeds(config=config, storage=storage)
        self.assertEqual(result["saved"], 1)
        self.assertEqual(result["feeds_processed"], 1)

        saved_items = storage.get_offline_articles(feed_name="BG Feed")
        self.assertEqual(len(saved_items), 1)
        self.assertEqual(saved_items[0].title, "Background Artikel 1")
        self.assertEqual(len(saved_items[0].images), 1)

        status = get_offline_task_status()
        self.assertFalse(status["is_running"])

    def test_ui_navigation_order_and_html_only_archive_tab(self) -> None:
        """Verifies that TAB_ARCHIVE ('📦 Archiv') is before '📡 Feedly' and only HTML open/download exists."""
        root = Path(__file__).resolve().parent.parent
        state_py = (root / "src" / "ui" / "state.py").read_text(encoding="utf-8")
        webapp_py = (root / "src" / "webapp.py").read_text(encoding="utf-8")
        manage_py = (root / "src" / "ui" / "tabs" / "manage_tab.py").read_text(encoding="utf-8")
        archive_py = (root / "src" / "ui" / "tabs" / "archive_tab.py").read_text(encoding="utf-8")
        req_txt = (root / "requirements.txt").read_text(encoding="utf-8")

        # No PDF in requirements or archive_tab
        self.assertNotIn("fpdf2", req_txt)
        self.assertNotIn("generate_offline_article_pdf", archive_py)
        self.assertNotIn("generate_offline_feed_pdf", archive_py)
        self.assertNotIn("application/pdf", archive_py)

        # HTML download present via native lazy st.download_button
        self.assertIn("generate_offline_article_html", archive_py)
        self.assertIn("generate_offline_feed_html", archive_py)
        self.assertIn("st.download_button", archive_py)

        # Combined Sync & Refresh button + bottom collapsible management block
        self.assertIn("btn_archive_sync_refresh", archive_py)
        self.assertIn("_render_archive_management_block", archive_py)
        self.assertNotIn("btn_archive_start_bg", archive_py)
        self.assertNotIn("btn_archive_refresh_ui", archive_py)

        # Tab order: Archiv (index 3) before Feedly (index 4)
        self.assertIn('TAB_ARCHIVE = "archive"', state_py)
        self.assertIn('"archive": 3, "feedly": 4', webapp_py)
        self.assertNotIn("news_data = {}", webapp_py)
        pos_arch = webapp_py.find('data-tab-id="{TAB_ID_ARCHIVE}"')
        pos_fdl = webapp_py.find('data-tab-id="{TAB_ID_FEEDLY}"')
        self.assertGreater(pos_arch, 0)
        self.assertLess(pos_arch, pos_fdl, "Archiv tab button must appear before Feedly in sidebar")

        # Manage tab offline checkboxes
        self.assertIn("inp_new_feed_offline", manage_py)
        self.assertIn("ed_offline_", manage_py)


if __name__ == "__main__":
    unittest.main()
