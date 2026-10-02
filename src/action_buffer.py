"""
Aktions-Puffer und Batching-System für den News Aggregator Bot.
Sammelt als gelesen markierte Artikel und Nutzer-Feedback (Likes/Dislikes)
zwischen und führt in konfigurierbaren Intervallen (z. B. alle 5 oder 10 Minuten)
oder auf manuellen Abruf gesammelte Bulk-Datenbankoperationen durch.

Besonderheiten:
- Thread-sicher über atomare Puffer-Entnahme (Double-Buffering / Atomic Drain).
- Ermöglicht kontinuierliches Sammeln weiterer Interaktionen, während ein Bulk-Schreibvorgang
  in die Datenbank (SQLite / Turso) im Hintergrund läuft.
- Rückgängig-Funktion (Unqueue) für versehentlich als gelesen markierte Artikel.
- Automatischer Hintergrund-Timer mit konfigurierbarem Intervall.
"""

from __future__ import annotations

import builtins
import logging
import threading
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import Article
    from src.storage import StorageBackend

logger = logging.getLogger(__name__)

DEFAULT_BUFFER_INTERVAL_MINUTES: int = 5
DEFAULT_BUFFER_INTERVAL_SECONDS: int = DEFAULT_BUFFER_INTERVAL_MINUTES * 60
ACTION_BUFFER_VERSION: int = 2


