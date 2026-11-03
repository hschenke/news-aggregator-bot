"""
Basis-Klasse, Schnittstellen und Konfiguration für das Storage-System des News Aggregator Bots.
Enthält gemeinsame Schemadefinitionen, SQL-Templates und performante Row-Mapper für SQLite & Turso.
"""

from __future__ import annotations

import os
import sys
import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.models import Article, OfflineArticle
from src.exceptions import StorageError, StorageConnectionError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS: float = float(os.getenv("TURSO_TIMEOUT", "30.0"))
DEFAULT_SQLITE_PATH: str = "data/news_bot.db"
OFFLINE_RETENTION_DAYS: int = 90

# ----------------- GEMEINSAME SCHEMADEFINITIONEN -----------------

SCHEMA_TABLES_SQL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS articles (
        url TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        summary TEXT DEFAULT '',
        source TEXT DEFAULT '',
        category TEXT DEFAULT '',
        timestamp REAL DEFAULT 0.0,
        guid TEXT,
        published TEXT,
        source_url TEXT,
        feedback INTEGER DEFAULT 0,
        is_bookmarked INTEGER DEFAULT 0,
        is_read INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS archived_articles (
        url TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        summary TEXT DEFAULT '',
        source TEXT DEFAULT '',
        category TEXT DEFAULT '',
        timestamp REAL DEFAULT 0.0,
        guid TEXT,
        published TEXT,
        source_url TEXT,
        feedback INTEGER DEFAULT 0,
        archived_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS briefings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        briefing_date TEXT NOT NULL,
        content_markdown TEXT NOT NULL,
        model_used TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS offline_articles (
        url TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        feed_name TEXT DEFAULT '',
        feed_url TEXT DEFAULT '',
        category TEXT DEFAULT '',
        published TEXT DEFAULT '',
        timestamp REAL DEFAULT 0.0,
        content_text TEXT DEFAULT '',
        content_html TEXT DEFAULT '',
        images_json TEXT DEFAULT '[]',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS settings_backups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL DEFAULT 0.0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        settings_yaml TEXT NOT NULL,
        label TEXT DEFAULT '',
        filter_ads INTEGER DEFAULT 1,
        keywords_count INTEGER DEFAULT 0,
        patterns_count INTEGER DEFAULT 0
    );
    """,
]

SCHEMA_INDEXES_SQL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_articles_timestamp ON articles(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);",
    "CREATE INDEX IF NOT EXISTS idx_articles_feedback ON articles(feedback);",
    "CREATE INDEX IF NOT EXISTS idx_articles_bookmark ON articles(is_bookmarked);",
    "CREATE INDEX IF NOT EXISTS idx_archived_articles_timestamp ON archived_articles(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_archived_articles_archived_at ON archived_articles(archived_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_offline_articles_feed_name ON offline_articles(feed_name);",
    "CREATE INDEX IF NOT EXISTS idx_offline_articles_timestamp ON offline_articles(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_offline_articles_created_at ON offline_articles(created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_settings_backups_ts ON settings_backups(timestamp DESC);",
]

UPSERT_ARTICLE_SQL = """
    INSERT INTO articles (
        url, title, summary, source, category, timestamp,
        guid, published, source_url, feedback, is_bookmarked, is_read,
        created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(url) DO UPDATE SET
        title = excluded.title,
        summary = excluded.summary,
        source = excluded.source,
        category = excluded.category,
        timestamp = excluded.timestamp,
        guid = COALESCE(excluded.guid, articles.guid),
        published = COALESCE(excluded.published, articles.published),
        source_url = COALESCE(excluded.source_url, articles.source_url),
        updated_at = excluded.updated_at
"""

UPSERT_OFFLINE_ARTICLE_SQL = """
    INSERT INTO offline_articles (
        url, title, feed_name, feed_url, category, published,
        timestamp, content_text, content_html, images_json, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(url) DO UPDATE SET
        title = excluded.title,
        feed_name = excluded.feed_name,
        feed_url = excluded.feed_url,
        category = excluded.category,
        published = excluded.published,
        timestamp = excluded.timestamp,
        content_text = excluded.content_text,
        content_html = excluded.content_html,
        images_json = excluded.images_json,
        created_at = excluded.created_at
"""

INSERT_SETTINGS_BACKUP_SQL = """
    INSERT INTO settings_backups (
        timestamp, created_at, settings_yaml, label, filter_ads, keywords_count, patterns_count
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
"""

# ----------------- HILFSFUNKTIONEN & MAPPER -----------------

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
                        url = st.secrets.get("TURSO_URL") or st.secrets.get("TURSO_DATABASE_URL")
                    if not key:
                        key = st.secrets.get("TURSO_KEY") or st.secrets.get("TURSO_AUTH_TOKEN")
            except Exception:
                pass

    url_str = str(url).strip() if url else None
    key_str = str(key).strip() if key else None
    return url_str, key_str


def row_to_article(r: Any) -> Article:
    """Konvertiert eine Datenbankzeile (sqlite3.Row oder Turso-Dict) effizient in ein Article-Objekt."""
    keys = set(r.keys()) if hasattr(r, "keys") else set(r)
    return Article(
        title=str(r["title"] or "Kein Titel").strip(),
        link=str(r["url"] or "#").strip(),
        summary=str(r["summary"] or ""),
        source=str(r["source"] or ""),
        category=str(r["category"] or ""),
        timestamp=float(r["timestamp"] or 0.0),
        guid=r["guid"] if "guid" in keys and r["guid"] is not None else None,
        published=r["published"] if "published" in keys and r["published"] is not None else None,
        source_url=r["source_url"] if "source_url" in keys and r["source_url"] is not None else None,
        feedback=int(r["feedback"] or 0) if "feedback" in keys else 0,
        archived_at=str(r["archived_at"]) if "archived_at" in keys and r["archived_at"] else None,
        extra={
            "is_bookmarked": bool(r["is_bookmarked"]) if "is_bookmarked" in keys else False,
            "is_read": bool(r["is_read"]) if "is_read" in keys else False,
        },
    )


def row_to_offline_article(r: Any) -> OfflineArticle:
    """Konvertiert eine Datenbankzeile effizient in ein OfflineArticle-Objekt."""
    keys = set(r.keys()) if hasattr(r, "keys") else set(r)
    return OfflineArticle(
        url=str(r["url"] or "#").strip(),
        title=str(r["title"] or "Kein Titel").strip(),
        feed_name=str(r["feed_name"] or "") if "feed_name" in keys else "",
        feed_url=str(r["feed_url"] or "") if "feed_url" in keys else "",
        category=str(r["category"] or "") if "category" in keys else "",
        published=str(r["published"] or "") if "published" in keys else "",
        timestamp=float(r["timestamp"] or 0.0) if "timestamp" in keys else 0.0,
        content_text=str(r["content_text"] or "") if "content_text" in keys else "",
        content_html=str(r["content_html"] or "") if "content_html" in keys else "",
        images_json=str(r["images_json"] or "[]") if "images_json" in keys else "[]",
        created_at=str(r["created_at"] or "") if "created_at" in keys else "",
    )


def row_to_settings_backup(r: Any) -> dict[str, Any]:
    """Konvertiert eine Datenbankzeile in ein Settings-Backup-Dictionary."""
    keys = set(r.keys()) if hasattr(r, "keys") else set(r)
    return {
        "id": int(r["id"]),
        "timestamp": float(r["timestamp"] or 0.0) if "timestamp" in keys else 0.0,
        "created_at": str(r["created_at"] or "") if "created_at" in keys else "",
        "settings_yaml": str(r["settings_yaml"] or "") if "settings_yaml" in keys else "",
        "label": str(r["label"] or "") if "label" in keys else "",
        "filter_ads": bool(r["filter_ads"]) if "filter_ads" in keys else True,
        "keywords_count": int(r["keywords_count"] or 0) if "keywords_count" in keys else 0,
        "patterns_count": int(r["patterns_count"] or 0) if "patterns_count" in keys else 0,
    }


def prepare_article_upsert_params(
    articles: list[Article | dict[str, Any]],
    archived_urls: set[str],
    max_age_seconds: float = 86400.0,
) -> list[tuple[Any, ...]]:
    """Filtert gelesene und veraltete Artikel heraus und bereitet die Parameterliste für den Upsert vor."""
    params_list: list[tuple[Any, ...]] = []
    now_ts = time.time()
    cutoff_ts = now_ts - max_age_seconds
    now_iso = datetime.now(timezone.utc).isoformat()

    for item in articles:
        art = Article.from_dict(item) if not isinstance(item, Article) else item
        url = art.link.strip()
        if not url or url == "#" or url in archived_urls:
            continue
        if art.timestamp > 0.0 and art.timestamp < cutoff_ts:
            continue

        params_list.append((
            url,
            art.title,
            art.summary,
            art.source,
            art.category,
            art.timestamp,
            art.guid,
            art.published,
            art.source_url,
            art.feedback,
            1 if art.get("is_bookmarked") else 0,
            1 if art.get("is_read") else 0,
            now_iso,
            now_iso,
        ))
    return params_list


def prepare_offline_article_params(
    articles: list[OfflineArticle | dict[str, Any]],
) -> list[tuple[Any, ...]]:
    """Bereitet die Parameterliste für OfflineArticle-Upserts vor."""
    params_list: list[tuple[Any, ...]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for item in articles:
        art = OfflineArticle.from_dict(item) if not isinstance(item, OfflineArticle) else item
        url = art.url.strip()
        if not url or url == "#":
            continue
        params_list.append((
            url,
            art.title,
            art.feed_name,
            art.feed_url,
            art.category,
            art.published,
            art.timestamp,
            art.content_text,
            art.content_html,
            art.images_json,
            art.created_at or now_iso,
        ))
    return params_list


def build_articles_query(
    limit: int = 100,
    category: str | None = None,
    feedback: int | None = None,
    is_bookmarked: bool | None = None,
    is_read: bool | None = None,
    search_query: str | None = None,
) -> tuple[str, list[Any]]:
    """Erstellt den parametrisierten SQL-Query und die Parameterliste zum Auslesen aktiver Artikel."""
    clauses: list[str] = []
    params: list[Any] = []

    if category and category != "Alle Kategorien":
        clauses.append("category = ?")
        params.append(category)

    if feedback is not None:
        clauses.append("feedback = ?")
        params.append(feedback)

    if is_bookmarked is not None:
        clauses.append("is_bookmarked = ?")
        params.append(1 if is_bookmarked else 0)

    if is_read is not None:
        clauses.append("is_read = ?")
        params.append(1 if is_read else 0)

    if search_query and search_query.strip():
        clauses.append("(title LIKE ? OR summary LIKE ?)")
        q_like = f"%{search_query.strip()}%"
        params.extend([q_like, q_like])

    where_stmt = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT * FROM articles
        {where_stmt}
        ORDER BY timestamp DESC
        LIMIT ?
    """
    params.append(max(1, limit))
    return sql, params


def build_offline_articles_query(
    feed_name: str | None = None,
    category: str | None = None,
    search_query: str | None = None,
    limit: int = 500,
) -> tuple[str, list[Any]]:
    """Erstellt den parametrisierten SQL-Query zum Auslesen von Offline-Artikeln."""
    clauses: list[str] = []
    params: list[Any] = []

    if feed_name and feed_name != "Alle Feeds":
        clauses.append("feed_name = ?")
        params.append(feed_name)

    if category and category != "Alle Kategorien":
        clauses.append("category = ?")
        params.append(category)

    if search_query and search_query.strip():
        clauses.append("(title LIKE ? OR content_text LIKE ?)")
        q_like = f"%{search_query.strip()}%"
        params.extend([q_like, q_like])

    where_stmt = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT * FROM offline_articles
        {where_stmt}
        ORDER BY timestamp DESC
        LIMIT ?
    """
    params.append(max(1, limit))
    return sql, params


# ----------------- ABSTRAKTE BASISKLASSE -----------------

class StorageBackend(ABC):
    """Abstrakte Basisklasse für persistente Speicher-Backends."""

    @abstractmethod
    def init_db(self) -> None:
        """Initialisiert das Datenbankschema (Tabellen & Indizes)."""
        pass

    @abstractmethod
    def save_articles(self, articles: list[Article | dict[str, Any]]) -> int:
        """Speichert oder aktualisiert Artikel via Upsert."""
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
        """Setzt das Nutzer-Feedback für einen Artikel (1 = Like, -1 = Dislike, 0 = Neutral)."""
        pass

    @abstractmethod
    def set_feedback_bulk(self, feedback_items: list[tuple[str, int, str]]) -> int:
        """Aktualisiert Bewertungen für mehrere Artikel gesammelt (Bulk-Operation)."""
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
        """Verschiebt einen gelesenen Artikel ins Archiv und löscht ihn aus den aktiven Artikeln."""
        pass

    @abstractmethod
    def archive_articles_bulk(self, articles: list[Article | dict[str, Any] | str]) -> int:
        """Verschiebt mehrere Artikel gesammelt ins Archiv in einer Transaktion."""
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
        """Verschiebt Artikel, die älter als max_age_seconds sind, ins Archiv."""
        pass

    @abstractmethod
    def cleanup_archive(self, max_age_days: int | float = 7, max_age_weeks: int | float | None = None) -> int:
        """Bereinigt die Archiv-Tabelle und löscht archivierte Artikel, die älter als max_age_days Tage sind."""
        pass

    @abstractmethod
    def purge_tables(self) -> dict[str, int]:
        """Leert alle Tabellen für einen sauberen Neustart."""
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
    def save_offline_article(self, article: OfflineArticle | dict[str, Any]) -> bool:
        """Speichert einen Artikel inkl. Webseiten-Abbild in offline_articles."""
        pass

    @abstractmethod
    def save_offline_articles(self, articles: list[OfflineArticle | dict[str, Any]]) -> int:
        """Speichert mehrere Offline-Artikel in offline_articles."""
        pass

    @abstractmethod
    def get_offline_articles(
        self,
        feed_name: str | None = None,
        category: str | None = None,
        search_query: str | None = None,
        limit: int = 500,
    ) -> list[OfflineArticle]:
        """Gibt gespeicherte Offline-Artikel sortiert nach timestamp DESC zurück."""
        pass

    @abstractmethod
    def get_offline_article(self, url: str) -> OfflineArticle | None:
        """Gibt einen einzelnen gespeicherten Offline-Artikel anhand seiner URL zurück."""
        pass

    @abstractmethod
    def get_offline_urls(self, feed_name: str | None = None) -> set[str]:
        """Gibt die Menge aller bereits offline gespeicherten Artikel-URLs zurück."""
        pass

    @abstractmethod
    def delete_offline_article(self, url: str) -> bool:
        """Löscht einen einzelnen Offline-Artikel anhand seiner URL."""
        pass

    @abstractmethod
    def delete_offline_articles_by_feed(self, feed_name: str) -> int:
        """Löscht alle gespeicherten Offline-Artikel eines bestimmten Feeds."""
        pass

    @abstractmethod
    def cleanup_offline_articles(self, max_age_days: int | float = OFFLINE_RETENTION_DAYS) -> int:
        """Entfernt automatisch Offline-Artikel, die älter als max_age_days sind."""
        pass

    @abstractmethod
    def save_settings_backup(
        self,
        settings_yaml: str,
        label: str = "Manuelles Backup",
        filter_ads: bool = True,
        keywords_count: int = 0,
        patterns_count: int = 0,
    ) -> int:
        """Speichert einen Snapshot der Einstellungen in settings_backups."""
        pass

    @abstractmethod
    def get_settings_backups(self, limit: int = 50) -> list[dict[str, Any]]:
        """Gibt gespeicherte Settings-Backups sortiert nach timestamp DESC zurück."""
        pass

    @abstractmethod
    def get_settings_backup(self, backup_id: int) -> dict[str, Any] | None:
        """Gibt ein bestimmtes Settings-Backup anhand seiner ID zurück."""
        pass

    @abstractmethod
    def delete_settings_backup(self, backup_id: int) -> bool:
        """Löscht ein bestimmtes Settings-Backup anhand seiner ID."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Schließt alle Verbindungen und gibt Ressourcen frei."""
        pass
