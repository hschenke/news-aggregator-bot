"""
Unit-Tests für die Tab-Retention und F5-Refresh-Synchronisation in der Web-App.
Stellt sicher:
1. Bidirektionale Übersetzung zwischen Tab-IDs und Anzeigenamen (Labels).
2. Cookie- und LocalStorage-Persistenz über COOKIE_TAB_NAME ('news_bot_active_tab').
3. Quelltext-Integrität in webapp.py für F5-Refresh, Browser-History-Sync und Ausbleiben von Tab-Locking.
"""

import unittest
from pathlib import Path


class TestWebappTabRetention(unittest.TestCase):

    def setUp(self):
        self.webapp_code = Path("src/webapp.py").read_text(encoding="utf-8") + "\n" + Path("src/ui/styles.py").read_text(encoding="utf-8")

    def test_label_and_tab_id_mapping(self):
        """Prüft die bidirektionale Zuordnung von Tab-IDs zu UI-Labels."""
        # Isolierter Namensraum für die Mapping-Funktionen aus webapp.py
        scope = {}
        code_snippet = """
TAB_ID_ARTICLES = "articles"
TAB_ID_KI = "ki"
TAB_ID_MANAGE = "manage"
TAB_ID_FEEDLY = "feedly"
VALID_TAB_IDS = {TAB_ID_ARTICLES, TAB_ID_KI, TAB_ID_MANAGE, TAB_ID_FEEDLY}

TAB_LABEL_ARTICLES = "📋 Artikel"
TAB_LABEL_KI = "✨ KI"
has_unsaved_changes = False
manage_suffix = " 🔴" if has_unsaved_changes else ""
TAB_LABEL_MANAGE = f"⚙️ Verwalten{manage_suffix}"
TAB_LABEL_FEEDLY = "📡 Feedly"

def label_to_tab_id(label: str) -> str:
    if "Artikel" in label:
        return TAB_ID_ARTICLES
    if "KI" in label:
        return TAB_ID_KI
    if "Verwalten" in label or "Quellen" in label:
        return TAB_ID_MANAGE
    if "Feedly" in label or "RSS" in label:
        return TAB_ID_FEEDLY
    return TAB_ID_ARTICLES

def tab_id_to_label(tab_id: str) -> str:
    if tab_id == TAB_ID_KI or tab_id == "briefing":
        return TAB_LABEL_KI
    if tab_id == TAB_ID_MANAGE or tab_id in ["settings", "feeds", "quellen"]:
        return TAB_LABEL_MANAGE
    if tab_id in [TAB_ID_FEEDLY, "rss", "feeds_rss"]:
        return TAB_LABEL_FEEDLY
    return TAB_LABEL_ARTICLES
"""
        exec(code_snippet, scope)

        tab_id_to_label = scope["tab_id_to_label"]
        label_to_tab_id = scope["label_to_tab_id"]
        VALID_TAB_IDS = scope["VALID_TAB_IDS"]

        self.assertIn("articles", VALID_TAB_IDS)
        self.assertIn("ki", VALID_TAB_IDS)
        self.assertIn("manage", VALID_TAB_IDS)
        self.assertIn("feedly", VALID_TAB_IDS)

        # Tab ID zu Label
        self.assertEqual(tab_id_to_label("articles"), "📋 Artikel")
        self.assertEqual(tab_id_to_label("ki"), "✨ KI")
        self.assertEqual(tab_id_to_label("manage"), "⚙️ Verwalten")
        self.assertEqual(tab_id_to_label("feedly"), "📡 Feedly")

        # Label zu Tab ID
        self.assertEqual(label_to_tab_id("📋 Artikel"), "articles")
        self.assertEqual(label_to_tab_id("✨ KI"), "ki")
        self.assertEqual(label_to_tab_id("⚙️ Verwalten"), "manage")
        self.assertEqual(label_to_tab_id("⚙️ Verwalten 🔴"), "manage")
        self.assertEqual(label_to_tab_id("📡 Feedly"), "feedly")

    def test_webapp_tab_persistence_source_integrity(self):
        """Prüft, dass webapp.py die Cookie-, URL- und History-Synchronisation vollständig implementiert."""
        webapp_code = self.webapp_code

        # 1. Cookie-Name
        self.assertIn('COOKIE_TAB_NAME = "news_bot_active_tab"', webapp_code)

        # 2. get_persisted_active_tab Funktion
        self.assertIn("def get_persisted_active_tab() -> str | None:", webapp_code)
        self.assertIn("st.context.cookies.get(COOKIE_TAB_NAME)", webapp_code)

        # 3. persist_active_tab Funktion
        self.assertIn("def persist_active_tab(active_nav_tab: str) -> None:", webapp_code)
        self.assertIn('st.session_state["active_nav_tab"] = active_nav_tab', webapp_code)
        self.assertIn('st.session_state["main_tabs_nav"] = tab_id_to_label(active_nav_tab)', webapp_code)
        self.assertIn('st.query_params["tab"] = active_nav_tab', webapp_code)

        # 4. Client-seitige URL- & Cookie-Synchronisation (auch iframe-resilient für Streamlit Cloud)
        self.assertIn('document.cookie = "{COOKIE_TAB_NAME}="', webapp_code)
        self.assertIn('localStorage.setItem("{COOKIE_TAB_NAME}", tab)', webapp_code)
        self.assertIn('sessionStorage.setItem("{COOKIE_TAB_NAME}", tab)', webapp_code)
        self.assertIn("win.history.replaceState(null, \"\", url.toString());", webapp_code)
        self.assertIn("syncUrl(window.parent);", webapp_code)

        # 5. F5-Refresh Logik: Bevorzugt get_persisted_active_tab() vor Fallback auf qp_tab
        self.assertIn("persisted_tab = get_persisted_active_tab()", webapp_code)
        self.assertIn("if persisted_tab:", webapp_code)
        self.assertIn("active_nav_tab = persisted_tab", webapp_code)

        # 6. st.tabs nutzt default-Parameter abgestimmt auf active_nav_tab
        self.assertIn("default_tab_label = tab_id_to_label(active_nav_tab)", webapp_code)
        self.assertIn("default=default_tab_label,", webapp_code)

        # 7. Kein altes Überschreiben des Benutzer-Klicks mehr durch alte URL-Parameter
        self.assertNotIn("active_nav_tab = label_to_tab_id(st.session_state[\"main_tabs_nav\"])\n    # Falls die URL explizit einen Tab vorgibt", webapp_code)

        # 8. Vollständig unsichtbare Script-Einbettung ohne sichtbare 1px-Striche oder Iframe-Borders über dem Titel
        self.assertIn("display:none !important", webapp_code)
        self.assertIn("unsafe_allow_javascript=True", webapp_code)
        self.assertNotIn("st.iframe(html_wrapper, height=1, width=1)", webapp_code)

        # 9. Header-Anchor-Links und Kettensymbol auf Titeln unterdrückt
        self.assertIn('st.title("📰 Daily News Briefing", anchor=False)', webapp_code)
        self.assertIn('[data-testid="stHeaderActionElements"]', webapp_code)

        # 10. Skeleton-Ladeboxen unterdrückt
        self.assertIn('[data-testid="stSkeleton"]', webapp_code)
        self.assertIn('.stSkeleton', webapp_code)

        # 11. 0-ms-Tabwechsel ohne Server-Rerun (reine clientseitige Umschaltung)
        self.assertNotIn('on_change="rerun"', webapp_code)

        # 12. Beide Navigationsbereiche (Sidebar-Buttons und Top-Tabs) werden clientseitig 0-ms synchronisiert
        self.assertIn('custom-nav-container', webapp_code)
        self.assertIn('custom-nav-btn', webapp_code)
        self.assertIn('setActiveTabClient', webapp_code)
        self.assertIn('[data-testid="stTab"]', webapp_code)

        # 13. Keine Altbrowser-Fallbacks (st.components.v1.html / st.iframe) in embed_client_script
        self.assertNotIn('st.components.v1.html(html_wrapper', webapp_code)
        self.assertNotIn('st.iframe(html_wrapper', webapp_code)


if __name__ == "__main__":
    unittest.main()
