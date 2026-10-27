"""
Strukturierte, unveränderliche Datenmodelle für den News Aggregator Bot.
Bietet Typsicherheit, Validierung und vollständige Mapping-Abwärtskompatibilität.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class Article:
    """
    Unveränderlicher Nachrichtenartikel mit typisierten Feldern.
    Unterstützt sowohl Attributzugriff (article.title) als auch Dictionary-Subscripting (article['title']).
    """
    title: str
    link: str
    summary: str = ""
    source: str = ""
    category: str = ""
    timestamp: float = 0.0
    guid: str | None = None
    published: str | None = None
    published_parsed: Any = None
    source_url: str | None = None
    feedback: int = 0  # -1 = dislike, 0 = neutral, 1 = like
    archived_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Konvertiert die Datenklasse in ein abwärtskompatibles Dictionary."""
        data = asdict(self)
        extra_data = data.pop("extra", {})
        data.update(extra_data)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Article) -> Article:
        """Erstellt eine Article-Instanz aus einem Dictionary oder gibt das Objekt unverändert zurück."""
        if isinstance(data, cls):
            return data

        known_fields = {
            "title", "link", "summary", "source", "category",
            "timestamp", "guid", "published", "published_parsed", "source_url",
            "feedback", "archived_at"
        }
        known_kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}

        for key, value in data.items():
            if key in known_fields:
                known_kwargs[key] = value
            else:
                extra[key] = value

        title = str(known_kwargs.get("title", "")).strip() or "Kein Titel"
        link = str(known_kwargs.get("link", "")).strip() or "#"
        
        raw_ts = known_kwargs.get("timestamp", 0.0)
        try:
            ts_float = float(raw_ts) if raw_ts is not None else 0.0
        except (ValueError, TypeError):
            ts_float = 0.0

        raw_feedback = known_kwargs.get("feedback", 0)
        try:
            feedback_int = int(raw_feedback) if raw_feedback is not None else 0
        except (ValueError, TypeError):
            feedback_int = 0

        archived_at_val = known_kwargs.get("archived_at")
        archived_at_str = str(archived_at_val).strip() if archived_at_val else None

        return cls(
            title=title,
            link=link,
            summary=str(known_kwargs.get("summary") or ""),
            source=str(known_kwargs.get("source") or ""),
            category=str(known_kwargs.get("category") or ""),
            timestamp=ts_float,
            guid=known_kwargs.get("guid"),
            published=known_kwargs.get("published"),
            published_parsed=known_kwargs.get("published_parsed"),
            source_url=known_kwargs.get("source_url"),
            feedback=feedback_int,
            archived_at=archived_at_str,
            extra=extra,
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Ermöglicht dictionary-kompatiblen Zugriff via .get(key, default)."""
        if hasattr(self, key) and key != "extra":
            val = getattr(self, key)
            return default if val is None else val
        return self.extra.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Ermöglicht dictionary-kompatiblen Zugriff via item['key']."""
        if hasattr(self, key) and key != "extra":
            return getattr(self, key)
        if key in self.extra:
            return self.extra[key]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        """Ermöglicht 'key in item' Abfragen."""
        return hasattr(self, key) or key in self.extra


@dataclass(frozen=True)
class OfflineArticle:
    """
    Unveränderlicher, für den Offline-Zugriff archivierter Artikel inklusive
    gespeichertem Webseiten-Text, bereinigtem HTML-Abbild und eingebetteten Bildern (JSON/Base64).
    """
    url: str
    title: str
    feed_name: str = ""
    feed_url: str = ""
    category: str = ""
    published: str = ""
    timestamp: float = 0.0
    content_text: str = ""
    content_html: str = ""
    images_json: str = "[]"
    created_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def images(self) -> list[dict[str, Any]]:
        """Gibt die gespeicherten Bilder als geparste Liste zurück."""
        import json
        if not self.images_json:
            return []
        try:
            parsed = json.loads(self.images_json)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    def to_dict(self) -> dict[str, Any]:
        """Konvertiert die OfflineArticle-Instanz in ein Dictionary."""
        data = asdict(self)
        extra_data = data.pop("extra", {})
        data.update(extra_data)
        data["link"] = self.url
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | OfflineArticle) -> OfflineArticle:
        """Erstellt eine OfflineArticle-Instanz aus einem Dictionary."""
        if isinstance(data, cls):
            return data

        import json
        known_fields = {
            "url", "link", "title", "feed_name", "source", "feed_url", "source_url",
            "category", "published", "timestamp", "content_text", "content_html",
            "images_json", "images", "created_at",
        }
        extra: dict[str, Any] = {}
        for k, v in data.items():
            if k not in known_fields:
                extra[k] = v

        url = str(data.get("url") or data.get("link") or "").strip() or "#"
        title = str(data.get("title") or "").strip() or "Kein Titel"
        feed_name = str(data.get("feed_name") or data.get("source") or "").strip()
        feed_url = str(data.get("feed_url") or data.get("source_url") or "").strip()
        category = str(data.get("category") or "").strip()
        published = str(data.get("published") or "").strip()

        raw_ts = data.get("timestamp", 0.0)
        try:
            ts_float = float(raw_ts) if raw_ts is not None else 0.0
        except (ValueError, TypeError):
            ts_float = 0.0

        content_text = str(data.get("content_text") or data.get("summary") or "")
        content_html = str(data.get("content_html") or "")

        raw_images = data.get("images_json")
        if raw_images is None and "images" in data:
            imgs = data.get("images")
            if isinstance(imgs, list):
                try:
                    raw_images = json.dumps(imgs, ensure_ascii=False)
                except Exception:
                    raw_images = "[]"
        images_json_str = str(raw_images).strip() if raw_images else "[]"

        created_at = str(data.get("created_at") or "").strip()

        return cls(
            url=url,
            title=title,
            feed_name=feed_name,
            feed_url=feed_url,
            category=category,
            published=published,
            timestamp=ts_float,
            content_text=content_text,
            content_html=content_html,
            images_json=images_json_str,
            created_at=created_at,
            extra=extra,
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Ermöglicht dictionary-kompatiblen Zugriff via .get(key, default)."""
        if key == "link":
            return self.url
        if hasattr(self, key) and key != "extra":
            val = getattr(self, key)
            return default if val is None else val
        return self.extra.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Ermöglicht dictionary-kompatiblen Zugriff via item['key']."""
        if key == "link":
            return self.url
        if hasattr(self, key) and key != "extra":
            return getattr(self, key)
        if key in self.extra:
            return self.extra[key]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        """Ermöglicht 'key in item' Abfragen."""
        if key == "link":
            return True
        return hasattr(self, key) or key in self.extra
