"""
Zentral definierte Exception-Hierarchie für den News Bot.
Ermöglicht präzise Fehlerbehandlung ohne Exceptions unbemerkt zu verschlucken.
"""


class NewsBotError(Exception):
    """Basisklasse für alle anwendungsbezogenen Fehler im News Bot."""
    pass


# Abwärtskompatibler Alias für bestehende Aufrufer und Tests
NewsAggregatorError = NewsBotError


class ConfigurationError(NewsBotError):
    """Fehler in der Konfiguration (z. B. ungültige YAML-Konfiguration oder fehlende Secrets)."""
    pass


class FeedFetchError(NewsBotError):
    """Fehler beim HTTP-Abruf oder Parsing eines externen RSS-Feeds."""
    pass


class NotificationError(NewsBotError):
    """Fehler bei der Benachrichtigung (SMTP oder Resend API)."""
    pass


class SummarizationError(NewsBotError):
    """Fehler bei der KI-Zusammenfassung via Gemini LLM."""
    pass


class StorageError(NewsBotError):
    """Basisklasse für Speicher- und Datenbankfehler."""
    pass


class StorageConnectionError(StorageError):
    """Fehler beim Verbindungsaufbau zur Datenbank (z. B. Turso Cloud DB)."""
    pass

