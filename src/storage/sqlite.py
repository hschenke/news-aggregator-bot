"""
Lokales SQLite-Backend für den News Bot.
Performant, thread-sicher und schlank unter Verwendung der Standardbibliothek.
"""

from __future__ import annotations

import sqlite3
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.models import Article, OfflineArticle
from src.storage.base import (
    StorageBackend,
    DEFAULT_TIMEOUT_SECONDS,
    OFFLINE_RETENTION_DAYS,
    SCHEMA_TABLES_SQL,
    SCHEMA_INDEXES_SQL,
    UPSERT_ARTICLE_SQL,
    UPSERT_OFFLINE_ARTICLE_SQL,
    INSERT_SETTINGS_BACKUP_SQL,
    get_safe_db_path,
    row_to_article,
    row_to_offline_article,
    row_to_settings_backup,
    prepare_article_upsert_params,
    prepare_offline_article_params,
    build_articles_query,
    build_offline_articles_query,
)

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
        conn = sqlite3.connect(self._db_path, timeout=DEFAULT_TIMEOUT_SECONDS, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
        except Exception:
            pass
        return conn

    def init_db(self) -> None:
        with self._get_connection() as conn:
            for sql in SCHEMA_TABLES_SQL + SCHEMA_INDEXES_SQL:
                conn.execute(sql)

    def save_articles(self, articles: list[Article | dict[str, Any]]) -> int:
        if not articles:
            return 0
        archived_urls = self.get_archived_urls()
        params_list = prepare_article_upsert_params(articles, archived_urls)
        if not params_list:
            return 0
        with self._get_connection() as conn:
            cursor = conn.executemany(UPSERT_ARTICLE_SQL, params_list)
            return cursor.rowcount if cursor.rowcount > 0 else len(params_list)

    def get_articles(
        self,
        limit: int = 100,
        category: str | None = None,
        feedback: int | None = None,
        is_bookmarked: bool | None = None,
        is_read: bool | None = None,
        search_query: str | None = None,
    ) -> list[Article]:
        sql, params = build_articles_query(
            limit=limit,
            category=category,
            feedback=feedback,
            is_bookmarked=is_bookmarked,
            is_read=is_read,
            search_query=search_query,
        )
        with self._get_connection() as conn:
            cursor = conn.execute(sql, params)
            return [row_to_article(r) for r in cursor.fetchall()]

    def get_article(self, url: str) -> Article | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM articles WHERE url = ? LIMIT 1", (url.strip(),))
            row = cursor.fetchone()
            return row_to_article(row) if row else None

    def is_url_known(self, url: str) -> bool:
        clean_url = url.strip()
        if not clean_url:
            return False
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM articles WHERE url = ? UNION SELECT 1 FROM archived_articles WHERE url = ? LIMIT 1",
                (clean_url, clean_url),
            )
            return cursor.fetchone() is not None

    def get_known_urls(self) -> set[str]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT url FROM articles UNION SELECT url FROM archived_articles")
            return {r[0] for r in cursor.fetchall()}

    def set_feedback(self, url: str, feedback: int, title: str = "") -> bool:
        safe_feedback = 1 if feedback > 0 else (-1 if feedback < 0 else 0)
        clean_url = url.strip()
        if not clean_url:
            return False
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE articles SET feedback = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                (safe_feedback, clean_url),
            )
            if cursor.rowcount == 0:
                conn.execute(
                    """
                    INSERT INTO articles (url, title, feedback, created_at, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(url) DO UPDATE SET feedback = excluded.feedback, updated_at = CURRENT_TIMESTAMP
                    """,
                    (clean_url, title or "Kein Titel", safe_feedback),
                )
            return True

    def set_feedback_bulk(self, feedback_items: list[tuple[str, int, str]]) -> int:
        if not feedback_items:
            return 0
        params = [(fb, u.strip()) for u, fb, _ in feedback_items]
        with self._get_connection() as conn:
            cursor = conn.executemany(
                "UPDATE articles SET feedback = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                params,
            )
            return cursor.rowcount if cursor.rowcount > 0 else len(feedback_items)

    def get_feedback_map(self) -> dict[str, int]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT url, feedback FROM articles WHERE feedback != 0")
            return {r[0]: int(r[1]) for r in cursor.fetchall()}

    def set_bookmark(self, url: str, is_bookmarked: bool) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE articles SET is_bookmarked = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                (1 if is_bookmarked else 0, url.strip()),
            )
            return cursor.rowcount > 0

    def set_read(self, url: str, is_read: bool) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE articles SET is_read = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                (1 if is_read else 0, url.strip()),
            )
            return cursor.rowcount > 0

    def save_briefing(self, briefing_date: str, content_markdown: str, model_used: str = "") -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO briefings (briefing_date, content_markdown, model_used) VALUES (?, ?, ?)",
                (briefing_date, content_markdown, model_used),
            )
            return cursor.lastrowid or 1

    def get_latest_briefing(self) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM briefings ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_briefings(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM briefings ORDER BY id DESC LIMIT ?",
                (max(1, limit),),
            )
            return [dict(r) for r in cursor.fetchall()]

    def archive_article(self, article: Article | dict[str, Any] | str) -> bool:
        url = article if isinstance(article, str) else (article.get("link") or article.get("url") or "")
        clean_url = str(url).strip()
        if not clean_url or clean_url == "#":
            return False

        with self._get_connection() as conn:
            if isinstance(article, (Article, dict)):
                art = Article.from_dict(article) if not isinstance(article, Article) else article
                conn.execute(
                    """
                    INSERT OR IGNORE INTO archived_articles (
                        url, title, summary, source, category, timestamp,
                        guid, published, source_url, feedback, archived_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        art.link, art.title, art.summary, art.source, art.category,
                        art.timestamp, art.guid, art.published, art.source_url, art.feedback,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO archived_articles (
                        url, title, summary, source, category, timestamp,
                        guid, published, source_url, feedback, archived_at
                    )
                    SELECT url, title, summary, source, category, timestamp,
                           guid, published, source_url, feedback, CURRENT_TIMESTAMP
                    FROM articles WHERE url = ?
                    """,
                    (clean_url,),
                )
            cursor = conn.execute("DELETE FROM articles WHERE url = ?", (clean_url,))
            return cursor.rowcount > 0

    def archive_articles_bulk(self, articles: list[Article | dict[str, Any] | str]) -> int:
        if not articles:
            return 0

        archived_count = 0
        with self._get_connection() as conn:
            for item in articles:
                if self.archive_article(item):
                    archived_count += 1
        return archived_count

    def get_archived_urls(self) -> set[str]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT url FROM archived_articles")
            return {r[0] for r in cursor.fetchall()}

    def is_article_archived(self, url: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM archived_articles WHERE url = ? LIMIT 1", (url.strip(),))
            return cursor.fetchone() is not None

    def get_archived_articles(self, limit: int = 100) -> list[Article]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM archived_articles ORDER BY timestamp DESC LIMIT ?",
                (max(1, limit),),
            )
            return [row_to_article(r) for r in cursor.fetchall()]

    def archive_old_articles(self, max_age_seconds: float = 86400.0) -> int:
        cutoff = time.time() - max_age_seconds
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO archived_articles (
                    url, title, summary, source, category, timestamp,
                    guid, published, source_url, feedback, archived_at
                )
                SELECT url, title, summary, source, category, timestamp,
                       guid, published, source_url, feedback, CURRENT_TIMESTAMP
                FROM articles
                WHERE timestamp > 0.0 AND timestamp < ?
                """,
                (cutoff,),
            )
            cursor = conn.execute("DELETE FROM articles WHERE timestamp > 0.0 AND timestamp < ?", (cutoff,))
            return cursor.rowcount

    def cleanup_archive(self, max_age_days: int | float = 7, max_age_weeks: int | float | None = None) -> int:
        cutoff_ts = time.time() - (float(max_age_days) * 86400.0)
        cutoff_iso = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM archived_articles WHERE (timestamp > 0.0 AND timestamp < ?) OR (archived_at < ?)",
                (cutoff_ts, cutoff_iso),
            )
            return cursor.rowcount

    def purge_tables(self) -> dict[str, int]:
        res: dict[str, int] = {}
        with self._get_connection() as conn:
            for tbl in ["articles", "archived_articles", "briefings", "offline_articles", "settings_backups"]:
                cursor = conn.execute(f"DELETE FROM {tbl}")
                res[tbl] = cursor.rowcount
        return res

    def get_metadata(self, key: str, default: str | None = None) -> str | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT value FROM metadata WHERE key = ? LIMIT 1", (key,))
            row = cursor.fetchone()
            return row["value"] if row and row["value"] is not None else default

    def set_metadata(self, key: str, value: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO metadata (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )

    def save_offline_article(self, article: OfflineArticle | dict[str, Any]) -> bool:
        params_list = prepare_offline_article_params([article])
        if not params_list:
            return False
        with self._get_connection() as conn:
            conn.execute(UPSERT_OFFLINE_ARTICLE_SQL, params_list[0])
            self.cleanup_offline_articles()
            return True

    def save_offline_articles(self, articles: list[OfflineArticle | dict[str, Any]]) -> int:
        params_list = prepare_offline_article_params(articles)
        if not params_list:
            return 0
        with self._get_connection() as conn:
            cursor = conn.executemany(UPSERT_OFFLINE_ARTICLE_SQL, params_list)
            self.cleanup_offline_articles()
            return cursor.rowcount if cursor.rowcount > 0 else len(params_list)

    def get_offline_articles(
        self,
        feed_name: str | None = None,
        category: str | None = None,
        search_query: str | None = None,
        limit: int = 500,
    ) -> list[OfflineArticle]:
        sql, params = build_offline_articles_query(
            feed_name=feed_name,
            category=category,
            search_query=search_query,
            limit=limit,
        )
        with self._get_connection() as conn:
            cursor = conn.execute(sql, params)
            return [row_to_offline_article(r) for r in cursor.fetchall()]

    def get_offline_article(self, url: str) -> OfflineArticle | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM offline_articles WHERE url = ? LIMIT 1", (url.strip(),))
            row = cursor.fetchone()
            return row_to_offline_article(row) if row else None

    def get_offline_urls(self, feed_name: str | None = None) -> set[str]:
        with self._get_connection() as conn:
            if feed_name:
                cursor = conn.execute("SELECT url FROM offline_articles WHERE feed_name = ?", (feed_name.strip(),))
            else:
                cursor = conn.execute("SELECT url FROM offline_articles")
            return {r[0] for r in cursor.fetchall()}

    def delete_offline_article(self, url: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM offline_articles WHERE url = ?", (url.strip(),))
            return cursor.rowcount > 0

    def delete_offline_articles_by_feed(self, feed_name: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM offline_articles WHERE feed_name = ?", (feed_name.strip(),))
            return cursor.rowcount

    def cleanup_offline_articles(self, max_age_days: int | float = OFFLINE_RETENTION_DAYS) -> int:
        cutoff_ts = time.time() - (float(max_age_days) * 86400.0)
        cutoff_iso = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM offline_articles WHERE (timestamp > 0.0 AND timestamp < ?) OR (created_at < ?)",
                (cutoff_ts, cutoff_iso),
            )
            return cursor.rowcount

    def save_settings_backup(
        self,
        settings_yaml: str,
        label: str = "Manuelles Backup",
        filter_ads: bool = True,
        keywords_count: int = 0,
        patterns_count: int = 0,
    ) -> int:
        now_ts = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT id, settings_yaml FROM settings_backups ORDER BY timestamp DESC, id DESC LIMIT 1"
            ).fetchone()
            if row and (row["settings_yaml"] or "").strip() == (settings_yaml or "").strip():
                return int(row["id"])
            cursor = conn.execute(
                INSERT_SETTINGS_BACKUP_SQL,
                (now_ts, now_iso, settings_yaml, label, 1 if filter_ads else 0, keywords_count, patterns_count),
            )
            return cursor.lastrowid or 1

    def get_settings_backups(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM settings_backups ORDER BY timestamp DESC LIMIT ?",
                (max(1, limit),),
            )
            return [row_to_settings_backup(r) for r in cursor.fetchall()]

    def get_settings_backup(self, backup_id: int) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM settings_backups WHERE id = ? LIMIT 1", (backup_id,))
            row = cursor.fetchone()
            return row_to_settings_backup(row) if row else None

    def delete_settings_backup(self, backup_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM settings_backups WHERE id = ?", (backup_id,))
            return cursor.rowcount > 0

    def close(self) -> None:
        if self._shared_conn is not None:
            try:
                self._shared_conn.close()
            except Exception:
                pass
            self._shared_conn = None
