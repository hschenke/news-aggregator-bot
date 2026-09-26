"""
Automatisierte Unittests für die Verwaltung von Quellen, Kategorien und Keywords (sources.yaml).
"""

import unittest
from src.aggregator import (
    normalize_keywords,
    add_category,
    rename_category,
    delete_category,
    add_feed,
    update_feed,
    delete_feed,
    update_settings,
)


class TestSourcesManagement(unittest.TestCase):

    def setUp(self):
        # Frische In-Memory Testkonfiguration
        self.config = {
            "categories": [
                {
                    "name": "Berlin",
                    "feeds": [
                        {
                            "name": "Polizeimeldungen Berlin",
                            "url": "https://www.berlin.de/polizei/polizeimeldungen/index.php/rss",
                            "include_keywords": ["Mitte", "Friedrichshain"]
                        }
                    ]
                },
                {
                    "name": "Tech",
                    "feeds": [
                        {
                            "name": "Heise",
                            "url": "https://www.heise.de/rss/heise-atom.xml"
                        }
                    ]
                }
            ],
            "settings": {
                "language": "de",
                "filter_ads": True,
                "ad_keywords": ["heise-angebot", "anzeige"]
            }
        }

    def test_normalize_keywords(self):
        # Kommagetrennter String
        self.assertEqual(normalize_keywords("Mahlsdorf, Kaulsdorf"), ["Mahlsdorf", "Kaulsdorf"])
        self.assertEqual(normalize_keywords("  Sport ,  Krypto  "), ["Sport", "Krypto"])
        # Liste
        self.assertEqual(normalize_keywords(["Mitte", "Pankow"]), ["Mitte", "Pankow"])
        # Leere Werte
        self.assertEqual(normalize_keywords(""), [])
        self.assertEqual(normalize_keywords(None), [])
        self.assertEqual(normalize_keywords([]), [])

    def test_add_feed_with_keywords(self):
        add_feed(
            category_name="Berlin",
            feed_name="Berlin Mahlsdorf",
            feed_url="https://example.com/rss",
            include_keywords="Mahlsdorf, Biesdorf",
            exclude_keywords="Unfall",
            config=self.config,
            save_to_disk=False
        )
        cat = next(c for c in self.config["categories"] if c["name"] == "Berlin")
        feed = next(f for f in cat["feeds"] if f["url"] == "https://example.com/rss")
        self.assertEqual(feed["include_keywords"], ["Mahlsdorf", "Biesdorf"])
        self.assertEqual(feed["exclude_keywords"], ["Unfall"])

    def test_update_feed_keywords(self):
        # Update include_keywords auf neuen Wert
        res = update_feed(
            category_name="Berlin",
            old_url="https://www.berlin.de/polizei/polizeimeldungen/index.php/rss",
            include_keywords="Wilmersdorf, Steglitz",
            config=self.config,
            save_to_disk=False
        )
        self.assertTrue(res)
        cat = next(c for c in self.config["categories"] if c["name"] == "Berlin")
        feed = next(f for f in cat["feeds"] if "berlin.de" in f["url"])
        self.assertEqual(feed["include_keywords"], ["Wilmersdorf", "Steglitz"])

    def test_clear_feed_keywords_with_empty_string(self):
        # Testet, dass das Leeren des Textfeldes (leerer String "") die Keywords tatsächlich löscht
        res = update_feed(
            category_name="Berlin",
            old_url="https://www.berlin.de/polizei/polizeimeldungen/index.php/rss",
            include_keywords="",
            exclude_keywords="",
            config=self.config,
            save_to_disk=False
        )
        self.assertTrue(res)
        cat = next(c for c in self.config["categories"] if c["name"] == "Berlin")
        feed = next(f for f in cat["feeds"] if "berlin.de" in f["url"])
        self.assertNotIn("include_keywords", feed)
        self.assertNotIn("exclude_keywords", feed)

    def test_category_crud_operations(self):
        # Add category
        self.assertTrue(add_category("Wissenschaft", config=self.config, save_to_disk=False))
        # Rename category
        self.assertTrue(rename_category("Wissenschaft", "Science & Tech", config=self.config, save_to_disk=False))
        names = [c["name"] for c in self.config["categories"]]
        self.assertIn("Science & Tech", names)
        # Delete category
        self.assertTrue(delete_category("Science & Tech", config=self.config, save_to_disk=False))
        names_after = [c["name"] for c in self.config["categories"]]
        self.assertNotIn("Science & Tech", names_after)

    def test_update_settings(self):
        update_settings(
            {
                "filter_ads": False,
                "ad_keywords": ["werbung", "deal"],
                "custom_prompt_directives": "Keine Filter anwenden."
            },
            config=self.config,
            save_to_disk=False
        )
        s = self.config["settings"]
        self.assertFalse(s["filter_ads"])
        self.assertEqual(s["ad_keywords"], ["werbung", "deal"])
        self.assertEqual(s["custom_prompt_directives"], "Keine Filter anwenden.")


if __name__ == "__main__":
    unittest.main()
