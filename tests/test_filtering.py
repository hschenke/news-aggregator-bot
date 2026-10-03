"""
Automatisierte Unittests für Werbefilterung, Keyword-Matching und Berliner Polizei Scraper.
"""

import unittest
import re
from src.aggregator import (
    is_ad_item,
    DEFAULT_AD_PATTERNS,
    clean_html_text,
    format_summary_html,
)


class TestFilteringAndScraping(unittest.TestCase):

    def test_ad_detection_default_patterns(self):
        # Heise Angebot
        self.assertTrue(is_ad_item("heise-Angebot: 20% Rabatt auf Monitore", "Jetzt zugreifen."))
        # Anzeige / Sponsored
        self.assertTrue(is_ad_item("Anzeige: Die besten Versicherungen", "Vergleichsportal."))
        self.assertTrue(is_ad_item("Neues Smartphone im Test", "Sponsored Post: Erfahre mehr."))
        self.assertTrue(is_ad_item("Rabatt-Aktion im Online-Shop", "Spare jetzt viel Geld."))
        # Normaler Artikel darf NICHT als Werbung erkannt werden
        self.assertFalse(is_ad_item("Python 3.14 veröffentlicht", "Neue Features und Performance-Optimierungen."))
        self.assertFalse(is_ad_item("Späti ausgeraubt", "In Wilmersdorf kam es zu einem Überfall."))

    def test_ad_detection_custom_keywords(self):
        custom_kws = ["krypto-scam", "gewinnspiel", "black friday"]
        self.assertTrue(is_ad_item("Großes Gewinnspiel gestartet", "Preise im Wert von...", custom_ad_keywords=custom_kws))
        self.assertTrue(is_ad_item("Black Friday Angebote 2026", "Schnäppchen des Jahres", custom_ad_keywords=custom_kws))
        self.assertFalse(is_ad_item("Wissenschaftliche Studie zu Schlaf", "Schlafforscher stellen Ergebnisse vor.", custom_ad_keywords=custom_kws))

    def test_clean_html_text(self):
        raw = "<p>Hallo &amp; Willkommen bei <b>Berlin.de</b>!&nbsp;&quot;Test&quot;</p>"
        cleaned = clean_html_text(raw)
        self.assertEqual(cleaned, 'Hallo & Willkommen bei Berlin.de! "Test"')

    def test_format_summary_html(self):
        # 1. Police Teaser mit Bezirk in Markdown-Fettdruck
        raw_teaser = "📍 **Steglitz-Zehlendorf** – Einsatzkräfte wurden alarmiert."
        formatted = format_summary_html(raw_teaser)
        self.assertEqual(formatted, "📍 <strong>Steglitz-Zehlendorf</strong> – Einsatzkräfte wurden alarmiert.")
        self.assertNotIn("**", formatted)

        # 2. HTML-Tags werden bereinigt und Fettdruck bleibt intakt
        html_input = "<p>📍 **Tempelhof-Schöneberg** – <i>Gestern Abend</i> &amp; Nacht...</p>"
        formatted_html = format_summary_html(html_input)
        self.assertEqual(formatted_html, "📍 <strong>Tempelhof-Schöneberg</strong> – Gestern Abend & Nacht...")

        # 3. Leerstring / None
        self.assertEqual(format_summary_html(""), "")
        self.assertEqual(format_summary_html(None), "")

        # 4. Normaler Text ohne Markdown bleibt unverändert
        self.assertEqual(format_summary_html("Einfacher Text ohne Formatierung."), "Einfacher Text ohne Formatierung.")

    def test_police_district_and_teaser_extraction(self):
        # Simuliertes HTML von berlin.de/polizei
        sample_html = """
        <!doctype html>
        <html>
        <body>
        <p class="polizeimeldung" title="Ereignisort">Charlottenburg-Wilmersdorf</p>
        <section class="teaser">
            <p><strong>Nr. 1259</strong><br>
            Heute Morgen kam es zu einem schweren Raub auf einen Spätkauf in Wilmersdorf.
            Nach den bisherigen Ermittlungen betrat ein Mann das Geschäft.
            </p>
        </section>
        </body>
        </html>
        """
        # 1. Bezirk extrahieren
        m_dist = re.search(r'title=[\'"]Ereignisort[\'"]>([^<]+)<', sample_html, re.IGNORECASE)
        self.assertIsNotNone(m_dist)
        district = clean_html_text(m_dist.group(1)).strip()
        self.assertEqual(district, "Charlottenburg-Wilmersdorf")

        # 2. Teaser extrahieren
        m_nr = re.search(r'<p[^>]*>\s*<strong>Nr\.\s*\d+</strong><br\s*/?>\s*(.*?)</p>', sample_html, re.DOTALL | re.IGNORECASE)
        self.assertIsNotNone(m_nr)
        teaser = clean_html_text(m_nr.group(1))
        teaser = re.sub(r"^Nr\.\s*\d+\s*", "", teaser).strip()
        self.assertTrue(teaser.startswith("Heute Morgen kam es zu einem schweren Raub"))

        # 3. Formattiertes Gesamtergebnis
        formatted = f"📍 **{district}** – {teaser}"
        self.assertIn("📍 **Charlottenburg-Wilmersdorf**", formatted)
        self.assertIn("Heute Morgen kam es zu einem schweren Raub", formatted)

        # 4. Umwandlung zu HTML für Web-App Container
        html_ready = format_summary_html(formatted)
        self.assertEqual(html_ready, f"📍 <strong>{district}</strong> – {teaser}")
        self.assertNotIn("**", html_ready)

    def test_get_article_timestamp(self):
        from src.aggregator import get_article_timestamp
        from src.models import Article
        import datetime

        # Float / Int
        self.assertEqual(get_article_timestamp({"timestamp": 1700000000.0}), 1700000000.0)
        self.assertEqual(get_article_timestamp(1700000000.0), 1700000000.0)

        # Datetime
        dt = datetime.datetime(2026, 9, 29, 12, 0, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(get_article_timestamp(dt), dt.timestamp())

        # RFC-822 String
        rfc_str = "Mon, 28 Sep 2026 10:00:00 +0000"
        self.assertGreater(get_article_timestamp({"published": rfc_str}), 0.0)

        # ISO String
        iso_str = "2026-09-28T10:00:00Z"
        self.assertGreater(get_article_timestamp({"published": iso_str}), 0.0)

        # Article Instanz
        art = Article(title="Test", link="https://example.com", timestamp=1700000000.0)
        self.assertEqual(get_article_timestamp(art), 1700000000.0)

        # Kein Datum / ungültig
        self.assertEqual(get_article_timestamp({}), 0.0)
        self.assertEqual(get_article_timestamp({"published": "ungueltiges datum"}), 0.0)
        self.assertEqual(get_article_timestamp(None), 0.0)

    def test_is_article_too_old(self):
        from src.aggregator import is_article_too_old, DEFAULT_MAX_ARTICLE_AGE_HOURS

        now_ts = 1790000000.0  # Fester Bezugspunkt
        one_hour_sec = 3600

        # 2 Stunden alt -> nicht zu alt (< 24 Stunden)
        recent_item = {"timestamp": now_ts - (2 * one_hour_sec)}
        self.assertFalse(is_article_too_old(recent_item, max_age_hours=24.0, now_ts=now_ts))

        # 23 Stunden alt -> nicht zu alt
        twenty_three_item = {"timestamp": now_ts - (23 * one_hour_sec)}
        self.assertFalse(is_article_too_old(twenty_three_item, max_age_hours=24.0, now_ts=now_ts))

        # 25 Stunden alt -> zu alt (> 24 Stunden)
        twenty_five_item = {"timestamp": now_ts - (25 * one_hour_sec)}
        self.assertTrue(is_article_too_old(twenty_five_item, max_age_hours=24.0, now_ts=now_ts))

        # 48 Stunden alt -> zu alt
        old_item = {"timestamp": now_ts - (48 * one_hour_sec)}
        self.assertTrue(is_article_too_old(old_item, max_age_hours=24.0, now_ts=now_ts))

        # Artikel ohne Timestamp (0.0) -> wird nicht als zu alt gewertet
        no_ts_item = {"timestamp": 0.0}
        self.assertFalse(is_article_too_old(no_ts_item, max_age_hours=24.0, now_ts=now_ts))

        # Deaktivierte Filterung (max_age_hours = 0 oder None)
        self.assertFalse(is_article_too_old(old_item, max_age_hours=0, now_ts=now_ts))
        self.assertFalse(is_article_too_old(old_item, max_age_hours=None, now_ts=now_ts))

        # Benutzerdefiniertes Alter (z. B. 12 Stunden)
        twelve_hour_limit = 12.0
        item_10_hours = {"timestamp": now_ts - (10 * one_hour_sec)}
        item_14_hours = {"timestamp": now_ts - (14 * one_hour_sec)}
        self.assertFalse(is_article_too_old(item_10_hours, max_age_hours=twelve_hour_limit, now_ts=now_ts))
        self.assertTrue(is_article_too_old(item_14_hours, max_age_hours=twelve_hour_limit, now_ts=now_ts))

    def test_filter_articles_by_age(self):
        from src.aggregator import filter_articles_by_age

        now_ts = 1790000000.0
        one_hour_sec = 3600

        articles = [
            {"title": "Ganz neu (1h)", "timestamp": now_ts - (1 * one_hour_sec)},
            {"title": "15 Stunden alt", "timestamp": now_ts - (15 * one_hour_sec)},
            {"title": "25 Stunden alt", "timestamp": now_ts - (25 * one_hour_sec)},
            {"title": "50 Stunden alt", "timestamp": now_ts - (50 * one_hour_sec)},
            {"title": "Ohne Datum", "timestamp": 0.0},
        ]

        filtered = filter_articles_by_age(articles, max_age_hours=24.0, now_ts=now_ts)
        filtered_titles = [a["title"] for a in filtered]

        self.assertEqual(len(filtered), 3)
        self.assertIn("Ganz neu (1h)", filtered_titles)
        self.assertIn("15 Stunden alt", filtered_titles)
        self.assertIn("Ohne Datum", filtered_titles)
        self.assertNotIn("25 Stunden alt", filtered_titles)
        self.assertNotIn("50 Stunden alt", filtered_titles)

        # Wenn Altersfilterung deaktiviert ist (0 Stunden)
        all_kept = filter_articles_by_age(articles, max_age_hours=0, now_ts=now_ts)
        self.assertEqual(len(all_kept), 5)

    def test_filter_news_data_by_age(self):
        from src.aggregator import filter_news_data_by_age

        now_ts = 1790000000.0
        one_hour_sec = 3600

        news_data = {
            "Tech": [
                {"title": "AI News", "timestamp": now_ts - (2 * one_hour_sec)},
                {"title": "Alter AI Post", "timestamp": now_ts - (25 * one_hour_sec)},
            ],
            "Fun": [
                {"title": "Aktueller Witz", "timestamp": now_ts - (1 * one_hour_sec)},
                {"title": "Uralter Witz", "timestamp": now_ts - (40 * one_hour_sec)},
            ]
        }

        filtered = filter_news_data_by_age(news_data, max_age_hours=24.0, now_ts=now_ts)
        self.assertEqual(len(filtered["Tech"]), 1)
        self.assertEqual(filtered["Tech"][0]["title"], "AI News")
        self.assertEqual(len(filtered["Fun"]), 1)
        self.assertEqual(filtered["Fun"][0]["title"], "Aktueller Witz")

    def test_sources_yaml_settings_contain_archive_retention_days(self):
        from src.aggregator import load_sources
        config = load_sources("config/sources.yaml")
        settings = config.get("settings", {})
        self.assertIn("archive_retention_days", settings)
        self.assertEqual(settings["archive_retention_days"], 7)

    def test_collect_all_news_skips_archived_articles(self):
        from unittest.mock import patch, MagicMock
        from src.aggregator import collect_all_news
        from src.storage import SqliteStorage
        from src.models import Article

        mock_storage = SqliteStorage(":memory:")
        mock_storage.init_db()
        mock_storage.archive_article(Article(title="Schon gelesen", link="https://example.com/archived-item"))

        import time
        now_ts = time.time()
        with patch("src.storage.get_storage", return_value=mock_storage):
            with patch("src.aggregator.load_sources", return_value={
                "categories": [
                    {
                        "name": "TestCat",
                        "feeds": [{"name": "TestFeed", "url": "https://example.com/feed.xml"}]
                    }
                ],
                "settings": {"archive_retention_days": 7}
            }):
                with patch("src.aggregator.fetch_feed_items", return_value=[
                    {"title": "Schon gelesen", "link": "https://example.com/archived-item", "timestamp": now_ts},
                    {"title": "Noch neu", "link": "https://example.com/brand-new", "timestamp": now_ts},
                ]):
                    collected = collect_all_news(export_rss=False)
                    self.assertIn("TestCat", collected)
                    cat_links = [it["link"] for it in collected["TestCat"]]
                    self.assertNotIn("https://example.com/archived-item", cat_links)
                    self.assertIn("https://example.com/brand-new", cat_links)


if __name__ == "__main__":
    unittest.main()
