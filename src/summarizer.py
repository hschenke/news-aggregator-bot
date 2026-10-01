import os
import sys
import re
import urllib.parse
import logging
from typing import Any
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

AVAILABLE_GEMINI_MODELS: list[str] = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
]
DEFAULT_GEMINI_MODEL: str = AVAILABLE_GEMINI_MODELS[0]


def get_candidate_models(preferred_model: str | None = None) -> list[str]:
    """
    Ermittelt die geordnete Liste an KI-Modellkandidaten inklusive Fallback-Kette.
    Das bevorzugte Modell steht an erster Stelle, gefolgt von den weiteren verfügbaren
    Modellen in absteigender Reihenfolge (vom neuesten 3.8 bis zum ältesten 3.5).
    """
    selected = preferred_model or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
    candidates: list[str] = [selected]
    for model_name in AVAILABLE_GEMINI_MODELS:
        if model_name not in candidates:
            candidates.append(model_name)
    return [m for m in candidates if m]


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


def get_streamlit_app_url(config_path: str = "config/sources.yaml") -> str:
    """Ermittelt die konfigurierte Basis-URL der Streamlit Web-App."""
    try:
        from src.aggregator import load_sources
        config = load_sources(config_path)
        configured_url = config.get("settings", {}).get("streamlit_app_url")
        if configured_url and str(configured_url).strip():
            return str(configured_url).strip().rstrip("/")
    except Exception:
        pass

    env_url = os.getenv("STREAMLIT_APP_URL")
    if env_url and env_url.strip():
        return env_url.strip().rstrip("/")

    try:
        import streamlit as st
        if hasattr(st, "secrets") and "STREAMLIT_APP_URL" in st.secrets:
            return str(st.secrets["STREAMLIT_APP_URL"]).strip().rstrip("/")
    except Exception:
        pass

    return "https://news-aggregator-bot-sdfgedfwcu7yr9gzikr8q8.streamlit.app"


def build_category_quicklinks(config: dict[str, Any], streamlit_base_url: str, config_path: str = "config/sources.yaml") -> dict[str, str]:
    """
    Erstellt für jede Kategorie den Link-Block.
    WICHTIG: Die Feed-Links verweisen direkt auf die Streamlit-App (mit Kategorie- & Feed-Filter),
    damit der Nutzer die formatierten Artikel sieht und nicht die unlesbare Roh-RSS-XML.
    Falls ein APP_PASSWORD hinterlegt ist, wird das sichere Auth-Token an die URLs angehängt,
    sodass der Nutzer bei Klicks aus dem Briefing nie wieder ein Passwort eingeben muss!
    """
    try:
        from src.auth import get_configured_app_password, generate_readonly_auth_token
    except ImportError:
        import importlib
        import src.auth
        importlib.reload(src.auth)
        from src.auth import get_configured_app_password, generate_readonly_auth_token
    app_pw = get_configured_app_password(config_path)
    auth_param = f"&auth={generate_readonly_auth_token(app_pw)}" if app_pw else ""

    category_links = {}
    for cat_item in config.get("categories", []):
        cat_name = cat_item.get("name", "").strip()
        if not cat_name:
            continue
        feeds = cat_item.get("feeds", [])
        encoded_cat = urllib.parse.quote(cat_name)
        cat_app_url = f"{streamlit_base_url}/?category={encoded_cat}{auth_param}"

        feed_parts = []
        for f in feeds:
            fname = f.get("name", "Feed").strip()
            encoded_feed = urllib.parse.quote(fname)
            feed_app_url = f"{streamlit_base_url}/?category={encoded_cat}&feed={encoded_feed}{auth_param}"
            feed_parts.append(f"[{fname}]({feed_app_url})")

        if len(feed_parts) == 1:
            feed_str = f"Feed: {feed_parts[0]}"
        elif len(feed_parts) > 1:
            feed_str = f"Feeds: {', '.join(feed_parts)}"
        else:
            feed_str = ""

        if feed_str:
            category_links[cat_name] = f"> 🔗 [Streamlit App]({cat_app_url}) · {feed_str}"
        else:
            category_links[cat_name] = f"> 🔗 [Streamlit App]({cat_app_url})"

    return category_links


