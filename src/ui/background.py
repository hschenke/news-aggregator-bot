"""
Background tasks module for direct non-blocking persistence.
Replaces the old buffer mechanism with instant, concurrent database operations in background daemon threads.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from src.models import Article
from src.storage import get_storage

logger = logging.getLogger(__name__)


def run_in_background(task_fn: Any, *args: Any, **kwargs: Any) -> threading.Thread:
    """Spawns a detached daemon thread to execute a persistent storage task non-blockingly."""
    def _worker() -> None:
        try:
            task_fn(*args, **kwargs)
        except Exception as exc:
            logger.warning("Background storage task failed: %s", exc)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread


def persist_read_and_archive_async(article: Article | dict[str, Any] | str) -> threading.Thread:
    """Archives an article in the background and removes it from active tables."""
    def _task() -> None:
        storage = get_storage()
        storage.archive_article(article)
        link = article if isinstance(article, str) else article.get("link", "")
        logger.info("Archived read article in background: %s", link)

    return run_in_background(_task)


def persist_feedback_async(url: str, feedback: int, title: str = "") -> threading.Thread:
    """Persists user feedback (like/dislike) directly in the background."""
    def _task() -> None:
        storage = get_storage()
        storage.set_feedback(url, feedback, title)
        logger.info("Persisted user feedback (%d) in background for %s", feedback, url)

    return run_in_background(_task)


def persist_bookmark_async(url: str, is_bookmarked: bool) -> threading.Thread:
    """Persists bookmark status directly in the background."""
    def _task() -> None:
        storage = get_storage()
        storage.set_bookmark(url, is_bookmarked)
        logger.info("Persisted bookmark state (%s) in background for %s", is_bookmarked, url)

    return run_in_background(_task)

