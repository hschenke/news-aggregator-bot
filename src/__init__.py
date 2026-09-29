"""
News Aggregator Bot Package
"""

from src.models import Article
from src.__version__ import __version__, get_app_version
from src.exceptions import (
    NewsAggregatorError,
    ConfigurationError,
    FeedFetchError,
    NotificationError,
    SummarizationError,
)

__all__ = [
    "Article",
    "__version__",
    "get_app_version",
    "NewsAggregatorError",
    "ConfigurationError",
    "FeedFetchError",
    "NotificationError",
    "SummarizationError",
]