DEFAULT_MAIN_PROMPT_TEMPLATE = """Du bist ein professioneller News-Kurator und Redakteur für ein Daily News Briefing.
Deine Aufgabe ist es, aus den folgenden Roh-Nachrichten ein übersichtliches, kompaktes und leicht lesbares Tages-Briefing auf {lang_name} zu erstellen.

WICHTIGE FORMATIERUNGSRICHTLINIEN:
1. KEIN "Executive Summary" und KEINE allgemeine Einleitung/Zusammenfassung vorweg! Starte direkt mit den Kategorien (z. B. "## 🤖 Tech & AI").
2. INFOBOX GLEICH AM ANFANG JEDER KATEGORIE:
   - Erstelle direkt unter jeder Kategorie-Überschrift (##) als Allererstes eine Infobox (Markdown Blockquote mit '>').
   - Fasse darin alle wichtigsten News und Entwicklungen dieser Kategorie kurz, knapp und prägnant in 2 bis maximal 3 Sätzen zusammen.
   - Format:
     > 💡 **Kompakt:** <Kurze, knappe Zusammenfassung aller wichtigsten News dieser Kategorie>
3. QUICKLINKS-ZEILE:
   - Setze direkt nach der Infobox exakt die vorgegebene Quicklinks-Zeile (Links zur Streamlit App & passenden Feeds) ein.
4. DIE TOP 5 ARTIKEL PRO KATEGORIE:
   - Wähle pro Kategorie maximal die TOP 5 wichtigsten und relevantesten Artikel aus.
   - Bevorzuge dabei unbedingt Artikel, die vom Nutzer positiv bewertet / geliked wurden (mit '⭐ [NUTZER-FAVORIT / GELIKED]' markiert).
   - Artikel, die mit '⚠️ [VOM NUTZER ALS WENIGER RELEVANT / GEDISLIKED]' gekennzeichnet sind, sollen nach Möglichkeit ignoriert oder nur nachrangig berücksichtigt werden.
   - Verlinke den Artikeltitel direkt mit der Originalquelle als Markdown-Link.
   - Erstelle pro Artikel NUR EINE einzige kurze, prägnante Zusammenfassung (1 bis maximal 2 Sätze) direkt hinter dem verlinkten Titel.
   - KEINE Kernaussage und KEINE Bedeutung generieren! Das Wort "TL;DR:" NICHT verwenden!
   - Format:
     - **[Artikeltitel](Original-URL)**: <Prägnante Zusammenfassung in 1-2 Sätzen>
5. Verwende sauberes Markdown mit gut strukturierten Zwischenüberschriften (##) und passenden Emojis.
6. REDAKTIONELLE FILTER & ANWEISUNGEN:
{active_directives}

Hier sind die aktuellen Roh-Nachrichten nach Kategorien gegliedert:
{context_data}
"""

DEFAULT_DIRECTIVES = """- Filtere reine Werbung, Angebote, Sonderaktionen, Rabatte, Advertorials oder gesponserte Beiträge strikt heraus.
- Nimm nur Artikel auf, die einen echten nachrichtlichen Informationswert bieten."""


def _strip_executive_summaries(text: str) -> str:
    """Entfernt Executive Summary Abschnitte und globale Überschriften."""
    cleaned = re.sub(
        r"(?is)^#{1,3}\s*(?:📌\s*)?Executive Summary.*?(?=\n#{1,3}\s+[^\n]+|\Z)",
        "",
        text,
    )
    cleaned = re.sub(
        r"(?i)^#{1,2}\s+(?:📊\s*)?(?:Daily\s+)?(?:Executive\s+)?Briefing[^\n]*\n+",
        "",
        cleaned.strip(),
    )
    return re.sub(r"^(?:\s*---\s*\n+)+", "", cleaned).strip()


def _strip_tldr_markers(text: str) -> str:
    """Entfernt redundante TL;DR Kennzeichnungen aus Aufzählungspunkten."""
    text = re.sub(r"(?<=\*\*:\s)(?:TL;?DR:?\s*)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<=\]\):\s)(?:TL;?DR:?\s*)", "", text, flags=re.IGNORECASE)
    return re.sub(r"\bTL;?DR:?\s*", "", text, flags=re.IGNORECASE)


def _match_category_name(raw_title: str, available_categories: list[str]) -> str | None:
    """Findet die passende Kategorie anhand von Normalisierung und Substring-Matching."""
    cleaned_title = re.sub(r"[^\w\s&]", "", raw_title).strip().lower()
    for cat_name in available_categories:
        c_clean = re.sub(r"[^\w\s&]", "", cat_name).strip().lower()
        if c_clean and (c_clean in cleaned_title or cleaned_title in c_clean):
            return cat_name
    return None