class ActionBuffer:
    """
    Thread-sicherer Puffer für Lese- und Feedback-Aktionen mit periodischem Bulk-Flush.
    """

    def __init__(self, interval_seconds: int = DEFAULT_BUFFER_INTERVAL_SECONDS) -> None:
        self.version: int = ACTION_BUFFER_VERSION
        self._lock = threading.Lock()
        self._pending_reads: dict[str, dict[str, Any]] = {}
        self._pending_feedback: dict[str, dict[str, Any]] = {}
        self._interval_seconds: int = max(30, interval_seconds)
        self._last_flush_time: float = time.time()
        self._is_flushing: bool = False

        self._timer_thread: threading.Thread | None = None
        self._stop_timer_event = threading.Event()

    def queue_read(self, article: dict[str, Any] | Article) -> None:
        """
        Reiht einen Artikel zur Archivierung (Gelesen-Markierung) in den Puffer ein.
        """
        art_dict = article.to_dict() if hasattr(article, "to_dict") else dict(article)
        url = (art_dict.get("link") or "").strip()
        if not url or url == "#":
            return
        with self._lock:
            self._pending_reads[url] = art_dict
        logger.debug("Artikel in Lesepuffer aufgenommen: %s", url)

    def unqueue_read(self, url: str) -> bool:
        """
        Entfernt einen Artikel wieder aus dem Lesepuffer (Rückgängig-Funktion).
        Gibt True zurück, falls der Artikel im Puffer vorhanden war.
        """
        clean_url = url.strip()
        with self._lock:
            removed = self._pending_reads.pop(clean_url, None)
        if removed is not None:
            logger.debug("Artikel aus Lesepuffer entfernt (Undo): %s", clean_url)
            return True
        return False

    def is_read_queued(self, url: str) -> bool:
        """Prüft, ob eine Artikel-URL aktuell im Lesepuffer vorgemerkt ist."""
        clean_url = url.strip()
        with self._lock:
            return clean_url in self._pending_reads

    def get_queued_read_urls(self) -> set[str]:
        """Gibt eine Kopie aller aktuell im Lesepuffer befindlichen URLs zurück."""
        with self._lock:
            return set(self._pending_reads.keys())

    def queue_feedback(
        self,
        url: str,
        feedback: int,
        title: str = "",
        persisted_feedback: int | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Reiht ein Like/Dislike/Neutral-Feedback in den Puffer ein.
        Aktualisiert ggf. auch das Feedback in einem bereits im Lesepuffer liegenden Artikel.
        Falls das Feedback wieder dem in der DB gespeicherten Zustand entspricht (z. B. neutral 0),
        wird der Eintrag atomar aus dem Puffer entfernt.
        """
        clean_url = url.strip()
        if not clean_url:
            return
        safe_fb = 1 if feedback > 0 else (-1 if feedback < 0 else 0)
        with self._lock:
            # Wenn der Zustand wieder identisch mit dem Datenbank-Bestand ist, wird keine DB-Aktion benötigt:
            if persisted_feedback is not None and safe_fb == persisted_feedback:
                self._pending_feedback.pop(clean_url, None)
                if clean_url in self._pending_reads:
                    self._pending_reads[clean_url]["feedback"] = safe_fb
                logger.debug("Feedback für %s entspricht DB-Stand (%d) -> aus Puffer entfernt", clean_url, safe_fb)
                return

            self._pending_feedback[clean_url] = {
                "feedback": safe_fb,
                "title": title.strip() or "Unbekannt",
            }
            if clean_url in self._pending_reads:
                self._pending_reads[clean_url]["feedback"] = safe_fb
        logger.debug("Feedback für %s in Puffer aufgenommen: %d", clean_url, safe_fb)

    def unqueue_feedback(self, url: str) -> bool:
        """
        Entfernt eine Feedback-Aktion wieder aus dem Puffer (z. B. wenn der Nutzer
        die Bewertung auf den ursprünglichen Zustand zurücksetzt).
        Gibt True zurück, falls ein Eintrag im Puffer vorhanden war.
        """
        clean_url = url.strip()
        with self._lock:
            removed = self._pending_feedback.pop(clean_url, None)
            if clean_url in self._pending_reads:
                self._pending_reads[clean_url]["feedback"] = 0
        if removed is not None:
            logger.debug("Feedback für %s aus Puffer entfernt: %s", clean_url, removed)
            return True
        return False

    def get_pending_counts(self) -> tuple[int, int]:
        """Gibt ein Tupel (anzahl_reads, anzahl_feedback) zurück."""
        with self._lock:
            return len(self._pending_reads), len(self._pending_feedback)

    def is_flushing(self) -> bool:
        """Gibt an, ob aktuell ein Flush-Vorgang aktiv ist."""
        with self._lock:
            return self._is_flushing

    def get_interval_minutes(self) -> int:
        """Gibt das aktuelle Flush-Intervall in Minuten zurück."""
        with self._lock:
            return max(1, self._interval_seconds // 60)

    def set_interval_minutes(self, minutes: int) -> None:
        """Setzt das Flush-Intervall in Minuten."""
        val = max(1, int(minutes))
        with self._lock:
            self._interval_seconds = val * 60
        logger.info("Aktions-Puffer Intervall gesetzt auf %d Minuten.", val)

    def get_seconds_until_next_flush(self) -> int:
        """Gibt die geschätzte Anzahl von Sekunden bis zum nächsten automatischen Flush zurück."""
        with self._lock:
            elapsed = time.time() - self._last_flush_time
            remaining = int(self._interval_seconds - elapsed)
            return max(0, remaining)

    def clear(self) -> None:
        """Leert den gesamten Puffer (z. B. für Tests oder Abbruch)."""
        with self._lock:
            self._pending_reads.clear()
            self._pending_feedback.clear()

    def flush(self, storage: StorageBackend | None = None) -> tuple[int, int]:
        """
        Entnimmt atomar alle aktuell gesammelten Aktionen aus dem Puffer
        und schreibt sie gesammelt in die Datenbank (Bulk-Operation).
        Währenddessen eintreffende neue Aktionen verbleiben im Puffer und
        werden nicht blockiert.

        Gibt ein Tupel (archivierte_artikel, aktualisierte_feedbacks) zurück.
        """
        with self._lock:
            if not self._pending_reads and not self._pending_feedback:
                self._last_flush_time = time.time()
                return 0, 0

            # Atomare Entnahme der aktuellen Batches
            reads_batch = dict(self._pending_reads)
            feedback_batch = dict(self._pending_feedback)
            self._pending_reads.clear()
            self._pending_feedback.clear()
            self._is_flushing = True

        # Ab hier ist der Lock freigegeben! Während der I/O-Operation können
        # weitere Aktionen völlig ungehindert in den Puffer geschrieben werden.
        archived_count = 0
        feedback_count = 0
        try:
            if storage is None:
                from src.storage import get_storage
                storage = get_storage()

            # 1. Bulk Feedback persistieren
            if feedback_batch:
                fb_tuples = [
                    (u, d["feedback"], d["title"])
                    for u, d in feedback_batch.items()
                ]
                feedback_count = storage.set_feedback_bulk(fb_tuples)
                logger.info("Bulk-Feedback synchronisiert: %d Einträge", feedback_count)

            # 2. Bulk Archivierung (Gelesene Artikel)
            if reads_batch:
                archived_count = storage.archive_articles_bulk(list(reads_batch.values()))
                logger.info("Bulk-Archivierung synchronisiert: %d Artikel", archived_count)

        except Exception as exc:
            logger.exception("Fehler beim Bulk-Flush des Aktions-Puffers: %s", exc)
            # Re-Merge bei Fehler: Nur Elemente zurückstellen, die nicht zwischenzeitlich neu belegt wurden
            with self._lock:
                for u, art in reads_batch.items():
                    if u not in self._pending_reads:
                        self._pending_reads[u] = art
                for u, fb in feedback_batch.items():
                    if u not in self._pending_feedback:
                        self._pending_feedback[u] = fb
        finally:
            with self._lock:
                self._is_flushing = False
                self._last_flush_time = time.time()

        return archived_count, feedback_count

    def flush_async(self, storage: StorageBackend | None = None) -> threading.Thread:
        """Führt den Flush in einem separaten Hintergrund-Thread aus."""
        thread = threading.Thread(
            target=self.flush,
            args=(storage,),
            daemon=True,
            name="ActionBufferAsyncFlush"
        )
        thread.start()
        return thread

    def start_periodic_timer(self, interval_seconds: int | None = None) -> None:
        """
        Startet den Hintergrund-Timer für die periodische Synchronisierung,
        sofern dieser noch nicht aktiv ist.
        """
        if interval_seconds is not None:
            self._interval_seconds = max(30, interval_seconds)

        if self._timer_thread is not None and self._timer_thread.is_alive():
            return

        self._stop_timer_event.clear()

        def _timer_worker() -> None:
            logger.info("Aktions-Puffer periodischer Timer gestartet (Intervall: %ds).", self._interval_seconds)
            while not self._stop_timer_event.is_set():
                # Kurze Sleeps, damit der Thread schnell auf Stopp-Signale reagiert
                for _ in range(10):
                    if self._stop_timer_event.is_set():
                        return
                    time.sleep(self._interval_seconds / 10.0)

                # Prüfen, ob Aktionen zum Flashen anstehen
                r_cnt, fb_cnt = self.get_pending_counts()
                if r_cnt > 0 or fb_cnt > 0:
                    try:
                        self.flush()
                    except Exception as err:
                        logger.warning("Automatischer Timer-Flush fehlgeschlagen: %s", err)

        self._timer_thread = threading.Thread(
            target=_timer_worker,
            daemon=True,
            name="ActionBufferPeriodicTimer"
        )
        self._timer_thread.start()

    def stop_periodic_timer(self) -> None:
        """Stoppt den periodischen Hintergrund-Timer."""
        self._stop_timer_event.set()
        if self._timer_thread is not None and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=1.0)
        self._timer_thread = None


_GLOBAL_ACTION_BUFFER: ActionBuffer | None = None
_BUFFER_LOCK = threading.Lock()


def get_action_buffer() -> ActionBuffer:
    """
    Gibt die globale Singleton-Instanz des Aktions-Puffers zurück.
    Initialisiert den Puffer beim ersten Aufruf thread-sicher und
    persistiert die Instanz in builtins über Streamlit-Reruns hinweg.
    Migriert bei Code-Reloads / Hot-Reloads automatisch den Zustand aus Alt-Instanzen.
    """
    global _GLOBAL_ACTION_BUFFER

    def _is_compatible(buf: Any) -> bool:
        return (
            buf is not None
            and type(buf) is ActionBuffer
            and getattr(buf, "version", 0) >= ACTION_BUFFER_VERSION
            and hasattr(buf, "unqueue_feedback")
        )

    existing = getattr(builtins, "_GLOBAL_ACTION_BUFFER", None)
    if _is_compatible(existing):
        _GLOBAL_ACTION_BUFFER = existing
        return existing

    with _BUFFER_LOCK:
        existing = getattr(builtins, "_GLOBAL_ACTION_BUFFER", None)
        if _is_compatible(existing):
            _GLOBAL_ACTION_BUFFER = existing
            return existing

        new_buffer = ActionBuffer()

        # Nahtlose Datenübernahme aus veralteten Instanzen im laufenden Prozess
        if existing is not None:
            try:
                old_reads = dict(getattr(existing, "_pending_reads", {}))
                old_fb = dict(getattr(existing, "_pending_feedback", {}))
                with new_buffer._lock:
                    new_buffer._pending_reads.update(old_reads)
                    new_buffer._pending_feedback.update(old_fb)
                if hasattr(existing, "stop_periodic_timer"):
                    existing.stop_periodic_timer()
                logger.info(
                    "Aktions-Puffer von Alt-Instanz auf Version %d migriert (%d Reads, %d Feedback übernommen).",
                    ACTION_BUFFER_VERSION,
                    len(old_reads),
                    len(old_fb),
                )
            except Exception as mig_err:
                logger.warning("Warnung bei Migration des Aktions-Puffers: %s", mig_err)

        new_buffer.start_periodic_timer()
        builtins._GLOBAL_ACTION_BUFFER = new_buffer
        _GLOBAL_ACTION_BUFFER = new_buffer
        return new_buffer
