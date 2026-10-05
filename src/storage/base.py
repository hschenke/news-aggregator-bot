"""
Basis-Klasse, Schnittstellen und Konfiguration für das Storage-System des News Aggregator Bots.
"""

from __future__ import annotations

import os
import sys
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from src.models import Article
from src.exceptions import StorageError, StorageConnectionError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS: float = float(os.getenv("TURSO_TIMEOUT", "30.0"))
DEFAULT_SQLITE_PATH: str = "data/news_bot.db"


def get_safe_db_path(db_path: str | Path | None = None) -> Path:
    """Ermittelt einen sicheren absoluten Pfad für die lokale SQLite-Datenbank."""
    if db_path is None:
        db_path = DEFAULT_SQLITE_PATH

    path = Path(db_path)
    if not path.is_absolute():
        root_dir = Path(__file__).resolve().parent.parent.parent
        path = (root_dir / path).resolve()
    else:
        path = path.resolve()

    # Sicherstellen, dass das Elternverzeichnis existiert (außer bei In-Memory)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    return path


def get_turso_config() -> tuple[str | None, str | None]:
    """
    Liest TURSO_URL und TURSO_KEY aus Umgebungsvariablen oder Streamlit Secrets.
    Unterstützt auch TURSO_DATABASE_URL und TURSO_AUTH_TOKEN als Aliasse.
    """
    url = os.getenv("TURSO_URL") or os.getenv("TURSO_DATABASE_URL")
    key = os.getenv("TURSO_KEY") or os.getenv("TURSO_AUTH_TOKEN")

    if not url or not key:
        if "STREAMLIT_SERVER_PORT" in os.environ or "streamlit" in sys.modules:
            try:
                import streamlit as st
                if hasattr(st, "secrets"):
                    if not url:
                        if "TURSO_URL" in st.secrets:
                            url = str(st.secrets["TURSO_URL"])
                        elif "TURSO_DATABASE_URL" in st.secrets:
                            url = str(st.secrets["TURSO_DATABASE_URL"])
                        elif hasattr(st.secrets, "get"):
                            url = st.secrets.get("TURSO_URL") or st.secrets.get("TURSO_DATABASE_URL")
                    if not key:
                        if "TURSO_KEY" in st.secrets:
                            key = str(st.secrets["TURSO_KEY"])
                        elif "TURSO_AUTH_TOKEN" in st.secrets:
                            key = str(st.secrets["TURSO_AUTH_TOKEN"])
                        elif hasattr(st.secrets, "get"):
                            key = st.secrets.get("TURSO_KEY") or st.secrets.get("TURSO_AUTH_TOKEN")
            except Exception as e_sec:
                logger.debug("Streamlit Secrets Zugriff nicht möglich: %s", e_sec)

    url_str = str(url).strip() if url else None
    key_str = str(key).strip() if key else None
    return url_str, key_str


