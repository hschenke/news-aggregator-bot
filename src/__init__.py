"""
News Bot Package
"""

from src.models import Article
from src.__version__ import __version__, get_app_version
from src.exceptions import (
    NewsBotError,
    NewsAggregatorError,
    ConfigurationError,
    FeedFetchError,
    NotificationError,
    SummarizationError,
    StorageError,
    StorageConnectionError,
)
from src.storage import (
    StorageBackend,
    SqliteStorage,
    TursoStorage,
    get_storage,
)

__all__ = [
    "Article",
    "__version__",
    "get_app_version",
    "NewsBotError",
    "NewsAggregatorError",
    "ConfigurationError",
    "FeedFetchError",
    "NotificationError",
    "SummarizationError",
    "StorageError",
    "StorageConnectionError",
    "StorageBackend",
    "SqliteStorage",
    "TursoStorage",
    "get_storage",
]
