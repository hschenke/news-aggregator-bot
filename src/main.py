import os
import sys
import time
import logging
from pathlib import Path

# Sicherstellen, dass UTF-8 und Line-Buffering im Terminal unterstützt werden
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

# Sicherstellen, dass das Projektverzeichnis im Suchpfad ist
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.aggregator import collect_all_news, save_pool_state
from src.summarizer import summarize_news_with_gemini
from src.notifier import dispatch_digest
from src.rss_generator import export_briefing_rss

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_pipeline() -> None:
    logger.info("News Aggregator Bot: Pipeline gestartet.")
    print("=" * 60, flush=True)
    print("🤖 News Aggregator Bot: Pipeline gestartet...", flush=True)
    print("=" * 60, flush=True)

    # 1. Schritt: News aggregieren (save_to_db=False vermeidet redundantes Doppelspeichern vor Schritt 4)
    print("\n[1/3] 📡 Lese konfigurierte RSS-Feeds ein...", flush=True)
    news = collect_all_news(save_to_db=False)
    total_items = sum(len(items) for items in news.values())
    print(f"      -> {total_items} Artikel über {len(news)} Kategorien geladen.", flush=True)
    print("      -> RSS-Feeds für alle Kategorien & Quellen erfolgreich bereitgestellt.", flush=True)

    if total_items == 0:
        print("[!] Keine Artikel gefunden. Bitte Feeds in config/sources.yaml prüfen.", flush=True)
        Path("output").mkdir(parents=True, exist_ok=True)
        return

    # 2. Schritt: KI-Zusammenfassung generieren
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    print(f"\n[2/3] 🧠 Generiere kuratierte Zusammenfassung mit LLM (bevorzugt: {gemini_model})...", flush=True)
    summary = summarize_news_with_gemini(news, model=gemini_model)
    print("      -> Zusammenfassung erfolgreich generiert.", flush=True)
    try:
        export_briefing_rss(summary, news_data=news)
        print("      -> KI-Briefing RSS-Feed (briefing.xml) erfolgreich bereitgestellt.", flush=True)
    except Exception as e:
        print(f"      [Hinweis] Briefing-RSS konnte nicht exportiert werden: {e}", flush=True)

    # 3. Schritt: Distribution (HTML generieren + E-Mail versenden)
    print("\n[3/3] 📬 Erstelle Digest & versende...", flush=True)
    dispatch_digest(summary)
    save_pool_state(news)

    # 4. Schritt: Datenbank-Persistenz (Turso Cloud DB mit automatischem lokalem SQLite-Fallback)
    try:
        from src.storage import get_storage, SqliteStorage
        storage = get_storage()
        all_articles = [it for items in news.values() for it in items]

        try:
            saved_count = storage.save_articles(all_articles)
            briefing_date = time.strftime("%Y-%m-%d")
            storage.save_briefing(briefing_date, summary, gemini_model)
            print(f"      -> 💾 {saved_count} Artikel & KI-Briefing in Datenbank archiviert.", flush=True)
        except Exception as db_err:
            logger.warning("Speichern in primärer DB fehlgeschlagen (%s). Nutze lokalen SQLite-Fallback...", db_err)
            print(f"      [Warnung] Cloud-DB fehlgeschlagen ({db_err}). Speichere lokal in SQLite-Archiv...", flush=True)
            fallback_storage = SqliteStorage()
            fallback_storage.init_db()
            saved_count = fallback_storage.save_articles(all_articles)
            briefing_date = time.strftime("%Y-%m-%d")
            fallback_storage.save_briefing(briefing_date, summary, gemini_model)
            print(f"      -> 💾 {saved_count} Artikel & KI-Briefing im lokalen SQLite-Archiv gesichert.", flush=True)
            storage = fallback_storage

        # 5. Schritt: Ältere Artikel (> 24h) archivieren und Archiv-Bereinigung (> archive_retention_days)
        from src.aggregator import load_sources, DEFAULT_ARCHIVE_RETENTION_DAYS
        sources_cfg = load_sources()
        settings = sources_cfg.get("settings", {})
        retention_days_raw = settings.get("archive_retention_days", DEFAULT_ARCHIVE_RETENTION_DAYS)
        try:
            retention_days = int(retention_days_raw) if retention_days_raw is not None else DEFAULT_ARCHIVE_RETENTION_DAYS
        except (ValueError, TypeError):
            retention_days = DEFAULT_ARCHIVE_RETENTION_DAYS

        # 5a. Artikel älter als 24 Stunden ins Archiv verschieben
        archived_count = storage.archive_old_articles(max_age_seconds=86400.0)
        if archived_count > 0:
            print(f"      -> 📦 Archivierung: {archived_count} Artikel (> 24h) ins Archiv verschoben.", flush=True)

        # 5b. Archiv-Einträge älter als retention_days (Standard: 7 Tage) löschen
        cleaned_count = storage.cleanup_archive(max_age_days=retention_days)
        if cleaned_count > 0:
            print(f"      -> 🧹 Archiv-Bereinigung: {cleaned_count} alte Artikel (> {retention_days} Tage) gelöscht.", flush=True)
        else:
            print(f"      -> 🧹 Archiv-Bereinigung: Keine veralteten Artikel im Archiv (> {retention_days} Tage).", flush=True)
    except Exception as exc:
        logger.warning("Datenbank-Archivierung oder Archiv-Bereinigung fehlgeschlagen: %s", exc)

    print("\n" + "=" * 60, flush=True)
    print("✨ Pipeline erfolgreich abgeschlossen!", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    run_pipeline()
