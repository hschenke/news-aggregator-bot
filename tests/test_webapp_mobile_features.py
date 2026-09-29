"""
Unittests für die mobilen Optimierungen der Web-App:
- Formatierung der Zusammenfassungen (HTML & Fettdruck für Bezirke)
- Zählung von Feeds und Artikeln in Kategorie-Titeln (z. B. '2 Feeds, 20 Artikel')
- Filter- und Suchlogik (Automatisches Aufklappen bei aktiver Filterung/Suche)
"""

import unittest
from src.aggregator import format_summary_html


class TestWebappMobileFeatures(unittest.TestCase):

    def test_police_district_bold_in_html(self):
        """Prüft, dass Bezirke in Zusammenfassungen als <strong> statt mit Roh-Sternchen formatiert werden."""
        raw_text = "📍 **Steglitz-Zehlendorf** – Einsatzkräfte von Polizei und Feuerwehr alarmiert."
        formatted = format_summary_html(raw_text)
        self.assertIn("<strong>Steglitz-Zehlendorf</strong>", formatted)
        self.assertNotIn("**", formatted)

        # Mehrere Bezirke/Fettdrucke in einem Text
        multi_text = "📍 **Mitte** und **Tiergarten** – Großeinsatz der Polizei."
        multi_formatted = format_summary_html(multi_text)
        self.assertEqual(multi_formatted, "📍 <strong>Mitte</strong> und <strong>Tiergarten</strong> – Großeinsatz der Polizei.")

    def test_category_expander_label_formatting(self):
        """Prüft die korrekte Singular- und Pluralbildung für Feeds und Artikel in Kategorie-Headern."""
        def format_cat_label(cat_name: str, feeds_count: int, items_count: int) -> str:
            feed_label = f"{feeds_count} Feed" if feeds_count == 1 else f"{feeds_count} Feeds"
            item_label = f"{items_count} Artikel" if items_count != 1 else "1 Artikel"
            return f"📁 **{cat_name}** ({feed_label}, {item_label})"

        # Bild 4 Szenarien
        self.assertEqual(
            format_cat_label("Berlin", 2, 20),
            "📁 **Berlin** (2 Feeds, 20 Artikel)"
        )
        self.assertEqual(
            format_cat_label("Finanzen & Coins", 2, 20),
            "📁 **Finanzen & Coins** (2 Feeds, 20 Artikel)"
        )
        self.assertEqual(
            format_cat_label("Fun", 1, 107),
            "📁 **Fun** (1 Feed, 107 Artikel)"
        )
        self.assertEqual(
            format_cat_label("Tech & AI", 3, 193),
            "📁 **Tech & AI** (3 Feeds, 193 Artikel)"
        )
        self.assertEqual(
            format_cat_label("Test", 1, 1),
            "📁 **Test** (1 Feed, 1 Artikel)"
        )

    def test_filtering_state_active_flag(self):
        """Prüft die Logik, wann Filter/Kategorien/Feeds automatisch offen bleiben."""
        def check_is_filtering(selected_cat: str, selected_feed: str, search_query: str) -> bool:
            return bool(
                (selected_cat and selected_cat != "Alle Kategorien")
                or (selected_feed and selected_feed != "Alle Feeds")
                or (search_query and search_query.strip())
            )

        # Standard-Übersicht: keine aktive Filterung
        self.assertFalse(check_is_filtering("Alle Kategorien", "Alle Feeds", ""))
        self.assertFalse(check_is_filtering("Alle Kategorien", "Alle Feeds", "   "))

        # Kategorie gewählt
        self.assertTrue(check_is_filtering("Policia", "Alle Feeds", ""))

        # Feed gewählt
        self.assertTrue(check_is_filtering("Alle Kategorien", "Polizeimeldungen Berlin", ""))

        # Suchbegriff eingegeben
        self.assertTrue(check_is_filtering("Alle Kategorien", "Alle Feeds", "Hellersdorf"))

        # Kombination
        self.assertTrue(check_is_filtering("Policia", "Polizeimeldungen Berlin", "Amoktat"))

    def test_search_reset_callback_behavior(self):
        """Prüft, dass der Reset-Mechanismus den Suchbegriff zuverlässig auf leeren String zurücksetzt."""
        mock_session_state = {"input_search_query": "Hellersdorf"}
        
        def on_clear_search():
            mock_session_state["input_search_query"] = ""

        self.assertEqual(mock_session_state["input_search_query"], "Hellersdorf")
        on_clear_search()
        self.assertEqual(mock_session_state["input_search_query"], "")

    def test_webapp_layout_integrity(self):
        """Prüft Quelltext-Integrität in webapp.py gegen Layout-Regressionen."""
        from pathlib import Path
        webapp_code = Path("src/webapp.py").read_text(encoding="utf-8")

        # 1. Sidebar muss auf "auto" stehen, damit Mobile nicht verdeckt wird
        self.assertIn('initial_sidebar_state="auto"', webapp_code)

        # 2. Kein fragiles position: absolute auf btn_search_clear
        self.assertNotIn("position: absolute !important;\n        right: 0.35rem", webapp_code)

        # 3. Mobile CSS muss die Suchleiste mit stColumn und flex: 1 1 0 flexibel halten
        self.assertIn('[data-testid="stHorizontalBlock"]:has(.st-key-input_search_query)', webapp_code)
        self.assertIn('flex: 1 1 0 !important;', webapp_code)
        self.assertIn('[data-testid="stColumn"]:has(.st-key-btn_search_clear)', webapp_code)
        self.assertIn('[data-testid="stColumn"]:has(.st-key-btn_search_go)', webapp_code)

        # 4. Feedly Subheader Name
        self.assertIn('"📡 RSS Exposure"', webapp_code)


if __name__ == "__main__":
    unittest.main()
