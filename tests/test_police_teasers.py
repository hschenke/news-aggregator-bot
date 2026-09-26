"""
Automatisierte Unittests für die Extraktion und das Caching von Berliner Polizeimeldungen sowie den Pool-Status.
"""

import unittest
from unittest.mock import patch, MagicMock
from src.aggregator import (
    extract_police_teaser,
    _POLICE_TEASER_CACHE,
    get_new_articles_count,
    save_pool_state,
)


class TestPoliceTeasersAndPool(unittest.TestCase):

    def setUp(self):
        _POLICE_TEASER_CACHE.clear()

    @patch("src.aggregator.requests.get")
    def test_extract_police_teaser_with_district(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"
        mock_response.text = """
        <html>
            <body>
                <p class="polizeimeldung" title="Ereignisort">Mahlsdorf</p>
                <div class="textile">
                    <p>In den frühen Morgenstunden kam es zu einem Einbruch in ein Einfamilienhaus in Mahlsdorf.</p>
                </div>
            </body>
        </html>
        """
        mock_get.return_value = mock_response

        url = "https://www.berlin.de/polizei/polizeimeldungen/2026/meldung.12345.php"
        teaser = extract_police_teaser(url)

        self.assertTrue(teaser.startswith("📍 **Mahlsdorf** –"))
        self.assertIn("Einbruch in ein Einfamilienhaus in Mahlsdorf", teaser)

        # Caching prüfen: Beim zweiten Aufruf darf requests.get nicht noch einmal aufgerufen werden
        mock_get.reset_mock()
        cached_teaser = extract_police_teaser(url)
        self.assertEqual(cached_teaser, teaser)
        mock_get.assert_not_called()

    def test_pool_state_tracking(self):
        test_news = {
            "Berlin": [
                {"title": "Meldung 1", "link": "https://example.com/1"},
                {"title": "Meldung 2", "link": "https://example.com/2"}
            ]
        }
        test_path = "output/test_pool_state_tmp.json"
        
        # Initialer Save
        save_pool_state(test_news, state_path=test_path)
        
        # Bei unverändertem Pool gibt es 0 neue Artikel
        new_count = get_new_articles_count(test_news, state_path=test_path)
        self.assertEqual(new_count, 0)

        # Ein neuer Artikel kommt hinzu
        test_news_updated = {
            "Berlin": [
                {"title": "Meldung 1", "link": "https://example.com/1"},
                {"title": "Meldung 2", "link": "https://example.com/2"},
                {"title": "Meldung 3", "link": "https://example.com/3"}
            ]
        }
        new_count_updated = get_new_articles_count(test_news_updated, state_path=test_path)
        self.assertEqual(new_count_updated, 1)

        # Aufräumen
        import os
        if os.path.exists(test_path):
            os.remove(test_path)


if __name__ == "__main__":
    unittest.main()
