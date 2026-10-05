"""
Lokales SQLite-Backend für den News Aggregator Bot.
"""

from __future__ import annotations

import sqlite3
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.models import Article
from src.storage.base import StorageBackend, DEFAULT_TIMEOUT_SECONDS, get_safe_db_path

logger = logging.getLogger(__name__)


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
        now_ts = time.time()
        cutoff_24h = now_ts - 86400.0
        for item in articles:
            art = Article.from_dict(item) if not isinstance(item, Article) else item
            url = art.link.strip()
            if not url or url == "#" or url in archived_urls:
                continue

            # Fest 24h-Grenze: Veraltete Artikel (> 24 Stunden) nicht aufnehmen
            if art.timestamp > 0.0 and art.timestamp < cutoff_24h:
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

    def archive_old_articles(self, max_age_seconds: float = 86400.0) -> int:
        """
        Verschiebt Artikel, die älter als max_age_seconds (Standard 24h) sind, ins Archiv
        und entfernt sie aus der aktiven Artikel-Tabelle.
        """
        if max_age_seconds <= 0:
            return 0
        cutoff_ts = time.time() - float(max_age_seconds)
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT url, title, summary, source, category, timestamp, guid, published, source_url, feedback "
                "FROM articles WHERE timestamp > 0.0 AND timestamp < ?",
                (cutoff_ts,)
            ).fetchall()
            if not rows:
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
            for r in rows:
                conn.execute(insert_sql, (
                    r["url"], r["title"], r["summary"], r["source"], r["category"],
                    r["timestamp"], r["guid"], r["published"], r["source_url"],
                    r["feedback"], now_iso
                ))
            conn.execute("DELETE FROM articles WHERE timestamp > 0.0 AND timestamp < ?", (cutoff_ts,))
            return len(rows)

    def cleanup_archive(self, max_age_days: int | float = 7, max_age_weeks: int | float | None = None) -> int:
        """
        Löscht archivierte Artikel, die älter als max_age_days Tage sind (Standard: 7 Tage).
        Unterstützt max_age_weeks zur Abwärtskompatibilität.
        """
        if max_age_weeks is not None and max_age_weeks > 0:
            days = float(max_age_weeks) * 7.0
        else:
            days = float(max_age_days)

        if days <= 0:
            return 0

        cutoff_ts = time.time() - (days * 86400.0)
        cutoff_iso = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat()

        sql = """
            DELETE FROM archived_articles
            WHERE (timestamp > 0.0 AND timestamp < ?)
               OR ((timestamp IS NULL OR timestamp <= 0.0) AND archived_at < ?)
        """
        with self._get_connection() as conn:
            cursor = conn.execute(sql, (cutoff_ts, cutoff_iso))
            return cursor.rowcount if cursor.rowcount >= 0 else 0

    def purge_tables(self) -> dict[str, int]:
        """
        Leert alle Tabellen (articles, archived_articles, briefings) für einen sauberen Neustart.
        """
        with self._get_connection() as conn:
            c1 = conn.execute("DELETE FROM articles;").rowcount
            c2 = conn.execute("DELETE FROM archived_articles;").rowcount
            c3 = conn.execute("DELETE FROM briefings;").rowcount
            conn.commit()
        return {
            "articles": max(0, c1),
            "archived_articles": max(0, c2),
            "briefings": max(0, c3),
        }

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

    def get_metadata(self, key: str, default: str | None = None) -> str | None:
        try:
            with self._get_connection() as conn:
                cur = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,))
                row = cur.fetchone()
                return str(row["value"]) if row and row["value"] is not None else default
        except Exception as exc:
            logger.warning("Fehler beim Lesen von SQLite-Metadata '%s': %s", key, exc)
            return default

    def set_metadata(self, key: str, value: str) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO metadata (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (key, str(value)),
                )
        except Exception as exc:
            logger.warning("Fehler beim Schreiben von SQLite-Metadata '%s': %s", key, exc)

    def close(self) -> None:
        if self._shared_conn is not None:
            try:
                self._shared_conn.close()
            except Exception:
                pass
            self._shared_conn = None