def _clean_and_enhance_briefing(
    text: str,
    category_links: dict[str, str],
    max_items_per_category: int = 5,
) -> str:
    """
    Bereinigt das KI-Briefing:
    - Entfernt jegliches Executive Summary oder einleitende Vorab-Zusammenfassungen
    - Entfernt das Wort 'TL;DR:' vor den Zusammenfassungen
    - Stellt sicher, dass jede Kategorie als Infobox eine kurze Zusammenfassung und die Quicklinks enthält
    - Begrenzt die Artikelanzahl pro Kategorie strikt auf die TOP 5
    - Garantiert Leerzeilen nach Blockquotes, damit Markdown saubere HTML-Elemente erzeugt
    """
    text = _strip_executive_summaries(text)
    text = _strip_tldr_markers(text)

    lines = text.split("\n")
    processed_lines: list[str] = []
    current_cat: str | None = None
    cat_links_inserted = False
    cat_item_count = 0

    header_pattern = re.compile(r"^(#{2,3})\s+(.*)$")
    available_cats = list(category_links.keys())

    def flush_quicklinks_if_needed():
        nonlocal cat_links_inserted
        if current_cat and not cat_links_inserted:
            ql = category_links.get(current_cat)
            if ql:
                processed_lines.append("")
                processed_lines.append(ql)
                processed_lines.append("")
            cat_links_inserted = True

    for line in lines:
        match = header_pattern.match(line.strip())
        if match:
            flush_quicklinks_if_needed()
            raw_title = match.group(2).strip()
            current_cat = _match_category_name(raw_title, available_cats)
            cat_links_inserted = False
            cat_item_count = 0
            processed_lines.append(line)
            continue

        stripped = line.strip()

        # Erkennung von Quicklinks
        if current_cat and "Streamlit App" in stripped:
            cat_links_inserted = True
            clean_line = stripped if stripped.startswith(">") else f"> {stripped}"
            processed_lines.append(clean_line)
            processed_lines.append("")
            continue

        # Erkennung von Infoboxen (> ...)
        if current_cat and stripped.startswith(">"):
            processed_lines.append(stripped)
            processed_lines.append("")
            continue

        # Erkennung von Artikellistenpunkten (- oder *)
        if current_cat and (stripped.startswith("- ") or stripped.startswith("* ")):
            flush_quicklinks_if_needed()
            cat_item_count += 1
            if cat_item_count <= max_items_per_category:
                processed_lines.append(line)
            continue

        # Fortsetzungszeilen von Artikeln (z.B. eingerückte Zeilen)
        if current_cat and cat_item_count > 0:
            if cat_item_count <= max_items_per_category:
                processed_lines.append(line)
            continue

        processed_lines.append(line)

    flush_quicklinks_if_needed()

    result = "\n".join(processed_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def summarize_news_with_gemini(
    categorized_news: dict[str, list[dict[str, Any]]],
    api_key: str | None = None,
    model: str | None = None,
    config_path: str = "config/sources.yaml",
    main_prompt_template: str | None = None,
    custom_directives: str | None = None,
) -> str:
    """
    Fasst die gesammelten Nachrichten mit dem Google Gemini Modell zusammen.
    Erstellt ein kompaktes Briefing ohne Executive Summary mit einer Infobox pro Kategorie,
    Quicklinks zur Streamlit App & Feeds sowie den Top 5 verlinkten Artikeln pro Kategorie.
    """
    try:
        from src.aggregator import load_sources
        config = load_sources(config_path)
        settings = config.get("settings", {})
    except Exception as exc:
        logger.warning("Quellen konnten nicht geladen werden (%s). Verwende Defaults.", exc)
        config = {"categories": []}
        settings = {}

    language = settings.get("language", "de")
    lang_name = "Deutsch" if language == "de" else language

    streamlit_app_url = get_streamlit_app_url(config_path)
    category_links = build_category_quicklinks(config, streamlit_app_url, config_path)

    active_directives = (custom_directives or "").strip()
    if not active_directives:
        active_directives = (settings.get("custom_prompt_directives") or "").strip()
    if not active_directives:
        active_directives = DEFAULT_DIRECTIVES

    active_main_template = (main_prompt_template or "").strip()
    if not active_main_template:
        active_main_template = (settings.get("custom_main_prompt") or "").strip()
    if not active_main_template:
        active_main_template = DEFAULT_MAIN_PROMPT_TEMPLATE

    active_key = api_key or get_configured_api_key()
    if not active_key or active_key.startswith("your_"):
        logger.info("Kein gültiger GEMINI_API_KEY gefunden. Erzeuge Standard-Zusammenfassung.")
        print("[Hinweis] Kein gültiger GEMINI_API_KEY gefunden. Erzeuge Standard-Zusammenfassung...")
        return _generate_fallback_summary(categorized_news, category_links=category_links)

    try:
        from google import genai
        client = genai.Client(api_key=active_key)

        context_lines = []
        for cat, items in sorted(categorized_news.items(), key=lambda x: x[0].strip().lower()):
            if not items:
                continue
            context_lines.append(f"\n\n## {cat}")
            quicklink = category_links.get(cat, "")
            if quicklink:
                context_lines.append(f"\nQuicklinks-Zeile für '{cat}':\n{quicklink}\n")
            def briefing_sort_key(it: dict[str, Any]) -> tuple[int, float]:
                fb = int(it.get("feedback") or 0)
                # Priorität: Like (1) -> 2, Neutral (0) -> 1, Dislike (-1) -> 0
                priority = 2 if fb > 0 else (0 if fb < 0 else 1)
                ts = float(it.get("timestamp") or 0.0)
                return (priority, ts)

            sorted_items = sorted(items, key=briefing_sort_key, reverse=True)
            for item in sorted_items:
                fb = int(item.get("feedback") or 0)
                fav_tag = " ⭐ [NUTZER-FAVORIT / GELIKED - BITTE BEVORZUGT BERÜCKSICHTIGEN]" if fb > 0 else ""
                dislike_tag = " ⚠️ [VOM NUTZER ALS WENIGER RELEVANT / GEDISLIKED MARKIERT]" if fb < 0 else ""
                context_lines.append(f"- **{item['title']}**{fav_tag}{dislike_tag} (Quelle: {item.get('source', 'Unbekannt')})")
                if item.get("summary"):
                    context_lines.append(f"  Auszug: {item['summary']}")
                context_lines.append(f"  Link: {item['link']}")

        context_data_str = "".join(context_lines)

        prompt = active_main_template
        if "{lang_name}" in prompt:
            prompt = prompt.replace("{lang_name}", lang_name)
        if "{active_directives}" in prompt:
            prompt = prompt.replace("{active_directives}", active_directives)
        else:
            prompt += f"\n\nREDAKTIONELLE FILTER & ANWEISUNGEN:\n{active_directives}\n"
        if "{context_data}" in prompt:
            prompt = prompt.replace("{context_data}", context_data_str)
        else:
            prompt += f"\n\nHier sind die aktuellen Roh-Nachrichten nach Kategorien gegliedert:\n{context_data_str}\n"

        candidate_models = get_candidate_models(model)

        last_error = None
        for model_name in candidate_models:
            try:
                logger.info("Generiere mit KI-Modell: %s", model_name)
                print(f"      -> Generiere mit Modell: {model_name}...")
                try:
                    chat = client.chats.create(model=model_name)
                    response = chat.send_message(prompt)
                except AttributeError:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                    )
                if response and response.text:
                    cleaned_result = _clean_and_enhance_briefing(response.text, category_links)
                    return cleaned_result
            except Exception as model_err:
                logger.warning("Modell %s temporär nicht erreichbar (%s). Versuche Alternative...", model_name, model_err)
                print(f"      [Warnung] Modell {model_name} temporär nicht erreichbar ({model_err}). Versuche Alternative...")
                last_error = model_err

        logger.error("Alle KI-Modelle schlugen fehl: %s", last_error)
        print(f"[Fehler] Alle KI-Modelle schlugen fehl: {last_error}")
        return _generate_fallback_summary(categorized_news, category_links=category_links)
    except Exception as exc:
        logger.error("Initialisierungsfehler Gemini API: %s", exc)
        print(f"[Fehler] Initialisierungsfehler Gemini API: {exc}")
        return _generate_fallback_summary(categorized_news, category_links=category_links)


