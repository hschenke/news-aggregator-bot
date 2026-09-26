import sys
import time
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


def run_pipeline():
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

    # 3. Schritt: Distribution (HTML generieren + E-Mail versenden)
    print("\n[3/3] 📬 Erstelle Digest & versende...")
    dispatch_digest(summary)
    save_pool_state(news)

    print("\n" + "=" * 60)
    print("✨ Pipeline erfolgreich abgeschlossen!")
    print("=" * 60)


if __name__ == "__main__":
    run_pipeline()
