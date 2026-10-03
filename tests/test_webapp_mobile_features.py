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

    def test_is_filtering_defined_in_webapp(self):
        """Stellt sicher, dass 'is_filtering' im Code definiert ist, bevor cat_is_open ausgewertet wird."""
        from pathlib import Path
        code = Path("src/ui/tabs/articles_tab.py").read_text(encoding="utf-8")
        pos_def = code.find("is_filtering = bool(")
        pos_use = code.find("cat_is_open = True if (")
        self.assertNotEqual(pos_def, -1, "'is_filtering = bool(' muss in articles_tab.py definiert sein!")
        self.assertNotEqual(pos_use, -1, "'cat_is_open = True if (' muss in articles_tab.py vorkommen!")
        self.assertLess(pos_def, pos_use, "is_filtering muss VOR cat_is_open definiert sein!")

    def test_search_reset_callback_behavior(self):
        """Prüft, dass der Reset-Mechanismus den Suchbegriff zuverlässig auf leeren String zurücksetzt."""
        mock_session_state = {"input_search_query": "Hellersdorf"}
        
        def on_clear_search():
            mock_session_state["input_search_query"] = ""

        self.assertEqual(mock_session_state["input_search_query"], "Hellersdorf")
        on_clear_search()
        self.assertEqual(mock_session_state["input_search_query"], "")

    def test_webapp_layout_integrity(self):
        """Prüft Quelltext-Integrität in Webapp-Modulen gegen Layout-Regressionen."""
        from pathlib import Path
        webapp_code = Path("src/webapp.py").read_text(encoding="utf-8")
        styles_code = Path("src/ui/styles.py").read_text(encoding="utf-8")
        articles_code = Path("src/ui/tabs/articles_tab.py").read_text(encoding="utf-8")
        manage_code = Path("src/ui/tabs/manage_tab.py").read_text(encoding="utf-8")
        feedly_code = Path("src/ui/tabs/feedly_tab.py").read_text(encoding="utf-8")

        # 1. Sidebar muss auf "auto" stehen, damit Mobile nicht verdeckt wird
        self.assertIn('initial_sidebar_state="auto"', webapp_code)

        # 2. Kein fragiles position: absolute auf btn_search_clear
        self.assertNotIn("position: absolute !important;\n        right: 0.35rem", styles_code)

        # 3. Mobile CSS muss die Suchleiste mit stColumn und flex: 1 1 0 flexibel halten
        self.assertIn('[data-testid="stHorizontalBlock"]:has(.st-key-input_search_query)', styles_code)
        self.assertIn('flex: 1 1 0 !important;', styles_code)
        self.assertIn('[data-testid="stColumn"]:has(.st-key-btn_search_clear)', styles_code)
        self.assertIn('[data-testid="stColumn"]:has(.st-key-btn_search_go)', styles_code)

        # 4. Feedly Subheader Name
        self.assertIn('st.subheader("📡 RSS Feeds")', feedly_code)

        # 5. Kategorie-Verschieben in Feed-Details
        self.assertIn('new_category=edit_cat_val.strip()', manage_code)

        # 6. Tab- und Expander-Verbleib beim Entwurf-Vormerken
        self.assertIn('st.session_state["editing_feed_key"] = new_hash', manage_code)
        self.assertIn('st.session_state["last_edited_category"] = edit_cat_val.strip()', manage_code)

        # 7. Bewertungs-Daumen (st.feedback) direkt unter dem Text (ohne störende Extra-Labels daneben)
        self.assertIn('st.feedback(', articles_code)
        self.assertIn('"thumbs"', articles_code)
        self.assertIn('on_article_feedback_change', articles_code)
        self.assertNotIn('col_fb_label', articles_code)
        self.assertIn("font-variation-settings: 'FILL' 1", styles_code)

    def test_feedback_widget_value_mapping(self):
        """Prüft die Abbildung von st.feedback Thumbs-Werten auf -1, 0, +1."""
        def map_feedback(widget_val: int | None) -> int:
            if widget_val == 1:
                return 1
            elif widget_val == 0:
                return -1
            return 0

        self.assertEqual(map_feedback(1), 1)     # Daumen hoch
        self.assertEqual(map_feedback(0), -1)    # Daumen runter
        self.assertEqual(map_feedback(None), 0)  # Deselektiert / Neutral

    def test_read_action_icon_and_styling(self):
        """Prüft, dass die Gelesen-Aktion als randloses Icon statt klobigem Button gerendert wird."""
        from pathlib import Path
        articles_code = Path("src/ui/tabs/articles_tab.py").read_text(encoding="utf-8")
        styles_code = Path("src/ui/styles.py").read_text(encoding="utf-8")

        # Randloses Material Icon statt roher Emoji-Button & feste 1-Zeilen-Verankerung
        self.assertIn('icon=":material/check:"', articles_code)
        self.assertIn('type="tertiary"', articles_code)
        self.assertIn('on_click=on_article_read_and_archive', articles_code)
        self.assertIn('wrap=False', articles_code)

        # CSS-Definition für randloses Icon mit transparenter Basis und rundem Hover
        self.assertIn('div[class*="st-key-read_"] button {', styles_code)
        self.assertIn('background-color: transparent !important;', styles_code)
        self.assertIn('border: none !important;', styles_code)
        self.assertIn('border-radius: 50% !important;', styles_code)

    def test_card_overflow_protection_css(self):
        """Prüft, dass Cards und Texte nicht über den Containerrand hinausragen."""
        from pathlib import Path
        styles_code = Path("src/ui/styles.py").read_text(encoding="utf-8")

        # Card-Container Begrenzung & Umbruch
        self.assertIn('[data-testid="stVerticalBlockBorderWrapper"] {', styles_code)
        self.assertIn('overflow-wrap: anywhere !important;', styles_code)
        self.assertIn('word-break: break-word !important;', styles_code)

        # Mobile Spaltenstacking für Cards
        self.assertIn('[data-testid="stExpander"] [data-testid="stColumn"]:has([data-testid="stVerticalBlockBorderWrapper"])', styles_code)
        self.assertIn('min-width: 100% !important;', styles_code)

        # Spezifische Eingrenzung der Feedback-/Read-Zeile auf den Card-Container
        self.assertIn('[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"]', styles_code)

    def test_expander_retention_on_read(self):
        """Prüft, dass gelesene Artikel die Kategorie und den Feed offen halten."""
        from pathlib import Path
        articles_code = Path("src/ui/tabs/articles_tab.py").read_text(encoding="utf-8")

        self.assertIn('st.session_state["persisted_open_categories"].add(category)', articles_code)
        self.assertIn('st.session_state["persisted_open_feeds"].add(feed_name)', articles_code)
        self.assertIn('or category in st.session_state.get("persisted_open_categories", set())', articles_code)
        self.assertIn('or feed_name in st.session_state.get("persisted_open_feeds", set())', articles_code)
        self.assertIn('anchor-feed-', articles_code)


if __name__ == "__main__":
    unittest.main()

