"""
Storage- und Datenbankpaket für den News Aggregator Bot.
Bietet ein einheitliches Repository-Interface (StorageBackend) mit zwei Implementierungen:
1. TursoStorage: Cloud-basierte LibSQL-Datenbank via HTTPS v2 Pipeline (Zero heavy dependencies).
2. SqliteStorage: Lokale SQLite-Datenbank (Standardbibliothek) als robuster Offline-/Entwicklungs-Fallback.

Inklusive automatischer Erkennung und unterbrechungsfreiem Failover (Fallback) bei Verbindungsfehlern.
"""

from __future__ import annotations

import logging
from pathlib import Path
import requests  # Erforderlich für Abwärtskompatibilität und Test-Mocking

from src.models import Article
from src.exceptions import StorageError, StorageConnectionError
from src.storage.base import (
    StorageBackend,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_SQLITE_PATH,
    get_safe_db_path,
    get_turso_config,
)
from src.storage.sqlite import SqliteStorage
from src.storage.turso import TursoStorage

logger = logging.getLogger(__name__)

_STORAGE_INSTANCE: StorageBackend | None = None


def reset_storage_singleton() -> None:
    """Setzt die Singleton-Instanz zurück (z. B. für Tests)."""
    global _STORAGE_INSTANCE
    _STORAGE_INSTANCE = None


def get_storage(prefer_turso: bool = True, db_path: str | Path | None = None) -> StorageBackend:
    """
    Factory-Funktion mit automatischem Fallback und Singleton-Wiederverwendung:
    1. Wenn db_path angegeben ist (z. B. in Tests für :memory:), wird stets eine isolierte Instanz erzeugt.
    2. Wenn prefer_turso=True und TURSO_URL + TURSO_KEY vorhanden sind:
       Versucht Verbindung zu Turso. Bei Erfolg wird TursoStorage wiederverwendet.
    3. Automatischer Fallback auf lokales SqliteStorage.
    """
    global _STORAGE_INSTANCE
    if db_path is not None:
        sqlite_storage = SqliteStorage(db_path=db_path)
        sqlite_storage.init_db()
        return sqlite_storage

    if _STORAGE_INSTANCE is not None:
        return _STORAGE_INSTANCE

    turso_url, turso_key = get_turso_config()

    if prefer_turso and turso_url and turso_key:
        try:
            logger.info("Turso-Zugangsdaten erkannt. Versuche Verbindung zu Turso Cloud...")
            turso_storage = TursoStorage(database_url=turso_url, auth_token=turso_key)
            turso_storage.init_db()
            logger.info("Erfolgreich mit Turso Cloud-Datenbank verbunden.")
            _STORAGE_INSTANCE = turso_storage
            return _STORAGE_INSTANCE
        except Exception as exc:
            logger.warning(
                "Turso-Verbindung konnte nicht initialisiert werden (%s). "
                "Automatischer Fallback auf lokale SQLite-Datenbank.",
                exc
            )

    logger.debug("Nutze lokale SQLite-Speicherung.")
    sqlite_storage = SqliteStorage(db_path=db_path)
    sqlite_storage.init_db()
    _STORAGE_INSTANCE = sqlite_storage
    return _STORAGE_INSTANCE


__all__ = [
    "StorageBackend",
    "SqliteStorage",
    "TursoStorage",
    "StorageError",
    "StorageConnectionError",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_SQLITE_PATH",
    "get_safe_db_path",
    "get_turso_config",
    "get_storage",
    "reset_storage_singleton",
    "requests",
]
