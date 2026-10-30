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
    def test_clean_and_enhance_briefing_removes_summary_and_caps_at_top_5(self):
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
        # Keine Zusammenfassungs-Infobox mehr!
        self.assertNotIn("💡 **Kompakt:**", result)
        self.assertIn("Streamlit App", result)
        self.assertIn("[A](http://a)", result)
        self.assertIn("[E](http://e)", result)
        # Artikel über Top 5 hinaus werden ausgeschlossen
        self.assertNotIn("[F](http://f)", result)
        self.assertNotIn("[G](http://g)", result)

    def test_clean_and_enhance_briefing_preserves_multiline_joke(self):
        text = """## 😂 Fun
> 🔗 [Streamlit App](http://app)
- **[Witz des Tages](http://joke)**:
Treffen sich zwei Blondinen.
"Ich hatte gestern Führerscheinprüfung und bin durchgefallen."
"Warum denn das?"
"Naja, ich bin Landstraße gefahren..."
"""
        cat_links = {"Fun": "> 🔗 [Streamlit App](http://app)"}
        result = _clean_and_enhance_briefing(text, cat_links)

        self.assertIn("## 😂 Fun", result)
        self.assertIn("[Witz des Tages](http://joke)", result)
        self.assertIn("Treffen sich zwei Blondinen.", result)
        self.assertIn("Führerscheinprüfung", result)

    def test_fallback_summary_contains_no_infobox_and_renders_jokes_fully(self):
        news = {
            "Fun": [
                {
                    "title": "Treffen sich zwei Blondinen",
                    "link": "http://hahaha.de/123",
                    "summary": "Treffen sich zwei Blondinen.\n\"Ich hatte gestern Führerscheinprüfung.\"",
                    "source": "Witz des Tages",
                }
            ],
            "Berlin": [
                {"title": f"Meldung {i}", "link": f"http://berlin.de/{i}", "summary": f"Text {i}"}
                for i in range(1, 10)
            ]
        }
        res = _generate_fallback_summary(
            news,
            category_links={
                "Fun": "> 🔗 [Streamlit App](http://app/fun)",
                "Berlin": "> 🔗 [Streamlit App](http://app/berlin)",
            }
        )
        self.assertIn("## Berlin", res)
        # Keine Zusammenfassungs-Infoboxen mehr
        self.assertNotIn("> 💡 **Kompakt:**", res)
        self.assertIn("Meldung 1", res)
        self.assertIn("Meldung 5", res)
        self.assertNotIn("Meldung 6", res)

        # Spezialfall Witz: vollständig als Text
        self.assertIn("## Fun", res)
        self.assertIn("Treffen sich zwei Blondinen", res)
        self.assertIn("Führerscheinprüfung", res)

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

    def test_email_rendering_with_quicklinks_and_multiline_joke(self):
        md = """## 🤖 Tech & AI

> 🔗 [Streamlit App](http://app)

- **[Titel 1](http://t1)**: Tatsächlicher Inhalt der Meldung ohne Schwurbeln.

## 😂 Fun

> 🔗 [Streamlit App](http://app/fun)

- **[Witz des Tages](http://joke)**:
Treffen sich zwei Blondinen.
"Ich hatte gestern Führerscheinprüfung."
"""
        html = markdown_to_html_email(md)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Streamlit App", html)
        self.assertIn("Tatsächlicher Inhalt der Meldung", html)
        self.assertIn("Treffen sich zwei Blondinen.", html)
        self.assertIn("Führerscheinprüfung.", html)

    def test_gemini_models_and_fallback_order(self):
        """Prüft die verfügbaren Modelle (mit gemini-3.5-flash-lite als Standard) und die Fallback-Kette."""
        expected_models = [
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
        ]
        self.assertEqual(AVAILABLE_GEMINI_MODELS, expected_models)
        self.assertEqual(DEFAULT_GEMINI_MODEL, "gemini-3.5-flash-lite")

        # Standardauswahl ohne explizite Angabe
        candidates = get_candidate_models()
        self.assertEqual(candidates, expected_models)
        self.assertEqual(candidates[0], "gemini-3.5-flash-lite")

        # Auswahl mit bevorzugtem Modell
        candidates_36 = get_candidate_models("gemini-3.6-flash")
        self.assertEqual(candidates_36[0], "gemini-3.6-flash")
        self.assertEqual(set(candidates_36), set(expected_models))
        self.assertEqual(len(candidates_36), len(expected_models))

        # Nicht verfügbares / veraltetes Modell fällt sauber auf DEFAULT_GEMINI_MODEL zurück
        candidates_invalid = get_candidate_models("gemini-3.8-flash")
        self.assertEqual(candidates_invalid[0], "gemini-3.5-flash-lite")
        self.assertEqual(candidates_invalid, expected_models)

    def test_sources_yaml_and_canonical_prompt_match_strictly(self):
        """Prüft strikte 1:1 Übereinstimmung zwischen prompts.yaml/sources.yaml und kanonischem DEFAULT_MAIN_PROMPT_TEMPLATE / DIRECTIVES."""
        from src.aggregator import load_sources, load_prompts

        # 1. Teste direktes Laden über load_prompts
        prompts = load_prompts()
        prm_prompt = prompts.get("custom_main_prompt", "").strip()
        canonical_prompt = DEFAULT_MAIN_PROMPT_TEMPLATE.strip()
        self.assertEqual(
            prm_prompt,
            canonical_prompt,
            "custom_main_prompt in prompts.yaml weicht 1:1 von DEFAULT_MAIN_PROMPT_TEMPLATE ab!",
        )

        prm_directives = prompts.get("custom_prompt_directives", "").strip()
        canonical_directives = DEFAULT_DIRECTIVES.strip()
        self.assertTrue(
            canonical_directives in prm_directives or prm_directives.startswith(canonical_directives),
            "custom_prompt_directives in prompts.yaml muss die Basis-Richtlinien von DEFAULT_DIRECTIVES enthalten!",
        )

        # 2. Teste transparente Fassade über load_sources
        sources = load_sources(auto_reconcile=False)
        yaml_prompt = sources.get("settings", {}).get("custom_main_prompt", "").strip()
        self.assertEqual(
            yaml_prompt,
            canonical_prompt,
            "custom_main_prompt in load_sources weicht 1:1 von DEFAULT_MAIN_PROMPT_TEMPLATE ab!",
        )

        yaml_directives = sources.get("settings", {}).get("custom_prompt_directives", "").strip()
        self.assertTrue(
            canonical_directives in yaml_directives or yaml_directives.startswith(canonical_directives),
            "custom_prompt_directives in load_sources muss die Basis-Richtlinien von DEFAULT_DIRECTIVES enthalten!",
        )

    def test_reconcile_prompt_templates_initializes_missing_prompts(self):
        """Prüft, dass der Abgleich fehlende oder leere Prompts automatisch 1:1 mit den Standards initialisiert."""
        from src.aggregator import reconcile_prompt_templates

        # Fall 1: Leere Konfiguration -> initialisiert 1:1 mit den Standards
        empty_config = {}
        changed_empty = reconcile_prompt_templates(empty_config)
        self.assertTrue(changed_empty)
        self.assertEqual(empty_config["settings"]["custom_main_prompt"], DEFAULT_MAIN_PROMPT_TEMPLATE.strip())
        self.assertEqual(empty_config["settings"]["custom_prompt_directives"], DEFAULT_DIRECTIVES.strip())

        # Fall 2: Bereits initialisierte Konfiguration -> Keine erneute Änderung
        changed_again = reconcile_prompt_templates(empty_config)
        self.assertFalse(changed_again)

        # Fall 3: Vom Nutzer bewusst modifizierter Prompt -> Bleibt erhalten und wird nicht überschrieben
        custom_config = {"settings": {"custom_main_prompt": "Mein eigener benutzerdefinierter Redaktionsprompt"}}
        changed_custom = reconcile_prompt_templates(custom_config)
        self.assertEqual(custom_config["settings"]["custom_main_prompt"], "Mein eigener benutzerdefinierter Redaktionsprompt")


if __name__ == "__main__":
    unittest.main()