def _generate_fallback_summary(
    categorized_news: dict[str, list[dict[str, Any]]],
    category_links: dict[str, str] | None = None,
    **kwargs: Any,
) -> str:
    """Einfacher Markdown-Report ohne LLM (Fallback)."""
    lines = []
    category_links = category_links or {}
    for cat, items in sorted(categorized_news.items(), key=lambda x: x[0].strip().lower()):
        if not items:
            continue
        lines.append(f"## {cat}")

        def briefing_sort_key(it: dict[str, Any]) -> tuple[int, float]:
            fb = int(it.get("feedback") or 0)
            priority = 2 if fb > 0 else (0 if fb < 0 else 1)
            ts = float(it.get("timestamp") or 0.0)
            return (priority, ts)

        sorted_items = sorted(items, key=briefing_sort_key, reverse=True)
        top_items = sorted_items[:5]

        lines.append(f"> 💡 **Kompakt:** Die wichtigsten {len(top_items)} Meldungen der Kategorie '{cat}'.\n")

        if cat in category_links:
            lines.append(category_links[cat] + "\n")

        for item in top_items:
            title = item.get("title", "Kein Titel")
            link = item.get("link", "#")
            summary = item.get("summary", "")
            source = item.get("source", "")
            if summary:
                lines.append(f"- **[{title}]({link})**: {summary}")
            elif source:
                lines.append(f"- **[{title}]({link})** ({source})")
            else:
                lines.append(f"- **[{title}]({link})**")
        lines.append("")
    return "\n".join(lines).strip()
