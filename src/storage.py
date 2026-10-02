"""
Storage- und Datenbankmodul für den News Aggregator Bot.
Bietet ein einheitliches Repository-Interface (StorageBackend) mit zwei Implementierungen:
1. TursoStorage: Cloud-basierte LibSQL-Datenbank via HTTPS v2 Pipeline (Zero heavy dependencies).
2. SqliteStorage: Lokale SQLite-Datenbank (Standardbibliothek) als robuster Offline-/Entwicklungs-Fallback.

Inklusive automatischer Erkennung und unterbrechungsfreiem Failover (Fallback) bei Verbindungsfehlern.
"""

from __future__ import annotations

import os
import sys
import time
import sqlite3
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

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
        root_dir = Path(__file__).resolve().parent.parent
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
    def cleanup_archive(self, max_age_weeks: int | float = 20) -> int:
        """
        Bereinigt die Archiv-Tabelle und löscht Artikel, die älter als max_age_weeks Wochen sind.
        Gibt die Anzahl der gelöschten Datensätze zurück.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Schließt alle Verbindungen und gibt Ressourcen frei."""
        pass


class SqliteStorage(StorageBackend):
    """
    Lokales SQLite-Backend mit Thread-Sicherheit und Standardbibliothek.
    Dient als primärer Offline-Speicher oder transparenter Cloud-Fallback.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path == ":memory:":
            self._db_path = ":memory:"
            self._shared_conn: sqlite3.Connection | None = sqlite3.connect(
                ":memory:", timeout=DEFAULT_TIMEOUT_SECONDS, check_same_thread=False
            )
            self._shared_conn.row_factory = sqlite3.Row
        else:
            self._db_path = str(get_safe_db_path(db_path))
            self._shared_conn = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        conn = sqlite3.connect(self._db_path, timeout=DEFAULT_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
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

                CREATE TABLE IF NOT EXISTS briefings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    briefing_date TEXT NOT NULL,
                    content_markdown TEXT NOT NULL,
                    model_used TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_articles_timestamp ON articles(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
                CREATE INDEX IF NOT EXISTS idx_articles_feedback ON articles(feedback);
                CREATE INDEX IF NOT EXISTS idx_articles_bookmark ON articles(is_bookmarked);
                CREATE INDEX IF NOT EXISTS idx_archived_articles_timestamp ON archived_articles(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_archived_articles_archived_at ON archived_articles(archived_at DESC);
            """)

    def save_articles(self, articles: list[Article | dict[str, Any]]) -> int:
        if not articles:
            return 0

        saved_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        upsert_sql = """
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

        params_list = []
        archived_urls = self.get_archived_urls()
        for item in articles:
            art = Article.from_dict(item) if not isinstance(item, Article) else item
            url = art.link.strip()
            if not url or url == "#" or url in archived_urls:
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

        if not params_list:
            return 0

        with self._get_connection() as conn:
            cursor = conn.executemany(upsert_sql, params_list)
            saved_count = cursor.rowcount if cursor.rowcount > 0 else len(params_list)

        return saved_count

    def get_articles(
        self,
        limit: int = 100,
        category: str | None = None,
        feedback: int | None = None,
        is_bookmarked: bool | None = None,
        is_read: bool | None = None,
        search_query: str | None = None,
    ) -> list[Article]:
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
        query_sql = f"""
            SELECT * FROM articles
            {where_stmt}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params.append(max(1, limit))

        with self._get_connection() as conn:
            cursor = conn.execute(query_sql, params)
            rows = cursor.fetchall()

        articles: list[Article] = []
        for r in rows:
            articles.append(Article.from_dict({
                "link": r["url"],
                "title": r["title"],
                "summary": r["summary"] or "",
                "source": r["source"] or "",
                "category": r["category"] or "",
                "timestamp": float(r["timestamp"] or 0.0),
                "guid": r["guid"],
                "published": r["published"],
                "source_url": r["source_url"],
                "feedback": int(r["feedback"] or 0),
                "is_bookmarked": bool(r["is_bookmarked"]),
                "is_read": bool(r["is_read"]),
            }))

        return articles

    def get_article(self, url: str) -> Article | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM articles WHERE url = ? LIMIT 1", (url.strip(),))
            row = cursor.fetchone()
            if not row:
                return None
            return Article.from_dict({
                "link": row["url"],
                "title": row["title"],
                "summary": row["summary"] or "",
                "source": row["source"] or "",
                "category": row["category"] or "",
                "timestamp": float(row["timestamp"] or 0.0),
                "guid": row["guid"],
                "published": row["published"],
                "source_url": row["source_url"],
                "feedback": int(row["feedback"] or 0),
                "is_bookmarked": bool(row["is_bookmarked"]),
                "is_read": bool(row["is_read"]),
            })

    def is_url_known(self, url: str) -> bool:
        clean_url = url.strip()
        if not clean_url:
            return False
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM articles WHERE url = ? UNION SELECT 1 FROM archived_articles WHERE url = ? LIMIT 1",
                (clean_url, clean_url)
            )
            return cursor.fetchone() is not None

    def get_known_urls(self) -> set[str]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT url FROM articles UNION SELECT url FROM archived_articles")
            return {row["url"] for row in cursor.fetchall()}

    def archive_article(self, article: Article | dict[str, Any] | str) -> bool:
        """
        Verschiebt einen Artikel ins Archiv (archived_articles) und löscht ihn aus articles.
        """
        if isinstance(article, str):
            clean_url = article.strip()
            if not clean_url:
                return False
            existing = self.get_article(clean_url)
            if existing:
                art = existing
            else:
                art = Article(title="Archivierter Artikel", link=clean_url)
        elif isinstance(article, Article):
            art = article
        elif isinstance(article, dict):
            art = Article.from_dict(article)
        else:
            return False

        clean_url = art.link.strip()
        if not clean_url or clean_url == "#":
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        insert_sql = """
            INSERT INTO archived_articles (
                url, title, summary, source, category, timestamp,
                guid, published, source_url, feedback, archived_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                source = excluded.source,
                category = excluded.category,
                timestamp = excluded.timestamp,
                guid = COALESCE(excluded.guid, archived_articles.guid),
                published = COALESCE(excluded.published, archived_articles.published),
                source_url = COALESCE(excluded.source_url, archived_articles.source_url),
                feedback = excluded.feedback,
                archived_at = excluded.archived_at
        """
        with self._get_connection() as conn:
            conn.execute(insert_sql, (
                clean_url,
                art.title,
                art.summary,
                art.source,
                art.category,
                art.timestamp,
                art.guid,
                art.published,
                art.source_url,
                art.feedback,
                now_iso,
            ))
            conn.execute("DELETE FROM articles WHERE url = ?", (clean_url,))
        return True

    def archive_articles_bulk(self, articles: list[Article | dict[str, Any] | str]) -> int:
        """
        Verschiebt mehrere Artikel gesammelt ins Archiv (archived_articles) und löscht sie aus articles.
        """
        if not articles:
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        insert_rows: list[tuple[Any, ...]] = []
        delete_urls: list[tuple[str]] = []

        for article in articles:
            if isinstance(article, str):
                clean_url = article.strip()
                if not clean_url:
                    continue
                existing = self.get_article(clean_url)
                art = existing if existing else Article(title="Archivierter Artikel", link=clean_url)
            elif isinstance(article, Article):
                art = article
            elif isinstance(article, dict):
                art = Article.from_dict(article)
            else:
                continue

            clean_url = art.link.strip()
            if not clean_url or clean_url == "#":
                continue

            insert_rows.append((
                clean_url,
                art.title,
                art.summary,
                art.source,
                art.category,
                art.timestamp,
                art.guid,
                art.published,
                art.source_url,
                art.feedback,
                now_iso,
            ))
            delete_urls.append((clean_url,))

        if not insert_rows:
            return 0

        insert_sql = """
            INSERT INTO archived_articles (
                url, title, summary, source, category, timestamp,
                guid, published, source_url, feedback, archived_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                source = excluded.source,
                category = excluded.category,
                timestamp = excluded.timestamp,
                guid = COALESCE(excluded.guid, archived_articles.guid),
                published = COALESCE(excluded.published, archived_articles.published),
                source_url = COALESCE(excluded.source_url, archived_articles.source_url),
                feedback = excluded.feedback,
                archived_at = excluded.archived_at
        """
        with self._get_connection() as conn:
            conn.executemany(insert_sql, insert_rows)
            conn.executemany("DELETE FROM articles WHERE url = ?", delete_urls)

        return len(insert_rows)

    def get_archived_urls(self) -> set[str]:
        """Gibt die Menge aller archivierten Artikel-URLs zurück."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT url FROM archived_articles")
            return {row["url"] for row in cursor.fetchall()}

    def is_article_archived(self, url: str) -> bool:
        """Prüft, ob eine URL bereits in archived_articles existiert."""
        clean_url = url.strip()
        if not clean_url:
            return False
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM archived_articles WHERE url = ? LIMIT 1", (clean_url,))
            return cursor.fetchone() is not None

    def get_archived_articles(self, limit: int = 100) -> list[Article]:
        """Gibt die zuletzt archivierten Artikel zurück."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM archived_articles ORDER BY timestamp DESC, archived_at DESC LIMIT ?",
                (max(1, limit),)
            )
            rows = cursor.fetchall()

        articles: list[Article] = []
        for r in rows:
            articles.append(Article.from_dict({
                "link": r["url"],
                "title": r["title"],
                "summary": r["summary"] or "",
                "source": r["source"] or "",
                "category": r["category"] or "",
                "timestamp": float(r["timestamp"] or 0.0),
                "guid": r["guid"],
                "published": r["published"],
                "source_url": r["source_url"],
                "feedback": int(r["feedback"] or 0),
                "archived_at": r["archived_at"],
            }))
        return articles

    def cleanup_archive(self, max_age_weeks: int | float = 20) -> int:
        """
        Löscht archivierte Artikel, die älter als max_age_weeks Wochen sind.
        """
        if max_age_weeks is None or float(max_age_weeks) <= 0:
            return 0
        SECONDS_PER_WEEK = 7.0 * 24 * 3600
        cutoff_ts = time.time() - (float(max_age_weeks) * SECONDS_PER_WEEK)
        cutoff_iso = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat()

        sql = """
            DELETE FROM archived_articles
            WHERE (timestamp > 0.0 AND timestamp < ?)
               OR ((timestamp IS NULL OR timestamp <= 0.0) AND archived_at < ?)
        """
        with self._get_connection() as conn:
            cursor = conn.execute(sql, (cutoff_ts, cutoff_iso))
            return cursor.rowcount if cursor.rowcount >= 0 else 0

    def set_feedback(self, url: str, feedback: int, title: str = "") -> bool:
        safe_feedback = 1 if feedback > 0 else (-1 if feedback < 0 else 0)
        clean_url = url.strip()
        if not clean_url:
            return False
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE articles SET feedback = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                (safe_feedback, clean_url)
            )
            if cursor.rowcount == 0:
                conn.execute(
                    """
                    INSERT INTO articles (url, title, feedback, created_at, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(url) DO UPDATE SET feedback = excluded.feedback, updated_at = CURRENT_TIMESTAMP
                    """,
                    (clean_url, title.strip() or "Unbekannt", safe_feedback)
                )
            return True

    def set_feedback_bulk(self, feedback_items: list[tuple[str, int, str]]) -> int:
        """
        Aktualisiert Feedback für mehrere Artikel gesammelt in einer Transaktion.
        """
        if not feedback_items:
            return 0
        insert_rows = []
        for item in feedback_items:
            url, fb = item[0], item[1]
            title = item[2] if len(item) > 2 else ""
            clean_url = url.strip()
            if not clean_url:
                continue
            safe_fb = 1 if fb > 0 else (-1 if fb < 0 else 0)
            insert_rows.append((clean_url, (title or "Unbekannt").strip(), safe_fb))

        if not insert_rows:
            return 0

        sql = """
            INSERT INTO articles (url, title, feedback, created_at, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(url) DO UPDATE SET feedback = excluded.feedback, updated_at = CURRENT_TIMESTAMP
        """
        with self._get_connection() as conn:
            conn.executemany(sql, insert_rows)
        return len(insert_rows)

    def get_feedback_map(self) -> dict[str, int]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT url, feedback FROM articles WHERE feedback != 0")
            return {row["url"]: int(row["feedback"]) for row in cursor.fetchall()}

    def set_bookmark(self, url: str, is_bookmarked: bool) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE articles SET is_bookmarked = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                (1 if is_bookmarked else 0, url.strip())
            )
            return cursor.rowcount > 0

    def set_read(self, url: str, is_read: bool) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE articles SET is_read = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                (1 if is_read else 0, url.strip())
            )
            return cursor.rowcount > 0

    def save_briefing(self, briefing_date: str, content_markdown: str, model_used: str = "") -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO briefings (briefing_date, content_markdown, model_used, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (briefing_date.strip(), content_markdown.strip(), model_used.strip(), now_iso)
            )
            return cursor.lastrowid or 0

    def get_latest_briefing(self) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM briefings ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    def get_briefings(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM briefings ORDER BY id DESC LIMIT ?", (max(1, limit),))
            return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        if self._shared_conn is not None:
            try:
                self._shared_conn.close()
            except Exception:
                pass
            self._shared_conn = None


class TursoStorage(StorageBackend):
    """
    Turso / LibSQL Cloud-Backend über die standardisierte HTTPS Hrana v2 Pipeline.
    Benötigt keine C-Extensions oder Build-Tools, funktioniert überall (Python 3.10-3.14+,
    Streamlit Cloud, GitHub Actions, Docker).
    """

    def __init__(self, database_url: str, auth_token: str) -> None:
        self._auth_token = auth_token.strip()
        self._pipeline_url = self._normalize_pipeline_url(database_url)
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._auth_token}",
            "Content-Type": "application/json",
            "User-Agent": "NewsAggregatorBot/1.0",
        })

    @staticmethod
    def _normalize_pipeline_url(raw_url: str) -> str:
        """Wandelt libsql:// oder https:// URLs in die Turso /v2/pipeline-Adresse um."""
        clean = raw_url.strip()
        if clean.startswith("libsql://"):
            clean = "https://" + clean[len("libsql://"):]
        elif not clean.startswith("http://") and not clean.startswith("https://"):
            clean = "https://" + clean

        parsed = urlparse(clean)
        scheme = parsed.scheme if parsed.scheme in ["http", "https"] else "https"
        netloc = parsed.netloc

        return f"{scheme}://{netloc}/v2/pipeline"

    @staticmethod
    def _to_turso_arg(val: Any) -> dict[str, Any]:
        """Konvertiert einen Python-Wert in das Turso Hrana v2 Parameter-Objekt."""
        if val is None:
            return {"type": "null"}
        if isinstance(val, bool):
            return {"type": "integer", "value": "1" if val else "0"}
        if isinstance(val, int):
            return {"type": "integer", "value": str(val)}
        if isinstance(val, float):
            return {"type": "float", "value": val}
        return {"type": "text", "value": str(val)}

    @staticmethod
    def _from_turso_cell(cell: dict[str, Any]) -> Any:
        """Konvertiert eine Turso Hrana v2 Zelle in einen nativen Python-Typ."""
        c_type = cell.get("type")
        c_val = cell.get("value")
        if c_type == "null" or c_val is None:
            return None
        if c_type == "integer":
            return int(c_val)
        if c_type == "float":
            return float(c_val)
        if c_type == "text":
            return str(c_val)
        return c_val

    def _execute_pipeline(self, statements: list[tuple[str, list[Any]]]) -> list[dict[str, Any]]:
        """
        Führt ein oder mehrere Statements in einer atomaren Turso Pipeline-Transaktion aus.
        Gibt die geparsten Resultate pro Statement zurück.
        """
        requests_payload: list[dict[str, Any]] = []
        for sql, params in statements:
            turso_args = [self._to_turso_arg(p) for p in params]
            requests_payload.append({
                "type": "execute",
                "stmt": {
                    "sql": sql,
                    "args": turso_args,
                }
            })

        requests_payload.append({"type": "close"})

        max_retries = 2
        response = None
        for attempt in range(max_retries + 1):
            try:
                response = self._session.post(
                    self._pipeline_url,
                    json={"requests": requests_payload},
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                )
                if (response.status_code == 429 or response.status_code >= 500) and attempt < max_retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                break
            except requests.RequestException as exc:
                if attempt < max_retries:
                    logger.warning(
                        "Turso HTTP-Verbindungsfehler (Versuch %d/%d): %s. Wiederhole in %.1fs...",
                        attempt + 1, max_retries + 1, exc, (attempt + 1) * 1.5
                    )
                    time.sleep((attempt + 1) * 1.5)
                else:
                    raise StorageConnectionError(f"HTTP-Verbindungsfehler zu Turso: {exc}") from exc

        if response.status_code != 200:
            raise StorageConnectionError(
                f"Turso API Fehler {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        results_out: list[dict[str, Any]] = []

        for item in data.get("results", []):
            if item.get("type") == "error":
                err_msg = item.get("error", {}).get("message", "Unbekannter Turso-Fehler")
                raise StorageError(f"Turso SQL Fehler: {err_msg}")

            if item.get("type") == "ok":
                resp_obj = item.get("response", {})
                if resp_obj.get("type") == "execute":
                    result = resp_obj.get("result", {})
                    cols = [c["name"] for c in result.get("cols", [])]
                    rows_data = []
                    for row in result.get("rows", []):
                        row_dict = {
                            cols[i]: self._from_turso_cell(cell)
                            for i, cell in enumerate(row)
                        }
                        rows_data.append(row_dict)

                    results_out.append({
                        "rows": rows_data,
                        "affected_rows": result.get("affected_row_count", 0),
                        "last_insert_rowid": result.get("last_insert_rowid"),
                    })

        return results_out

    def init_db(self) -> None:
        stmts = [
            ("""
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
            """, []),
            ("""
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
            """, []),
            ("""
            CREATE TABLE IF NOT EXISTS briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                briefing_date TEXT NOT NULL,
                content_markdown TEXT NOT NULL,
                model_used TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """, []),
            ("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """, []),
            ("CREATE INDEX IF NOT EXISTS idx_articles_timestamp ON articles(timestamp DESC);", []),
            ("CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);", []),
            ("CREATE INDEX IF NOT EXISTS idx_articles_feedback ON articles(feedback);", []),
            ("CREATE INDEX IF NOT EXISTS idx_articles_bookmark ON articles(is_bookmarked);", []),
            ("CREATE INDEX IF NOT EXISTS idx_archived_articles_timestamp ON archived_articles(timestamp DESC);", []),
            ("CREATE INDEX IF NOT EXISTS idx_archived_articles_archived_at ON archived_articles(archived_at DESC);", []),
        ]
        self._execute_pipeline(stmts)

    def save_articles(self, articles: list[Article | dict[str, Any]]) -> int:
        if not articles:
            return 0

        now_iso = datetime.now(timezone.utc).isoformat()
        upsert_sql = """
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

        stmts: list[tuple[str, list[Any]]] = []
        archived_urls = self.get_archived_urls()
        for item in articles:
            art = Article.from_dict(item) if not isinstance(item, Article) else item
            url = art.link.strip()
            if not url or url == "#" or url in archived_urls:
                continue

            stmts.append((upsert_sql, [
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
            ]))

        if not stmts:
            return 0

        # In Batches à maximal 50 Statements aufteilen für optimale Netzwerklaufzeiten
        BATCH_SIZE = 50
        saved_count = 0
        for i in range(0, len(stmts), BATCH_SIZE):
            batch = stmts[i:i + BATCH_SIZE]
            res = self._execute_pipeline(batch)
            for r in res:
                saved_count += max(1, r.get("affected_rows", 1))

        return saved_count

    def get_articles(
        self,
        limit: int = 100,
        category: str | None = None,
        feedback: int | None = None,
        is_bookmarked: bool | None = None,
        is_read: bool | None = None,
        search_query: str | None = None,
    ) -> list[Article]:
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

        res = self._execute_pipeline([(sql, params)])
        if not res:
            return []

        articles: list[Article] = []
        for r in res[0].get("rows", []):
            articles.append(Article.from_dict({
                "link": r["url"],
                "title": r["title"],
                "summary": r["summary"] or "",
                "source": r["source"] or "",
                "category": r["category"] or "",
                "timestamp": float(r["timestamp"] or 0.0),
                "guid": r["guid"],
                "published": r["published"],
                "source_url": r["source_url"],
                "feedback": int(r["feedback"] or 0),
                "is_bookmarked": bool(r["is_bookmarked"]),
                "is_read": bool(r["is_read"]),
            }))

        return articles

    def get_article(self, url: str) -> Article | None:
        res = self._execute_pipeline([
            ("SELECT * FROM articles WHERE url = ? LIMIT 1", [url.strip()])
        ])
        if not res or not res[0].get("rows"):
            return None

        row = res[0]["rows"][0]
        return Article.from_dict({
            "link": row["url"],
            "title": row["title"],
            "summary": row["summary"] or "",
            "source": row["source"] or "",
            "category": row["category"] or "",
            "timestamp": float(row["timestamp"] or 0.0),
            "guid": row["guid"],
            "published": row["published"],
            "source_url": row["source_url"],
            "feedback": int(row["feedback"] or 0),
            "is_bookmarked": bool(row["is_bookmarked"]),
            "is_read": bool(row["is_read"]),
        })

    def is_url_known(self, url: str) -> bool:
        clean = url.strip()
        if not clean:
            return False
        res = self._execute_pipeline([
            (
                "SELECT 1 FROM articles WHERE url = ? UNION SELECT 1 FROM archived_articles WHERE url = ? LIMIT 1",
                [clean, clean]
            )
        ])
        if not res or not res[0].get("rows"):
            return False
        return len(res[0]["rows"]) > 0

    def get_known_urls(self) -> set[str]:
        res = self._execute_pipeline([
            ("SELECT url FROM articles UNION SELECT url FROM archived_articles", [])
        ])
        if not res or not res[0].get("rows"):
            return set()
        return {r["url"] for r in res[0]["rows"] if "url" in r}

    def archive_article(self, article: Article | dict[str, Any] | str) -> bool:
        """
        Verschiebt einen Artikel ins Archiv (archived_articles) und löscht ihn aus articles.
        """
        if isinstance(article, str):
            clean_url = article.strip()
            if not clean_url:
                return False
            existing = self.get_article(clean_url)
            if existing:
                art = existing
            else:
                art = Article(title="Archivierter Artikel", link=clean_url)
        elif isinstance(article, Article):
            art = article
        elif isinstance(article, dict):
            art = Article.from_dict(article)
        else:
            return False

        clean_url = art.link.strip()
        if not clean_url or clean_url == "#":
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        upsert_sql = """
            INSERT INTO archived_articles (
                url, title, summary, source, category, timestamp,
                guid, published, source_url, feedback, archived_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                source = excluded.source,
                category = excluded.category,
                timestamp = excluded.timestamp,
                guid = COALESCE(excluded.guid, archived_articles.guid),
                published = COALESCE(excluded.published, archived_articles.published),
                source_url = COALESCE(excluded.source_url, archived_articles.source_url),
                feedback = excluded.feedback,
                archived_at = excluded.archived_at
        """
        stmts = [
            (upsert_sql, [
                clean_url,
                art.title,
                art.summary,
                art.source,
                art.category,
                art.timestamp,
                art.guid,
                art.published,
                art.source_url,
                art.feedback,
                now_iso,
            ]),
            ("DELETE FROM articles WHERE url = ?", [clean_url]),
        ]
        self._execute_pipeline(stmts)
        return True

    def archive_articles_bulk(self, articles: list[Article | dict[str, Any] | str]) -> int:
        """
        Verschiebt mehrere Artikel gesammelt ins Archiv (archived_articles) und löscht sie aus articles via Turso HTTP-Pipeline.
        """
        if not articles:
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        stmts: list[tuple[str, list[Any]]] = []
        upsert_sql = """
            INSERT INTO archived_articles (
                url, title, summary, source, category, timestamp,
                guid, published, source_url, feedback, archived_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                source = excluded.source,
                category = excluded.category,
                timestamp = excluded.timestamp,
                guid = COALESCE(excluded.guid, archived_articles.guid),
                published = COALESCE(excluded.published, archived_articles.published),
                source_url = COALESCE(excluded.source_url, archived_articles.source_url),
                feedback = excluded.feedback,
                archived_at = excluded.archived_at
        """
        for article in articles:
            if isinstance(article, str):
                clean_url = article.strip()
                if not clean_url:
                    continue
                existing = self.get_article(clean_url)
                art = existing if existing else Article(title="Archivierter Artikel", link=clean_url)
            elif isinstance(article, Article):
                art = article
            elif isinstance(article, dict):
                art = Article.from_dict(article)
            else:
                continue

            clean_url = art.link.strip()
            if not clean_url or clean_url == "#":
                continue

            stmts.append((upsert_sql, [
                clean_url,
                art.title,
                art.summary,
                art.source,
                art.category,
                art.timestamp,
                art.guid,
                art.published,
                art.source_url,
                art.feedback,
                now_iso,
            ]))
            stmts.append(("DELETE FROM articles WHERE url = ?", [clean_url]))

        if not stmts:
            return 0

        BATCH_SIZE = 50
        for i in range(0, len(stmts), BATCH_SIZE):
            self._execute_pipeline(stmts[i:i + BATCH_SIZE])

        return len(stmts) // 2

    def get_archived_urls(self) -> set[str]:
        """Gibt die Menge aller archivierten Artikel-URLs zurück."""
        res = self._execute_pipeline([("SELECT url FROM archived_articles", [])])
        if not res or not res[0].get("rows"):
            return set()
        return {r["url"] for r in res[0]["rows"] if "url" in r}

    def is_article_archived(self, url: str) -> bool:
        """Prüft, ob eine URL bereits in archived_articles existiert."""
        clean = url.strip()
        if not clean:
            return False
        res = self._execute_pipeline([
            ("SELECT 1 FROM archived_articles WHERE url = ? LIMIT 1", [clean])
        ])
        if not res or not res[0].get("rows"):
            return False
        return len(res[0]["rows"]) > 0

    def get_archived_articles(self, limit: int = 100) -> list[Article]:
        """Gibt die zuletzt archivierten Artikel zurück."""
        res = self._execute_pipeline([
            ("SELECT * FROM archived_articles ORDER BY timestamp DESC, archived_at DESC LIMIT ?", [max(1, limit)])
        ])
        if not res or not res[0].get("rows"):
            return []

        articles: list[Article] = []
        for r in res[0].get("rows", []):
            articles.append(Article.from_dict({
                "link": r["url"],
                "title": r["title"],
                "summary": r["summary"] or "",
                "source": r["source"] or "",
                "category": r["category"] or "",
                "timestamp": float(r["timestamp"] or 0.0),
                "guid": r["guid"],
                "published": r["published"],
                "source_url": r["source_url"],
                "feedback": int(r["feedback"] or 0),
                "archived_at": r.get("archived_at"),
            }))
        return articles

    def cleanup_archive(self, max_age_weeks: int | float = 20) -> int:
        """
        Löscht archivierte Artikel, die älter als max_age_weeks Wochen sind.
        """
        if max_age_weeks is None or float(max_age_weeks) <= 0:
            return 0
        SECONDS_PER_WEEK = 7.0 * 24 * 3600
        cutoff_ts = time.time() - (float(max_age_weeks) * SECONDS_PER_WEEK)
        cutoff_iso = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat()

        sql = """
            DELETE FROM archived_articles
            WHERE (timestamp > 0.0 AND timestamp < ?)
               OR ((timestamp IS NULL OR timestamp <= 0.0) AND archived_at < ?)
        """
        res = self._execute_pipeline([(sql, [cutoff_ts, cutoff_iso])])
        if not res:
            return 0
        return int(res[0].get("affected_rows", 0))

    def set_feedback(self, url: str, feedback: int, title: str = "") -> bool:
        safe_val = 1 if feedback > 0 else (-1 if feedback < 0 else 0)
        clean_url = url.strip()
        if not clean_url:
            return False
        res = self._execute_pipeline([
            ("UPDATE articles SET feedback = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?", [safe_val, clean_url])
        ])
        if not res or res[0].get("affected_rows", 0) == 0:
            self._execute_pipeline([
                ("""
                INSERT INTO articles (url, title, feedback, created_at, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(url) DO UPDATE SET feedback = excluded.feedback, updated_at = CURRENT_TIMESTAMP
                """, [clean_url, title.strip() or "Unbekannt", safe_val])
            ])
        return True

    def set_feedback_bulk(self, feedback_items: list[tuple[str, int, str]]) -> int:
        """
        Aktualisiert Feedback für mehrere Artikel gesammelt via Turso HTTP-Pipeline.
        """
        if not feedback_items:
            return 0
        stmts: list[tuple[str, list[Any]]] = []
        sql = """
            INSERT INTO articles (url, title, feedback, created_at, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(url) DO UPDATE SET feedback = excluded.feedback, updated_at = CURRENT_TIMESTAMP
        """
        for item in feedback_items:
            url, fb = item[0], item[1]
            title = item[2] if len(item) > 2 else ""
            clean_url = url.strip()
            if not clean_url:
                continue
            safe_fb = 1 if fb > 0 else (-1 if fb < 0 else 0)
            stmts.append((sql, [clean_url, (title or "Unbekannt").strip(), safe_fb]))

        if not stmts:
            return 0

        BATCH_SIZE = 50
        for i in range(0, len(stmts), BATCH_SIZE):
            self._execute_pipeline(stmts[i:i + BATCH_SIZE])

        return len(stmts)

    def get_feedback_map(self) -> dict[str, int]:
        res = self._execute_pipeline([("SELECT url, feedback FROM articles WHERE feedback != 0", [])])
        if not res or not res[0].get("rows"):
            return {}
        return {
            r["url"]: int(r["feedback"])
            for r in res[0]["rows"]
            if "url" in r and r.get("feedback") is not None
        }

    def set_bookmark(self, url: str, is_bookmarked: bool) -> bool:
        res = self._execute_pipeline([
            ("UPDATE articles SET is_bookmarked = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?", [1 if is_bookmarked else 0, url.strip()])
        ])
        if res and res[0].get("affected_rows", 0) > 0:
            return True
        return False

    def set_read(self, url: str, is_read: bool) -> bool:
        res = self._execute_pipeline([
            ("UPDATE articles SET is_read = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?", [1 if is_read else 0, url.strip()])
        ])
        if res and res[0].get("affected_rows", 0) > 0:
            return True
        return False

    def save_briefing(self, briefing_date: str, content_markdown: str, model_used: str = "") -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        res = self._execute_pipeline([
            ("""
            INSERT INTO briefings (briefing_date, content_markdown, model_used, created_at)
            VALUES (?, ?, ?, ?)
            """, [briefing_date.strip(), content_markdown.strip(), model_used.strip(), now_iso])
        ])
        if res and res[0].get("last_insert_rowid"):
            return int(res[0]["last_insert_rowid"])
        return 1

    def get_latest_briefing(self) -> dict[str, Any] | None:
        res = self._execute_pipeline([
            ("SELECT * FROM briefings ORDER BY id DESC LIMIT 1", [])
        ])
        if not res or not res[0].get("rows"):
            return None
        return res[0]["rows"][0]

    def get_briefings(self, limit: int = 10) -> list[dict[str, Any]]:
        res = self._execute_pipeline([
            ("SELECT * FROM briefings ORDER BY id DESC LIMIT ?", [max(1, limit)])
        ])
        if not res or not res[0].get("rows"):
            return []
        return res[0]["rows"]

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass


def get_storage(prefer_turso: bool = True, db_path: str | Path | None = None) -> StorageBackend:
    """
    Factory-Funktion mit automatischem Fallback:
    1. Wenn prefer_turso=True und TURSO_URL + TURSO_KEY vorhanden sind:
       Versucht Verbindung zu Turso. Bei Erfolg wird TursoStorage zurückgegeben.
    2. Wenn keine Credentials da sind oder Turso nicht erreichbar ist:
       Automatischer, transparenter Fallback auf lokales SqliteStorage.
    """
    turso_url, turso_key = get_turso_config()

    if prefer_turso and turso_url and turso_key:
        try:
            logger.info("Turso-Zugangsdaten erkannt. Versuche Verbindung zu Turso Cloud...")
            turso_storage = TursoStorage(database_url=turso_url, auth_token=turso_key)
            turso_storage.init_db()
            logger.info("Erfolgreich mit Turso Cloud-Datenbank verbunden.")
            return turso_storage
        except Exception as exc:
            logger.warning(
                "Turso-Verbindung konnte nicht initialisiert werden (%s). "
                "Automatischer Fallback auf lokale SQLite-Datenbank.",
                exc
            )

    logger.debug("Nutze lokale SQLite-Speicherung.")
    sqlite_storage = SqliteStorage(db_path=db_path)
    sqlite_storage.init_db()
    return sqlite_storage