class StorageBackend(ABC):
    """Abstrakte Basisklasse für persistente Speicher-Backends."""

    @abstractmethod
    def init_db(self) -> None:
        """Initialisiert das Datenbankschema (Tabellen & Indizes)."""
        pass

    @abstractmethod
    def save_articles(self, articles: list[Article | dict[str, Any]]) -> int:
        """
        Speichert oder aktualisiert Artikel via Upsert.
        Bestehende Nutzer-Interaktionen (Feedback, Lesezeichen, Gelesen) bleiben erhalten.
        """
        pass

    @abstractmethod
    def get_articles(
        self,
        limit: int = 100,
        category: str | None = None,
        feedback: int | None = None,
        is_bookmarked: bool | None = None,
        is_read: bool | None = None,
        search_query: str | None = None,
    ) -> list[Article]:
        """Gibt gespeicherte Artikel sortiert nach timestamp DESC zurück."""
        pass

    @abstractmethod
    def get_article(self, url: str) -> Article | None:
        """Holt einen einzelnen Artikel anhand seiner URL."""
        pass

    @abstractmethod
    def is_url_known(self, url: str) -> bool:
        """Prüft, ob eine URL bereits in der Datenbank existiert."""
        pass

    @abstractmethod
    def get_known_urls(self) -> set[str]:
        """Gibt die Menge aller bekannten Artikel-URLs zurück (für Deduplizierung)."""
        pass

    @abstractmethod
    def set_feedback(self, url: str, feedback: int, title: str = "") -> bool:
        """
        Setzt das Nutzer-Feedback für einen Artikel:
        1 = Like (Daumen hoch), -1 = Dislike (Daumen runter), 0 = Neutral.
        """
        pass

    @abstractmethod
    def set_feedback_bulk(self, feedback_items: list[tuple[str, int, str]]) -> int:
        """
        Aktualisiert Bewertungen für mehrere Artikel gesammelt (Bulk-Operation).
        Nimmt eine Liste von (url, feedback, title) Tuples entgegen.
        Gibt die Anzahl der verarbeiteten Einträge zurück.
        """
        pass

    @abstractmethod
    def get_feedback_map(self) -> dict[str, int]:
        """Gibt ein Mapping {url: feedback} für alle bewerteten Artikel zurück (feedback != 0)."""
        pass

    @abstractmethod
    def set_bookmark(self, url: str, is_bookmarked: bool) -> bool:
        """Setzt oder entfernt ein Lesezeichen für einen Artikel."""
        pass

    @abstractmethod
    def set_read(self, url: str, is_read: bool) -> bool:
        """Markiert einen Artikel als gelesen oder ungelesen."""
        pass

    @abstractmethod
    def save_briefing(self, briefing_date: str, content_markdown: str, model_used: str = "") -> int:
        """Speichert ein generiertes KI-Briefing im Archiv."""
        pass

    @abstractmethod
    def get_latest_briefing(self) -> dict[str, Any] | None:
        """Gibt das neueste archivierte Briefing zurück."""
        pass

    @abstractmethod
    def get_briefings(self, limit: int = 10) -> list[dict[str, Any]]:
        """Gibt die letzten archivierten Briefings zurück."""
        pass

    @abstractmethod
    def archive_article(self, article: Article | dict[str, Any] | str) -> bool:
        """
        Verschiebt einen gelesenen Artikel ins Archiv (archived_articles) und löscht ihn
        aus der aktiven Artikel-Tabelle (articles).
        """
        pass

    @abstractmethod
    def archive_articles_bulk(self, articles: list[Article | dict[str, Any] | str]) -> int:
        """
        Verschiebt mehrere Artikel gesammelt ins Archiv (archived_articles) und löscht
        sie aus der aktiven Artikel-Tabelle (articles) in einer Bulk-Transaktion.
        Gibt die Anzahl der archivierten Artikel zurück.
        """
        pass

    @abstractmethod
    def get_archived_urls(self) -> set[str]:
        """Gibt alle URLs der bisher archivierten Artikel zurück."""
        pass

    @abstractmethod
    def is_article_archived(self, url: str) -> bool:
        """Prüft, ob eine URL bereits im Archiv vorhanden ist."""
        pass

    @abstractmethod
    def get_archived_articles(self, limit: int = 100) -> list[Article]:
        """Gibt archivierte Artikel sortiert nach Datum zurück."""
        pass

    @abstractmethod
    def archive_old_articles(self, max_age_seconds: float = 86400.0) -> int:
        """
        Verschiebt Artikel, die älter als max_age_seconds (Standard 24h) sind, ins Archiv
        und entfernt sie aus der aktiven Artikel-Tabelle.
        """
        pass

    @abstractmethod
    def cleanup_archive(self, max_age_days: int | float = 7, max_age_weeks: int | float | None = None) -> int:
        """
        Bereinigt die Archiv-Tabelle und löscht archivierte Artikel, die älter als max_age_days Tage sind.
        Gibt die Anzahl der gelöschten Datensätze zurück.
        """
        pass

    @abstractmethod
    def purge_tables(self) -> dict[str, int]:
        """
        Leert alle Tabellen (articles, archived_articles, briefings) für einen sauberen Neustart.
        Gibt die Anzahl der gelöschten Zeilen je Tabelle zurück.
        """
        pass

    @abstractmethod
    def get_metadata(self, key: str, default: str | None = None) -> str | None:
        """Liest einen Schlüsselwert aus der Metadaten-Tabelle."""
        pass

    @abstractmethod
    def set_metadata(self, key: str, value: str) -> None:
        """Schreibt oder aktualisiert einen Schlüsselwert in der Metadaten-Tabelle."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Schließt alle Verbindungen und gibt Ressourcen frei."""
        pass
