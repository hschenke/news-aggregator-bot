"""
Unittests für die Article-Dataclass und deren Abwärtskompatibilität.
"""

import unittest
from src.models import Article


class TestArticleModel(unittest.TestCase):

    def test_article_creation_and_attributes(self):
        art = Article(
            title="Neues Modell veröffentlicht",
            link="https://example.com/news/1",
            summary="Eine kurze Zusammenfassung.",
            source="TechNews",
            category="Tech & AI",
            timestamp=1700000000.0,
        )
        self.assertEqual(art.title, "Neues Modell veröffentlicht")
        self.assertEqual(art.link, "https://example.com/news/1")
        self.assertEqual(art.summary, "Eine kurze Zusammenfassung.")
        self.assertEqual(art.source, "TechNews")
        self.assertEqual(art.category, "Tech & AI")
        self.assertEqual(art.timestamp, 1700000000.0)

    def test_article_mapping_compatibility(self):
        art = Article(
            title="Mapping Test",
            link="https://example.com/map",
            summary="Subscripting funktioniert wie ein Dictionary.",
            extra={"custom_field": 42},
        )
        # Test subscripting
        self.assertEqual(art["title"], "Mapping Test")
        self.assertEqual(art["custom_field"], 42)
        # Test .get()
        self.assertEqual(art.get("title"), "Mapping Test")
        self.assertEqual(art.get("nonexistent", "default"), "default")
        # Test in operator
        self.assertIn("title", art)
        self.assertIn("custom_field", art)
        self.assertNotIn("unknown", art)

    def test_from_dict_and_to_dict(self):
        raw_dict = {
            "title": "Dict Import Test",
            "link": "https://example.com/dict",
            "summary": "Import aus RSS-Dict",
            "source": "RSS Feed",
            "timestamp": "1700000000",
            "arbitrary_meta": "extra_value",
        }
        art = Article.from_dict(raw_dict)
        self.assertIsInstance(art, Article)
        self.assertEqual(art.title, "Dict Import Test")
        self.assertEqual(art.timestamp, 1700000000.0)
        self.assertEqual(art["arbitrary_meta"], "extra_value")

        exported = art.to_dict()
        self.assertIsInstance(exported, dict)
        self.assertEqual(exported["title"], "Dict Import Test")
        self.assertEqual(exported["arbitrary_meta"], "extra_value")


if __name__ == "__main__":
    unittest.main()
