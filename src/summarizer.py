import os
from typing import Dict, List, Any
from dotenv import load_dotenv

load_dotenv()

def summarize_news_with_gemini(categorized_news: Dict[str, List[Dict[str, str]]]) -> str:
    """
    Fasst die gesammelten Nachrichten mit dem Google Gemini Modell zusammen.
    Falls kein API-Key hinterlegt ist, wird eine strukturierte Fallback-Übersicht erzeugt.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key.startswith("your_"):
        print("[Hinweis] Kein gültiger GEMINI_API_KEY gefunden. Erzeuge Standard-Zusammenfassung...")
        return _generate_fallback_summary(categorized_news)

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        
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
Deine Aufgabe ist es, aus den folgenden Roh-Nachrichten ein übersichtliches, prägnantes und leicht lesbares Tages-Briefing auf Deutsch zu erstellen.

Formatierungsrichtlinien:
1. Beginne mit einem kurzen 2-3 Sätze langen "Executive Summary" der wichtigsten Trends des Tages.
2. Gruppiere die Themen nach ihren Kategorien.
3. Wähle pro Kategorie die 2-4 relevantesten Themen aus und fasse sie in je 2-3 Bullet-Points zusammen (inklusive Kernaussage und Bedeutung).
4. Verlinke jeweils die Originalquelle mit einem sprechenden Link Markdown, z.B. [Mehr lesen](URL).
5. Verwende sauberes Markdown mit gut strukturierten Zwischenüberschriften und Emojis.

Hier sind die aktuellen Roh-Nachrichten:
{"".join(context_lines)}
"""
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"[Fehler] Fehler beim Gemini API Aufruf: {e}")
        return _generate_fallback_summary(categorized_news)


def _generate_fallback_summary(categorized_news: Dict[str, List[Dict[str, str]]]) -> str:
    """Einfacher Markdown-Report ohne LLM (Fallback)."""
    lines = [
        "# 📰 Dein Daily News Briefing",
        "*Hinweis: Dies ist die Vorschau ohne KI-Zusammenfassung (trage deinen GEMINI_API_KEY in die .env ein).* \n"
    ]
    for cat, items in categorized_news.items():
        lines.append(f"\n## {cat}")
        for item in items[:4]:
            lines.append(f"- **[{item['title']}]({item['link']})** ({item.get('source')})")
            if item.get("summary"):
                lines.append(f"  > {item['summary']}")
    return "\n".join(lines)
