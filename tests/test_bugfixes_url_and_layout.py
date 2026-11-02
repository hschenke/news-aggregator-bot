"""
Tests for URL sanitization in emails/briefings and row-based article layout.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.filters import sanitize_markdown_url
from src.summarizer import _sanitize_briefing_urls, _clean_and_enhance_briefing
from src.notifier import markdown_to_html_email
from src.rss_generator import extract_briefing_articles, export_briefing_rss


class TestUrlSanitizationAndArticleLayout(unittest.TestCase):
    def test_sanitize_markdown_url_removes_trailing_hyphens(self) -> None:
        """Prüft, dass störende nachgestellte Bindestriche und Satzzeichen zuverlässig entfernt werden."""
        # 1. URL mit nachgestelltem Bindestrich (Bug aus Nutzeranfrage)
        url1 = "https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre-"
        self.assertEqual(
            sanitize_markdown_url(url1),
            "https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre",
        )

        # 2. Mehrere Bindestriche am Ende
        url2 = "https://debeste.de/634178/Ich-habe-eine-Idee-f-r-ein-H-rbuch-8-Stunden-lang-nur---"
        self.assertEqual(
            sanitize_markdown_url(url2),
            "https://debeste.de/634178/Ich-habe-eine-Idee-f-r-ein-H-rbuch-8-Stunden-lang-nur",
        )

        # 3. Bindestrich gefolgt von Satzzeichen
        url3 = "https://allianz-arena.com/de/news/2026/11/fc-bayern-empfaengt-hertha-bsc-im-dfb-pokal-achtelfinale-2026-27-."
        self.assertEqual(
            sanitize_markdown_url(url3),
            "https://allianz-arena.com/de/news/2026/11/fc-bayern-empfaengt-hertha-bsc-im-dfb-pokal-achtelfinale-2026-27",
        )

        # 4. Normale URLs mit internen Bindestrichen (Slugs) bleiben unangetastet
        url_normal = "https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre"
        self.assertEqual(sanitize_markdown_url(url_normal), url_normal)

        # 5. URLs mit abschließendem Schrägstrich
        url_slash = "https://example.com/category/slug/"
        self.assertEqual(sanitize_markdown_url(url_slash), url_slash)

        # 6. Leere Eingaben
        self.assertEqual(sanitize_markdown_url(""), "")
        self.assertEqual(sanitize_markdown_url("   "), "")

        # 7. URL mit Query-Parametern und nachgestelltem Bindestrich im Pfad
        url_query = "https://example.com/news/slug-?utm_source=feed"
        self.assertEqual(sanitize_markdown_url(url_query), "https://example.com/news/slug?utm_source=feed")

    def test_sanitize_briefing_urls_reconciles_with_known_urls(self) -> None:
        """Prüft, dass Markdown-Links im Briefing-Text bereinigt und mit echten Feed-URLs abgeglichen werden."""
        md_text = (
            "## 🤖 Tech & AI\n\n"
            "- **[ChatGPT mehrere Abos](https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre-)**: OpenAI führt Kontowechsel ein.\n"
        )
        known = {
            "https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre": "https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre"
        }
        cleaned = _sanitize_briefing_urls(md_text, known_urls_map=known)
        self.assertIn("https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre", cleaned)
        self.assertNotIn("chatgpt-abos-switch-sperre-", cleaned)

    def test_clean_and_enhance_briefing_sanitizes_urls(self) -> None:
        """Prüft, dass _clean_and_enhance_briefing die URLs bereinigt."""
        md_text = (
            "## 🤖 Tech & AI\n\n"
            "- **[ChatGPT mehrere Abos](https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre-)**: Beschreibung.\n"
        )
        result = _clean_and_enhance_briefing(md_text, category_links={})
        self.assertIn("https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre", result)
        self.assertNotIn("chatgpt-abos-switch-sperre-", result)

    def test_email_html_generation_has_no_trailing_hyphens_in_links(self) -> None:
        """Prüft, dass die erzeugte HTML-E-Mail keine Links mit nachgestelltem Bindestrich enthält."""
        md_text = (
            "## 🤖 Tech & AI\n\n"
            "- **[ChatGPT mehrere Abos](https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre-)**: Tatsächlicher Inhalt.\n"
        )
        html_email = markdown_to_html_email(md_text)
        self.assertIn('href="https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre"', html_email)
        self.assertNotIn('href="https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre-"', html_email)

    def test_extract_briefing_articles_sanitizes_urls(self) -> None:
        """Prüft, dass extract_briefing_articles URLs ohne nachgestellten Bindestrich extrahiert."""
        md_text = (
            "## 🤖 Tech & AI\n\n"
            "- **[ChatGPT mehrere Abos](https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre-)**: Beschreibung.\n"
        )
        extracted = extract_briefing_articles(md_text)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(
            extracted[0]["link"],
            "https://www.all-ai.de/news/news26top/chatgpt-abos-switch-sperre",
        )

    def test_articles_tab_uses_row_based_grid_rendering(self) -> None:
        """Prüft, dass articles_tab.py ein zeilenweises Grid nutzt, um das Vertauschen von Artikeln zu verhindern."""
        code = Path("src/ui/tabs/articles_tab.py").read_text(encoding="utf-8")
        self.assertIn("range(0, len(visible_items), 2)", code)
        self.assertNotIn("for idx, item in enumerate(visible_items):\n                        with cols[idx % 2]:", code)

    def test_archive_tab_uses_row_based_grid_rendering(self) -> None:
        """Prüft, dass archive_tab.py ein zeilenweises Grid nutzt."""
        code = Path("src/ui/tabs/archive_tab.py").read_text(encoding="utf-8")
        self.assertIn("range(0, len(visible_articles), 2)", code)
        self.assertNotIn("for idx, art in enumerate(visible_articles):\n                        art_hash", code)


if __name__ == "__main__":
    unittest.main()
