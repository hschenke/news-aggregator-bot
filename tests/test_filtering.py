"""
Automatisierte Unittests für Werbefilterung, Keyword-Matching und Berliner Polizei Scraper.
"""

import unittest
import re
from src.aggregator import (
    is_ad_item,
    DEFAULT_AD_PATTERNS,
    clean_html_text,
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


if __name__ == "__main__":
    unittest.main()
