"""
Turso / LibSQL Cloud-Backend für den News Bot via HTTPS Hrana v2 Pipeline.
Performant, schlank und ohne native C-Extensions (Python 3.10-3.14+).
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from src.models import Article, OfflineArticle
from src.exceptions import StorageError, StorageConnectionError
from src.storage.base import (
    StorageBackend,
    DEFAULT_TIMEOUT_SECONDS,
    OFFLINE_RETENTION_DAYS,
    SCHEMA_TABLES_SQL,
    SCHEMA_INDEXES_SQL,
    UPSERT_ARTICLE_SQL,
    UPSERT_OFFLINE_ARTICLE_SQL,
    INSERT_SETTINGS_BACKUP_SQL,
    row_to_article,
    row_to_offline_article,
    row_to_settings_backup,
    prepare_article_upsert_params,
    prepare_offline_article_params,
    build_articles_query,
    build_offline_articles_query,
)

logger = logging.getLogger(__name__)


class TursoStorage(StorageBackend):
    """
    Turso / LibSQL Cloud-Backend über die standardisierte HTTPS Hrana v2 Pipeline.
    Nutzt atomare Pipeline-Transaktionen und HTTP-Verbindungspooling.
    """

    def __init__(self, database_url: str, auth_token: str) -> None:
        self._auth_token = auth_token.strip()
        self._pipeline_url = self._normalize_pipeline_url(database_url)
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._auth_token}",
            "Content-Type": "application/json",
            "User-Agent": "NewsBot/1.0",
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
        stmts = [(sql, []) for sql in SCHEMA_TABLES_SQL + SCHEMA_INDEXES_SQL]
        self._execute_pipeline(stmts)

    def save_articles(self, articles: list[Article | dict[str, Any]]) -> int:
        if not articles:
            return 0
        archived_urls = self.get_archived_urls()
        params_list = prepare_article_upsert_params(articles, archived_urls)
        if not params_list:
            return 0

        stmts = [(UPSERT_ARTICLE_SQL, list(p)) for p in params_list]
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
        sql, params = build_articles_query(
            limit=limit,
            category=category,
            feedback=feedback,
            is_bookmarked=is_bookmarked,
            is_read=is_read,
            search_query=search_query,
        )
        res = self._execute_pipeline([(sql, params)])
        if not res or not res[0].get("rows"):
            return []
        return [row_to_article(r) for r in res[0]["rows"]]

    def get_article(self, url: str) -> Article | None:
        res = self._execute_pipeline([
            ("SELECT * FROM articles WHERE url = ? LIMIT 1", [url.strip()])
        ])
        if not res or not res[0].get("rows"):
            return None
        return row_to_article(res[0]["rows"][0])

    def is_url_known(self, url: str) -> bool:
        clean_url = url.strip()
        if not clean_url:
            return False
        res = self._execute_pipeline([
            (
                "SELECT 1 FROM articles WHERE url = ? UNION SELECT 1 FROM archived_articles WHERE url = ? LIMIT 1",
                [clean_url, clean_url],
            )
        ])
        return bool(res and res[0].get("rows"))

    def get_known_urls(self) -> set[str]:
        res = self._execute_pipeline([("SELECT url FROM articles UNION SELECT url FROM archived_articles", [])])
        if not res or not res[0].get("rows"):
            return set()
        return {r["url"] for r in res[0]["rows"]}

    def set_feedback(self, url: str, feedback: int, title: str = "") -> bool:
        safe_feedback = 1 if feedback > 0 else (-1 if feedback < 0 else 0)
        clean_url = url.strip()
        if not clean_url:
            return False
        res = self._execute_pipeline([
            (
                "UPDATE articles SET feedback = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                [safe_feedback, clean_url],
            )
        ])
        if res and res[0].get("affected_rows", 0) == 0:
            self._execute_pipeline([
                (
                    """
                    INSERT INTO articles (url, title, feedback, created_at, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(url) DO UPDATE SET feedback = excluded.feedback, updated_at = CURRENT_TIMESTAMP
                    """,
                    [clean_url, title or "Kein Titel", safe_feedback],
                )
            ])
        return True

    def set_feedback_bulk(self, feedback_items: list[tuple[str, int, str]]) -> int:
        if not feedback_items:
            return 0
        stmts = [
            (
                "UPDATE articles SET feedback = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                [fb, u.strip()],
            )
            for u, fb, _ in feedback_items
        ]
        BATCH_SIZE = 50
        updated_count = 0
        for i in range(0, len(stmts), BATCH_SIZE):
            batch = stmts[i:i + BATCH_SIZE]
            res = self._execute_pipeline(batch)
            for r in res:
                updated_count += r.get("affected_rows", 0)
        return updated_count if updated_count > 0 else len(feedback_items)

    def get_feedback_map(self) -> dict[str, int]:
        res = self._execute_pipeline([
            ("SELECT url, feedback FROM articles WHERE feedback != 0", [])
        ])
        if not res or not res[0].get("rows"):
            return {}
        return {r["url"]: int(r["feedback"]) for r in res[0]["rows"]}

    def set_bookmark(self, url: str, is_bookmarked: bool) -> bool:
        res = self._execute_pipeline([
            (
                "UPDATE articles SET is_bookmarked = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                [1 if is_bookmarked else 0, url.strip()],
            )
        ])
        return bool(res and res[0].get("affected_rows", 0) > 0)

    def set_read(self, url: str, is_read: bool) -> bool:
        res = self._execute_pipeline([
            (
                "UPDATE articles SET is_read = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                [1 if is_read else 0, url.strip()],
            )
        ])
        return bool(res and res[0].get("affected_rows", 0) > 0)

    def save_briefing(self, briefing_date: str, content_markdown: str, model_used: str = "") -> int:
        res = self._execute_pipeline([
            (
                "INSERT INTO briefings (briefing_date, content_markdown, model_used) VALUES (?, ?, ?)",
                [briefing_date, content_markdown, model_used],
            )
        ])
        return res[0].get("last_insert_rowid") or 1 if res else 1

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

    def archive_article(self, article: Article | dict[str, Any] | str) -> bool:
        url = article if isinstance(article, str) else (article.get("link") or article.get("url") or "")
        clean_url = str(url).strip()
        if not clean_url or clean_url == "#":
            return False

        if isinstance(article, (Article, dict)):
            art = Article.from_dict(article) if not isinstance(article, Article) else article
            stmts = [
                (
                    """
                    INSERT OR IGNORE INTO archived_articles (
                        url, title, summary, source, category, timestamp,
                        guid, published, source_url, feedback, archived_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    [
                        art.link, art.title, art.summary, art.source, art.category,
                        art.timestamp, art.guid, art.published, art.source_url, art.feedback,
                    ],
                ),
                ("DELETE FROM articles WHERE url = ?", [clean_url]),
            ]
        else:
            stmts = [
                (
                    """
                    INSERT OR IGNORE INTO archived_articles (
                        url, title, summary, source, category, timestamp,
                        guid, published, source_url, feedback, archived_at
                    )
                    SELECT url, title, summary, source, category, timestamp,
                           guid, published, source_url, feedback, CURRENT_TIMESTAMP
                    FROM articles WHERE url = ?
                    """,
                    [clean_url],
                ),
                ("DELETE FROM articles WHERE url = ?", [clean_url]),
            ]

        res = self._execute_pipeline(stmts)
        return bool(res and res[-1].get("affected_rows", 0) > 0)

    def archive_articles_bulk(self, articles: list[Article | dict[str, Any] | str]) -> int:
        if not articles:
            return 0
        archived_count = 0
        for item in articles:
            if self.archive_article(item):
                archived_count += 1
        return archived_count

    def get_archived_urls(self) -> set[str]:
        res = self._execute_pipeline([("SELECT url FROM archived_articles", [])])
        if not res or not res[0].get("rows"):
            return set()
        return {r["url"] for r in res[0]["rows"]}

    def is_article_archived(self, url: str) -> bool:
        res = self._execute_pipeline([
            ("SELECT 1 FROM archived_articles WHERE url = ? LIMIT 1", [url.strip()])
        ])
        return bool(res and res[0].get("rows"))

    def get_archived_articles(self, limit: int = 100) -> list[Article]:
        res = self._execute_pipeline([
            ("SELECT * FROM archived_articles ORDER BY timestamp DESC LIMIT ?", [max(1, limit)])
        ])
        if not res or not res[0].get("rows"):
            return []
        return [row_to_article(r) for r in res[0]["rows"]]

    def archive_old_articles(self, max_age_seconds: float = 86400.0) -> int:
        cutoff = time.time() - max_age_seconds
        stmts = [
            (
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
                [cutoff],
            ),
            ("DELETE FROM articles WHERE timestamp > 0.0 AND timestamp < ?", [cutoff]),
        ]
        res = self._execute_pipeline(stmts)
        return res[1].get("affected_rows", 0) if len(res) > 1 else 0

    def cleanup_archive(self, max_age_days: int | float = 7, max_age_weeks: int | float | None = None) -> int:
        cutoff_ts = time.time() - (float(max_age_days) * 86400.0)
        cutoff_iso = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        res = self._execute_pipeline([
            (
                "DELETE FROM archived_articles WHERE (timestamp > 0.0 AND timestamp < ?) OR (archived_at < ?)",
                [cutoff_ts, cutoff_iso],
            )
        ])
        return res[0].get("affected_rows", 0) if res else 0

    def purge_tables(self) -> dict[str, int]:
        tables = ["articles", "archived_articles", "briefings", "offline_articles", "settings_backups"]
        stmts = [(f"DELETE FROM {tbl}", []) for tbl in tables]
        res = self._execute_pipeline(stmts)
        return {tables[i]: res[i].get("affected_rows", 0) for i in range(len(tables))}

    def get_metadata(self, key: str, default: str | None = None) -> str | None:
        res = self._execute_pipeline([
            ("SELECT value FROM metadata WHERE key = ? LIMIT 1", [key])
        ])
        if not res or not res[0].get("rows"):
            return default
        val = res[0]["rows"][0].get("value")
        return val if val is not None else default

    def set_metadata(self, key: str, value: str) -> None:
        self._execute_pipeline([
            (
                """
                INSERT INTO metadata (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                [key, value],
            )
        ])

    def save_offline_article(self, article: OfflineArticle | dict[str, Any]) -> bool:
        params_list = prepare_offline_article_params([article])
        if not params_list:
            return False
        self._execute_pipeline([(UPSERT_OFFLINE_ARTICLE_SQL, list(params_list[0]))])
        self.cleanup_offline_articles()
        return True

    def save_offline_articles(self, articles: list[OfflineArticle | dict[str, Any]]) -> int:
        params_list = prepare_offline_article_params(articles)
        if not params_list:
            return 0
        stmts = [(UPSERT_OFFLINE_ARTICLE_SQL, list(p)) for p in params_list]
        BATCH_SIZE = 50
        saved_count = 0
        for i in range(0, len(stmts), BATCH_SIZE):
            batch = stmts[i:i + BATCH_SIZE]
            res = self._execute_pipeline(batch)
            for r in res:
                saved_count += max(1, r.get("affected_rows", 1))
        self.cleanup_offline_articles()
        return saved_count

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
        res = self._execute_pipeline([(sql, params)])
        if not res or not res[0].get("rows"):
            return []
        return [row_to_offline_article(r) for r in res[0]["rows"]]

    def get_offline_article(self, url: str) -> OfflineArticle | None:
        res = self._execute_pipeline([
            ("SELECT * FROM offline_articles WHERE url = ? LIMIT 1", [url.strip()])
        ])
        if not res or not res[0].get("rows"):
            return None
        return row_to_offline_article(res[0]["rows"][0])

    def get_offline_urls(self, feed_name: str | None = None) -> set[str]:
        if feed_name:
            sql = "SELECT url FROM offline_articles WHERE feed_name = ?"
            params = [feed_name.strip()]
        else:
            sql = "SELECT url FROM offline_articles"
            params = []
        res = self._execute_pipeline([(sql, params)])
        if not res or not res[0].get("rows"):
            return set()
        return {r["url"] for r in res[0]["rows"]}

    def delete_offline_article(self, url: str) -> bool:
        res = self._execute_pipeline([
            ("DELETE FROM offline_articles WHERE url = ?", [url.strip()])
        ])
        return bool(res and res[0].get("affected_rows", 0) > 0)

    def delete_offline_articles_by_feed(self, feed_name: str) -> int:
        res = self._execute_pipeline([
            ("DELETE FROM offline_articles WHERE feed_name = ?", [feed_name.strip()])
        ])
        return res[0].get("affected_rows", 0) if res else 0

    def cleanup_offline_articles(self, max_age_days: int | float = OFFLINE_RETENTION_DAYS) -> int:
        cutoff_ts = time.time() - (float(max_age_days) * 86400.0)
        cutoff_iso = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        res = self._execute_pipeline([
            (
                "DELETE FROM offline_articles WHERE (timestamp > 0.0 AND timestamp < ?) OR (created_at < ?)",
                [cutoff_ts, cutoff_iso],
            )
        ])
        return res[0].get("affected_rows", 0) if res else 0

    def save_settings_backup(
        self,
        settings_yaml: str,
        label: str = "Manuelles Backup",
        filter_ads: bool = True,
        keywords_count: int = 0,
        patterns_count: int = 0,
    ) -> int:
        latest = self.get_settings_backups(limit=1)
        if latest and (latest[0].get("settings_yaml") or "").strip() == (settings_yaml or "").strip():
            return int(latest[0]["id"])
        now_ts = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        res = self._execute_pipeline([
            (
                INSERT_SETTINGS_BACKUP_SQL,
                [now_ts, now_iso, settings_yaml, label, 1 if filter_ads else 0, keywords_count, patterns_count],
            )
        ])
        return res[0].get("last_insert_rowid") or 1 if res else 1

    def get_settings_backups(self, limit: int = 50) -> list[dict[str, Any]]:
        res = self._execute_pipeline([
            ("SELECT * FROM settings_backups ORDER BY timestamp DESC LIMIT ?", [max(1, limit)])
        ])
        if not res or not res[0].get("rows"):
            return []
        return [row_to_settings_backup(r) for r in res[0]["rows"]]

    def get_settings_backup(self, backup_id: int) -> dict[str, Any] | None:
        res = self._execute_pipeline([
            ("SELECT * FROM settings_backups WHERE id = ? LIMIT 1", [backup_id])
        ])
        if not res or not res[0].get("rows"):
            return None
        return row_to_settings_backup(res[0]["rows"][0])

    def delete_settings_backup(self, backup_id: int) -> bool:
        res = self._execute_pipeline([
            ("DELETE FROM settings_backups WHERE id = ?", [backup_id])
        ])
        return bool(res and res[0].get("affected_rows", 0) > 0)

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
