import os
import sys
import time
import logging
from pathlib import Path

# Sicherstellen, dass UTF-8 im Windows-Terminal unterstützt wird
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Sicherstellen, dass das Projektverzeichnis im Suchpfad ist
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.aggregator import collect_all_news, save_pool_state
from src.summarizer import summarize_news_with_gemini
from src.notifier import dispatch_digest
from src.rss_generator import export_briefing_rss

logger = logging.getLogger(__name__)


def run_pipeline() -> None:
    logger.info("News Aggregator Bot: Pipeline gestartet.")
    print("=" * 60)
    print("🤖 News Aggregator Bot: Pipeline gestartet...")
    print("=" * 60)

    # 1. Schritt: News aggregieren
    print("\n[1/3] 📡 Lese konfigurierte RSS-Feeds ein...")
    news = collect_all_news()
    total_items = sum(len(items) for items in news.values())
    print(f"      -> {total_items} Artikel über {len(news)} Kategorien geladen.")
    print("      -> RSS-Feeds für alle Kategorien & Quellen erfolgreich bereitgestellt.")

    if total_items == 0:
        print("[!] Keine Artikel gefunden. Bitte Feeds in config/sources.yaml prüfen.")
        Path("output").mkdir(parents=True, exist_ok=True)
        return

    # 2. Schritt: KI-Zusammenfassung generieren
    print("\n[2/3] 🧠 Generiere kuratierte Zusammenfassung mit LLM...")
    summary = summarize_news_with_gemini(news)
    print("      -> Zusammenfassung erfolgreich generiert.")
    try:
        export_briefing_rss(summary)
        print("      -> KI-Briefing RSS-Feed (briefing.xml) erfolgreich bereitgestellt.")
    except Exception as e:
        print(f"      [Hinweis] Briefing-RSS konnte nicht exportiert werden: {e}")

    # 3. Schritt: Distribution (HTML generieren + E-Mail versenden)
    print("\n[3/3] 📬 Erstelle Digest & versende...")
    dispatch_digest(summary)
    save_pool_state(news)

    # 4. Schritt: Datenbank-Persistenz (Turso Cloud DB oder lokaler SQLite-Fallback)
    try:
        from src.storage import get_storage
        storage = get_storage()
        all_articles = [it for items in news.values() for it in items]
        saved_count = storage.save_articles(all_articles)
        briefing_date = time.strftime("%Y-%m-%d")
        gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        storage.save_briefing(briefing_date, summary, gemini_model)
        print(f"      -> 💾 {saved_count} Artikel & KI-Briefing in Datenbank archiviert.")

        # 5. Schritt: Archiv-Bereinigung (Morgendlicher Cleanup beim KI Briefing Schedule)
        from src.aggregator import load_sources, DEFAULT_MAX_ARTICLE_AGE_WEEKS
        sources_cfg = load_sources()
        settings = sources_cfg.get("settings", {})
        max_age_weeks_raw = settings.get("max_article_age_weeks")
        if max_age_weeks_raw is None:
            max_age_weeks_raw = settings.get("max_age_weeks", DEFAULT_MAX_ARTICLE_AGE_WEEKS)
        try:
            max_age_weeks = int(max_age_weeks_raw) if max_age_weeks_raw is not None else DEFAULT_MAX_ARTICLE_AGE_WEEKS
        except (ValueError, TypeError):
            max_age_weeks = DEFAULT_MAX_ARTICLE_AGE_WEEKS

        cleaned_count = storage.cleanup_archive(max_age_weeks=max_age_weeks)
        if cleaned_count > 0:
            print(f"      -> 🧹 Archiv-Bereinigung: {cleaned_count} veraltete Artikel (> {max_age_weeks} Wochen) bereinigt.")
        else:
            print(f"      -> 🧹 Archiv-Bereinigung: Keine veralteten Artikel im Archiv (> {max_age_weeks} Wochen).")
    except Exception as exc:
        logger.warning("Datenbank-Archivierung oder Archiv-Bereinigung fehlgeschlagen: %s", exc)

    print("\n" + "=" * 60)
    print("✨ Pipeline erfolgreich abgeschlossen!")
    print("=" * 60)


if __name__ == "__main__":
    run_pipeline()
