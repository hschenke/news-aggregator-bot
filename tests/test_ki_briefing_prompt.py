import unittest
from src.summarizer import (
    _clean_and_enhance_briefing,
    _generate_fallback_summary,
    DEFAULT_MAIN_PROMPT_TEMPLATE,
    DEFAULT_DIRECTIVES,
    AVAILABLE_GEMINI_MODELS,
    DEFAULT_GEMINI_MODEL,
    get_candidate_models,
)
from src.notifier import markdown_to_html_email


class TestKiBriefingPrompt(unittest.TestCase):
    def test_clean_and_enhance_briefing_caps_at_top_5(self):
        text = """## 🤖 Tech & AI
> 💡 **Kompakt:** Die wichtigsten News zusammengefasst in zwei Sätzen.
- **[A](http://a)**: Beschreibung 1
- **[B](http://b)**: Beschreibung 2
- **[C](http://c)**: Beschreibung 3
- **[D](http://d)**: Beschreibung 4
- **[E](http://e)**: Beschreibung 5
- **[F](http://f)**: Beschreibung 6
- **[G](http://g)**: Beschreibung 7
"""
        cat_links = {"Tech & AI": "> 🔗 [Streamlit App](http://app)"}
        result = _clean_and_enhance_briefing(text, cat_links)

        self.assertIn("## 🤖 Tech & AI", result)
        self.assertIn("💡 **Kompakt:**", result)
        self.assertIn("Streamlit App", result)
        self.assertIn("[A](http://a)", result)
        self.assertIn("[E](http://e)", result)
        # Articles beyond Top 5 must be excluded
        self.assertNotIn("[F](http://f)", result)
        self.assertNotIn("[G](http://g)", result)

    def test_fallback_summary_contains_infobox_and_top_5(self):
        news = {
            "Berlin": [
                {"title": f"Meldung {i}", "link": f"http://berlin.de/{i}", "summary": f"Text {i}"}
                for i in range(1, 10)
            ]
        }
        res = _generate_fallback_summary(news, category_links={"Berlin": "> 🔗 [Streamlit App](http://app)"})
        self.assertIn("## Berlin", res)
        self.assertIn("> 💡 **Kompakt:**", res)
        self.assertIn("Meldung 1", res)
        self.assertIn("Meldung 5", res)
        self.assertNotIn("Meldung 6", res)

    def test_liked_articles_prioritized_in_briefing(self):
        # Meldung 9 ist geliked (feedback=1), Meldung 1 ist neutral, Meldung 2 ist disliked (feedback=-1)
        news = {
            "Berlin": [
                {"title": "Meldung 1 Neutral", "link": "http://berlin.de/1", "summary": "Text 1", "timestamp": 100.0, "feedback": 0},
                {"title": "Meldung 2 Disliked", "link": "http://berlin.de/2", "summary": "Text 2", "timestamp": 200.0, "feedback": -1},
                {"title": "Meldung 9 Liked", "link": "http://berlin.de/9", "summary": "Text 9", "timestamp": 50.0, "feedback": 1},
            ]
        }
        res = _generate_fallback_summary(news)
        lines = [line for line in res.split("\n") if line.startswith("- **[")]
        # Liked item must come FIRST even though its timestamp is older than Neutral
        self.assertIn("Meldung 9 Liked", lines[0])
        # Neutral comes second
        self.assertIn("Meldung 1 Neutral", lines[1])
        # Disliked comes last
        self.assertIn("Meldung 2 Disliked", lines[2])

    def test_email_rendering_styles_infobox_distinctly(self):
        md = """## 🤖 Tech & AI

> 💡 **Kompakt:** KI-Trends von heute.

> 🔗 [Streamlit App](http://app)

- **[Titel 1](http://t1)**: News 1
"""
        html = markdown_to_html_email(md)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Kompakt:", html)
        self.assertIn("#eff6ff", html)  # Infobox background color
        self.assertIn("#2563eb", html)  # Infobox border accent
        self.assertIn("Streamlit App", html)

    def test_gemini_models_and_fallback_order(self):
        """Prüft die absteigende Sortierung der Modelle (3.8 bis 3.5) und die Fallback-Kette."""
        expected_models = [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
        ]
        self.assertEqual(AVAILABLE_GEMINI_MODELS, expected_models)
        self.assertEqual(DEFAULT_GEMINI_MODEL, "gemini-3.8-flash")

        # Standardauswahl ohne explizite Angabe
        candidates = get_candidate_models()
        self.assertEqual(candidates, expected_models)
        self.assertEqual(candidates[0], "gemini-3.8-flash")

        # Auswahl mit bevorzugtem Modell
        candidates_36 = get_candidate_models("gemini-3.6-flash")
        self.assertEqual(candidates_36[0], "gemini-3.6-flash")
        self.assertEqual(set(candidates_36), set(expected_models))
        self.assertEqual(len(candidates_36), len(expected_models))

    def test_prompt_template_and_sources_include_feedback_directives(self):
        """Stellt sicher, dass sowohl DEFAULT_MAIN_PROMPT_TEMPLATE als auch sources.yaml die Like/Dislike-Regeln enthalten."""
        from src.aggregator import load_sources

        self.assertIn("⭐ [NUTZER-FAVORIT / GELIKED]", DEFAULT_MAIN_PROMPT_TEMPLATE)
        self.assertIn("⚠️ [VOM NUTZER ALS WENIGER RELEVANT / GEDISLIKED]", DEFAULT_MAIN_PROMPT_TEMPLATE)

        sources = load_sources()
        yaml_prompt = sources.get("settings", {}).get("custom_main_prompt", "")
        self.assertIn("⭐ [NUTZER-FAVORIT / GELIKED]", yaml_prompt)
        self.assertIn("⚠️ [VOM NUTZER ALS WENIGER RELEVANT / GEDISLIKED]", yaml_prompt)


if __name__ == "__main__":
    unittest.main()
