"""
Tests zur Verifikation der modularen Architektur für v0.20.0.
Stellt sicher, dass die neuen Submodule isoliert importierbar sind
und die Fassaden (src.aggregator, src.storage) 100% abwärtskompatibel bleiben.
"""

import unittest


class TestModularArchitecture(unittest.TestCase):

    def test_storage_package_imports(self):
        """Prüft isolierte Importe aus dem neuen src.storage Paket."""
        from src.storage.base import StorageBackend, get_safe_db_path, get_turso_config
        from src.storage.sqlite import SqliteStorage
        from src.storage.turso import TursoStorage
        from src.storage import get_storage, reset_storage_singleton

        self.assertTrue(issubclass(SqliteStorage, StorageBackend))
        self.assertTrue(issubclass(TursoStorage, StorageBackend))
        self.assertTrue(callable(get_storage))
        self.assertTrue(callable(reset_storage_singleton))

    def test_filters_module_imports(self):
        """Prüft isolierte Importe aus src.filters."""
        from src.filters import (
            clean_html_text,
            format_summary_html,
            unwrap_and_clean_url,
            get_canonical_url,
            is_ad_item,
            is_article_too_old,
            filter_articles_by_age,
        )
        self.assertEqual(clean_html_text("<b>Hallo</b> &amp; Welt"), "Hallo & Welt")
        self.assertEqual(unwrap_and_clean_url("https://example.com/item"), "https://example.com/item")
        self.assertTrue(is_ad_item("Anzeige: Sonderposten"))

    def test_feed_fetcher_module_imports(self):
        """Prüft isolierte Importe aus src.feed_fetcher."""
        from src.feed_fetcher import (
            determine_stream_type,
            autodiscover_rss_feeds,
            fetch_feed_raw,
            test_feed_connection,
        )
        self.assertEqual(determine_stream_type("rss20", "", b""), "RSS 2.0")
        self.assertTrue(callable(fetch_feed_raw))
        self.assertTrue(callable(test_feed_connection))

    def test_police_scraper_module_imports(self):
        """Prüft isolierte Importe aus src.police_scraper."""
        from src.police_scraper import extract_police_teaser, _POLICE_TEASER_CACHE
        self.assertEqual(extract_police_teaser(""), "")
        self.assertIsInstance(_POLICE_TEASER_CACHE, dict)

    def test_sources_manager_module_imports(self):
        """Prüft isolierte Importe aus src.sources_manager."""
        from src.sources_manager import (
            get_sources_path,
            load_sources,
            save_sources,
            add_feed,
            delete_feed,
            update_feed,
            add_category,
            delete_category,
            rename_category,
            update_settings,
            sync_sources_to_github,
            trigger_rss_update_workflow,
            purge_jsdelivr_cache,
            get_settings_path,
            get_prompts_path,
            load_settings,
            save_settings,
            load_prompts,
            save_prompts,
            load_sources_raw,
        )
        self.assertTrue(callable(load_sources))
        self.assertTrue(callable(save_sources))
        self.assertTrue(callable(add_feed))
        self.assertTrue(callable(sync_sources_to_github))
        self.assertTrue(callable(load_settings))
        self.assertTrue(callable(save_settings))
        self.assertTrue(callable(load_prompts))
        self.assertTrue(callable(save_prompts))
        self.assertTrue(callable(load_sources_raw))

    def test_aggregator_facade_backward_compatibility(self):
        """Prüft, dass src.aggregator alle alten Symbole via Fassade exportiert."""
        import src.aggregator as agg

        expected_symbols = [
            "fetch_feed_items",
            "collect_all_news",
            "clean_html_text",
            "format_summary_html",
            "unwrap_and_clean_url",
            "get_canonical_url",
            "normalize_keywords",
            "is_ad_item",
            "get_article_timestamp",
            "is_article_too_old",
            "filter_articles_by_age",
            "filter_news_data_by_age",
            "determine_stream_type",
            "autodiscover_rss_feeds",
            "fetch_feed_raw",
            "test_feed_connection",
            "extract_police_teaser",
            "_POLICE_TEASER_CACHE",
            "load_sources",
            "save_sources",
            "load_settings",
            "save_settings",
            "load_prompts",
            "save_prompts",
            "add_feed",
            "delete_feed",
            "update_feed",
            "rename_category",
            "add_category",
            "delete_category",
            "update_settings",
            "get_pool_state_path",
            "load_pool_state",
            "save_pool_state",
            "get_new_articles_count",
            "DEFAULT_AD_PATTERNS",
            "DEFAULT_MAX_ARTICLE_AGE_HOURS",
        ]
        for sym in expected_symbols:
            self.assertTrue(hasattr(agg, sym), f"Symbol '{sym}' fehlt in src.aggregator Fassade!")


if __name__ == "__main__":
    unittest.main()
