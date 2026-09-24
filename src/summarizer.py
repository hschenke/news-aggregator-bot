import os
import sys
from typing import Dict, List, Any
from dotenv import load_dotenv

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

def get_configured_api_key() -> str:
    """Ermittelt den Gemini API-Key aus Umgebungsvariablen oder Streamlit Secrets."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        try:
            import streamlit as st
            if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
                api_key = str(st.secrets["GEMINI_API_KEY"])
        except Exception:
            pass
    return api_key or ""


def summarize_news_with_gemini(
    categorized_news: Dict[str, List[Dict[str, str]]],
    api_key: str = None,
    model: str = None,
    config_path: str = "config/sources.yaml",
) -> str:
    """
    Fasst die gesammelten Nachrichten mit dem Google Gemini Modell zusammen.
    Unterstützt API-Key Übergabe, Umgebungsvariablen sowie Streamlit Secrets.
    Falls kein API-Key hinterlegt ist, wird eine strukturierte Fallback-Übersicht erzeugt.
    """
    # Lese Konfigurations-Einstellungen (z.B. max_articles_per_category)
    try:
        from src.aggregator import load_sources
        config = load_sources(config_path)
        settings = config.get("settings", {})
    except Exception:
        settings = {}

    max_articles = settings.get("max_articles_per_category", 4)
    language = settings.get("language", "de")
    lang_name = "Deutsch" if language == "de" else language

    active_key = api_key or get_configured_api_key()
    if not active_key or active_key.startswith("your_"):
        print("[Hinweis] Kein gültiger GEMINI_API_KEY gefunden. Erzeuge Standard-Zusammenfassung...")
        return _generate_fallback_summary(categorized_news, max_articles=max_articles)

    try:
        from google import genai
        client = genai.Client(api_key=active_key)
        
        # Erstelle Kontext aus den News
        context_lines = []
        for cat, items in categorized_news.items():
            context_lines.append(f"\n### Kategorie: {cat}")
            for item in items:
                context_lines.append(f"- **{item['title']}** (Quelle: {item.get('source', 'Unbekannt')})")
                if item.get("summary"):
                    context_lines.append(f"  Auszug: {item['summary']}")
                context_lines.append(f"  Link: {item['link']}")

        prompt = f"""
Du bist ein professioneller News-Kurator und Redakteur für ein Daily Executive Briefing.
Deine Aufgabe ist es, aus den folgenden Roh-Nachrichten ein übersichtliches, prägnantes und leicht lesbares Tages-Briefing auf {lang_name} zu erstellen.

Formatierungsrichtlinien:
1. Beginne mit einem kurzen 2-3 Sätze langen "Executive Summary" der wichtigsten Trends des Tages.
2. Gruppiere die Themen nach ihren Kategorien.
3. Wähle pro Kategorie bis zu {max_articles} der relevantesten Themen aus und fasse sie in je 2-3 Bullet-Points zusammen (inklusive Kernaussage und Bedeutung).
4. Verlinke jeweils die Originalquelle mit einem sprechenden Link Markdown, z.B. [Mehr lesen](URL).
5. Verwende sauberes Markdown mit gut strukturierten Zwischenüberschriften und Emojis.

Hier sind die aktuellen Roh-Nachrichten:
{"".join(context_lines)}
"""
        preferred_model = model or os.getenv("GEMINI_MODEL")
        default_candidates = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash"]
        candidate_models = [preferred_model] if preferred_model else default_candidates
        # Stelle sicher, dass die Fallback-Kandidaten angehängt werden, falls preferred_model fehlschlägt
        for dm in default_candidates:
            if dm not in candidate_models:
                candidate_models.append(dm)
        candidate_models = [m for m in candidate_models if m]

        last_error = None
        for model_name in candidate_models:
            try:
                print(f"      -> Generiere mit Modell: {model_name}...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response and response.text:
                    return response.text
            except Exception as model_err:
                print(f"      [Warnung] Modell {model_name} temporär nicht erreichbar ({model_err}). Versuche Alternative...")
                last_error = model_err

        print(f"[Fehler] Alle KI-Modelle schlugen fehl: {last_error}")
        return _generate_fallback_summary(categorized_news, max_articles=max_articles)
    except Exception as e:
        print(f"[Fehler] Initialisierungsfehler Gemini API: {e}")
        return _generate_fallback_summary(categorized_news, max_articles=max_articles)


def _generate_fallback_summary(categorized_news: Dict[str, List[Dict[str, str]]], max_articles: int = 4) -> str:
    """Einfacher Markdown-Report ohne LLM (Fallback)."""
    lines = [
        "# 📰 Dein Daily News Briefing",
        "*Hinweis: Dies ist die Vorschau ohne KI-Zusammenfassung (trage deinen GEMINI_API_KEY in die .env ein).* \n"
    ]
    for cat, items in categorized_news.items():
        lines.append(f"\n## {cat}")
        for item in items[:max_articles]:
            lines.append(f"- **[{item['title']}]({item['link']})** ({item.get('source')})")
            if item.get("summary"):
                lines.append(f"  > {item['summary']}")
    return "\n".join(lines)
