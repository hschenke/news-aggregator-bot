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

    def test_update_feed_move_to_existing_category(self):
        # Feed aus 'Berlin' nach 'Tech' verschieben
        res = update_feed(
            category_name="Berlin",
            old_url="https://www.berlin.de/polizei/polizeimeldungen/index.php/rss",
            new_category="Tech",
            config=self.config,
            save_to_disk=False,
        )
        self.assertTrue(res)
        berlin_cat = next(c for c in self.config["categories"] if c["name"] == "Berlin")
        tech_cat = next(c for c in self.config["categories"] if c["name"] == "Tech")
        self.assertEqual(len(berlin_cat["feeds"]), 0)
        self.assertEqual(len(tech_cat["feeds"]), 2)
        moved_feed = next(f for f in tech_cat["feeds"] if "berlin.de" in f["url"])
        self.assertEqual(moved_feed["name"], "Polizeimeldungen Berlin")

    def test_update_feed_move_to_new_category(self):
        # Feed in eine ganz neue Kategorie verschieben
        res = update_feed(
            category_name="Berlin",
            old_url="https://www.berlin.de/polizei/polizeimeldungen/index.php/rss",
            new_name="Polizei News",
            new_category="Blaulicht & Sicherheit",
            config=self.config,
            save_to_disk=False,
        )
        self.assertTrue(res)
        cat_names = [c["name"] for c in self.config["categories"]]
        self.assertIn("Blaulicht & Sicherheit", cat_names)
        new_cat = next(c for c in self.config["categories"] if c["name"] == "Blaulicht & Sicherheit")
        self.assertEqual(len(new_cat["feeds"]), 1)
        self.assertEqual(new_cat["feeds"][0]["name"], "Polizei News")

    def test_update_feed_move_and_change_url_simultaneously(self):
        # URL und Kategorie gleichzeitig ändern
        res = update_feed(
            category_name="Berlin",
            old_url="https://www.berlin.de/polizei/polizeimeldungen/index.php/rss",
            new_url="https://www.berlin.de/polizei/neuer_feed.xml",
            new_name="Berlin Polizei Neu",
            new_category="Tech",
            config=self.config,
            save_to_disk=False,
        )
        self.assertTrue(res)
        berlin_cat = next(c for c in self.config["categories"] if c["name"] == "Berlin")
        tech_cat = next(c for c in self.config["categories"] if c["name"] == "Tech")
        self.assertEqual(len(berlin_cat["feeds"]), 0)
        self.assertEqual(len(tech_cat["feeds"]), 2)
        moved_feed = next(f for f in tech_cat["feeds"] if f["url"] == "https://www.berlin.de/polizei/neuer_feed.xml")
        self.assertEqual(moved_feed["name"], "Berlin Polizei Neu")

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
                "max_article_age_weeks": 12,
                "custom_prompt_directives": "Keine Filter anwenden."
            },
            config=self.config,
            save_to_disk=False
        )
        s = self.config["settings"]
        self.assertFalse(s["filter_ads"])
        self.assertEqual(s["ad_keywords"], ["werbung", "deal"])
        self.assertEqual(s["max_article_age_weeks"], 12)
        self.assertEqual(s["custom_prompt_directives"], "Keine Filter anwenden.")

    def test_yaml_files_extension_standardization(self):
        """Stellt sicher, dass alle YAML-Dateien im Repository auf .yaml enden und keine .yml-Dateien existieren."""
        from pathlib import Path
        repo_root = Path(__file__).resolve().parent.parent
        yml_files = []
        for p in repo_root.rglob("*.yml"):
            # Ignoriere versteckte Cache/Venv Ordner
            parts = p.parts
            if any(part.startswith(".") and part not in [".github", ".streamlit"] for part in parts) or ".venv" in parts:
                continue
            yml_files.append(p.relative_to(repo_root).as_posix())

        self.assertEqual(yml_files, [], f"Es wurden Dateien mit der veralteten Endung .yml gefunden: {yml_files}")

    def test_split_config_files_structure(self):
        """Prüft, dass sources.yaml, settings.yaml und prompts.yaml sauber aufgeteilt existieren."""
        from pathlib import Path
        import yaml
        from src.aggregator import (
            load_sources,
            load_sources_raw,
            load_settings,
            load_prompts,
            get_sources_path,
            get_settings_path,
            get_prompts_path,
        )

        sources_path = get_sources_path()
        settings_path = get_settings_path()
        prompts_path = get_prompts_path()

        self.assertTrue(sources_path.exists(), "config/sources.yaml existiert nicht!")
        self.assertTrue(settings_path.exists(), "config/settings.yaml existiert nicht!")
        self.assertTrue(prompts_path.exists(), "config/prompts.yaml existiert nicht!")

        # sources.yaml darf nur categories enthalten, keine settings
        raw_sources = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
        self.assertIn("categories", raw_sources)
        self.assertNotIn("settings", raw_sources, "sources.yaml darf nach dem Aufsplitten keinen 'settings'-Block mehr enthalten!")

        # settings.yaml enthält globale Einstellungen
        raw_settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        self.assertIn("language", raw_settings)
        self.assertIn("archive_retention_days", raw_settings)
        self.assertIn("filter_ads", raw_settings)
        self.assertIn("ad_keywords", raw_settings)
        self.assertNotIn("custom_main_prompt", raw_settings, "settings.yaml darf keine Prompt-Definitionen enthalten!")

        # prompts.yaml enthält Hauptprompt & Direktiven
        raw_prompts = yaml.safe_load(prompts_path.read_text(encoding="utf-8"))
        self.assertIn("custom_main_prompt", raw_prompts)
        self.assertIn("custom_prompt_directives", raw_prompts)

        # load_sources() führt alles transparent zusammen
        combined = load_sources(auto_reconcile=False)
        self.assertIn("categories", combined)
        self.assertIn("settings", combined)
        self.assertEqual(combined["settings"]["language"], raw_settings["language"])
        self.assertEqual(combined["settings"]["custom_main_prompt"], raw_prompts["custom_main_prompt"])

    def test_isolated_config_loaders_and_savers(self):
        """Testet isolierte Lade- und Speichermethoden für getrennte Konfigurationen."""
        import tempfile
        import shutil
        from pathlib import Path
        from src.aggregator import (
            load_sources,
            save_sources,
            load_settings,
            save_settings,
            load_prompts,
            save_prompts,
        )

        temp_dir = Path(tempfile.mkdtemp())
        try:
            src_file = temp_dir / "sources.yaml"
            set_file = temp_dir / "settings.yaml"
            prm_file = temp_dir / "prompts.yaml"

            # 1. Speichern einzelner Konfigurationen
            save_settings({"language": "fr", "filter_ads": False}, config_path=str(set_file))
            loaded_set = load_settings(str(set_file))
            self.assertEqual(loaded_set["language"], "fr")
            self.assertFalse(loaded_set["filter_ads"])

            save_prompts({"custom_main_prompt": "Test Prompt", "custom_prompt_directives": "Dir"}, config_path=str(prm_file))
            loaded_prm = load_prompts(str(prm_file))
            self.assertEqual(loaded_prm["custom_main_prompt"], "Test Prompt")

            # 2. Speichern & Laden über die integrierte Schnittstelle
            integrated_cfg = {
                "categories": [{"name": "Lokal", "feeds": [{"name": "F1", "url": "https://example.com/rss"}]}],
                "settings": {"language": "it", "custom_main_prompt": "Italienischer Prompt"}
            }
            save_sources(integrated_cfg, config_path=str(src_file), sync_github=False)
            loaded_all = load_sources(config_path=str(src_file), auto_reconcile=False)
            self.assertEqual(len(loaded_all["categories"]), 1)
            self.assertEqual(loaded_all["settings"]["language"], "it")
            self.assertEqual(loaded_all["settings"]["custom_main_prompt"], "Italienischer Prompt")

            # 3. update_settings ohne config-Objekt aktualisiert direkt settings.yaml & prompts.yaml
            from src.sources_manager import update_settings
            update_settings(
                {"language": "es", "custom_main_prompt": "Spanischer Prompt"},
                config_path=str(set_file),
                config=None,
                save_to_disk=True,
            )
            updated_set = load_settings(str(set_file))
            updated_prm = load_prompts(str(prm_file))
            self.assertEqual(updated_set["language"], "es")
            self.assertNotIn("custom_main_prompt", updated_set)
            self.assertEqual(updated_prm["custom_main_prompt"], "Spanischer Prompt")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
