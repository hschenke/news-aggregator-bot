"""
Zentral definierte Exception-Hierarchie für den News Aggregator Bot.
Ermöglicht präzise Fehlerbehandlung ohne Exceptions unbemerkt zu verschlucken.
"""


class NewsAggregatorError(Exception):
    """Basisklasse für alle anwendungsbezogenen Fehler im News Aggregator Bot."""
    pass


class ConfigurationError(NewsAggregatorError):
    """Fehler in der Konfiguration (z. B. ungültige sources.yaml oder fehlende Secrets)."""
    pass


class FeedFetchError(NewsAggregatorError):
    """Fehler beim HTTP-Abruf oder Parsing eines externen RSS-Feeds."""
    pass


class NotificationError(NewsAggregatorError):
    """Fehler bei der Benachrichtigung (SMTP oder Resend API)."""
    pass


class SummarizationError(NewsAggregatorError):
    """Fehler bei der KI-Zusammenfassung via Gemini LLM."""
    pass
