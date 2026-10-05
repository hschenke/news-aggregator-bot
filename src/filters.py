"""
Filter-, Bereinigungs- und Zeitprüfungs-Funktionen für den News Aggregator Bot.
"""

from __future__ import annotations

import re
import html
import functools
import urllib.parse
import calendar
import email.utils
import time
from datetime import datetime
from typing import Any

DEFAULT_AD_PATTERNS: list[str] = [
    r"^heise-angebot:",
    r"^(?:anzeige|werbung|gesponsert|partnerangebot)\s*[:\-\|•]",
    r"\[(?:anzeige|werbung|sponsored|gesponsert|partnerangebot|advertorial)\]",
    r"\((?:anzeige|werbung|sponsored|gesponsert|partnerangebot|advertorial)\)",
    r"\b(?:advertorial|partnerangebot|sonderveröffentlichung)\b",
    r"\b(?:sponsored post|sponsored content)\b",
    r"\bdeal(?:s)? des tages\b",
    r"^rabatt-aktion\b",
]

DEFAULT_MAX_ARTICLE_AGE_HOURS: float = 24.0
DEFAULT_MAX_ARTICLE_AGE_SECONDS: float = 24.0 * 3600.0
DEFAULT_ARCHIVE_RETENTION_DAYS: int = 7
DEFAULT_MAX_ARTICLE_AGE_WEEKS: int = 20  # Veralteter Kompatibilitätsalias
SECONDS_PER_HOUR: int = 3600
SECONDS_PER_DAY: int = 86400
SECONDS_PER_WEEK: int = 7 * 24 * 60 * 60  # 604_800 Sekunden pro Woche


@functools.lru_cache(maxsize=2048)
def clean_html_text(text: str) -> str:
    """Bereinigt HTML-Tags (z. B. <b>, <i>, <a>), unescaped Entities (&amp;, &quot;) und normalisiert Whitespace."""
    if not text:
        return ""
    # Zweifaches Unescaping für doppelt kodierte HTML-Entities
    cleaned = html.unescape(text)
    if any(entity in cleaned for entity in ["&lt;", "&gt;", "&amp;", "&quot;", "&#"]):
        cleaned = html.unescape(cleaned)
    # Alle HTML-Tags entfernen
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Typische geschützte Leerzeichen und Steuerzeichen aufräumen
    cleaned = cleaned.replace("\xa0", " ").replace("&nbsp;", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


@functools.lru_cache(maxsize=2048)
def format_summary_html(text: str) -> str:
    """
    Bereitet eine Zusammenfassung für HTML-Container auf:
    1. Bereinigt HTML-Tags via clean_html_text().
    2. Wandelt Markdown-Fettdruck (**Text**) in HTML <strong>Text</strong> um,
       sodass Text in HTML-Elementen wie <div> verlässlich fett gerendert wird.
    """
    if not text:
        return ""
    cleaned = clean_html_text(text)
    if not cleaned:
        return ""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", cleaned)


def unwrap_and_clean_url(url: str) -> str:
    """Löst Google Alert Redirect-URLs auf und extrahiert die tatsächliche Ziel-URL."""
    if not url:
        return ""
    url = url.strip()
    if "google.com/url?" in url:
        try:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            target = qs.get("url") or qs.get("q")
            if target and target[0]:
                url = target[0].strip()
        except Exception:
            pass
    return url


def get_canonical_url(url: str) -> str:
    """Normalisiert URLs für die Duplikatsprüfung (entfernt Tracking-Parameter wie utm_*, fbclid)."""
    url = unwrap_and_clean_url(url)
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.query:
            qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            filtered_qs = {
                k: v for k, v in qs.items()
                if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "ocid", "cmpid", "ref"}
            }
            new_query = urllib.parse.urlencode(filtered_qs, doseq=True)
            url = urllib.parse.urlunparse((
                parsed.scheme,
                parsed.netloc.lower(),
                parsed.path.rstrip("/") or "/",
                parsed.params,
                new_query,
                ""
            ))
    except Exception:
        pass
    return url.rstrip("/")


def normalize_keywords(kw: Any) -> list[str]:
    """Wandelt Keywords (Liste, String oder None) in eine bereinigte Liste von Strings um."""
    if not kw:
        return []
    if isinstance(kw, str):
        return [k.strip() for k in kw.split(",") if k.strip()]
    if isinstance(kw, (list, set, tuple)):
        res = []
        for k in kw:
            if isinstance(k, str):
                res.extend([x.strip() for x in k.split(",") if x.strip()])
            elif k is not None:
                res.append(str(k).strip())
        return [r for r in res if r]
    return []


def is_ad_item(title: str, summary: str = "", custom_ad_keywords: list[str] | None = None) -> bool:
    """Prüft, ob ein Artikel Werbung, Anzeige, gesponsertes Angebot oder Deal ist."""
    t_clean = (title or "").strip().lower()
    s_clean = (summary or "").strip().lower()

    for pat in DEFAULT_AD_PATTERNS:
        if re.search(pat, t_clean, re.IGNORECASE) or re.search(pat, s_clean, re.IGNORECASE):
            return True

    if custom_ad_keywords:
        for kw in custom_ad_keywords:
            k = kw.strip().lower()
            if not k:
                continue
            # Allgemeine Kennzeichnungen wie 'anzeige' oder 'werbung' dürfen nicht als einfache Substring-Suche
            # im Fließtext (summary) matchen, da sie dort häufig in legitimem Kontext
            # (z. B. 'Strafanzeige', redaktionelle Banner-Hinweise 'Quelle: Google Anzeige') vorkommen.
            if k in ("anzeige", "werbung", "sponsored", "gesponsert"):
                label_pat = rf"(?:^|\[|\()\s*{re.escape(k)}\s*(?:[:\-\|•\]\)]|$)"
                if re.search(label_pat, t_clean, re.IGNORECASE) or re.search(rf"^{re.escape(k)}\s*[:\-\|•]", s_clean, re.IGNORECASE):
                    return True
            else:
                pat = rf"\b{re.escape(k)}\b"
                if re.search(pat, t_clean, re.IGNORECASE) or re.search(pat, s_clean, re.IGNORECASE):
                    return True

    return False


def get_article_timestamp(item: Any) -> float:
    """
    Ermittelt den Unix-Timestamp (Sekunden seit Epoch) eines Artikels, Eintrags oder Datums.
    Unterstützt Article-Objekte, Dictionaries, feedparser-Entries, Datetime-Objekte und Zahlen.
    Gibt 0.0 zurück, falls kein valides Datum extrahiert werden kann.
    """
    if item is None:
        return 0.0

    if isinstance(item, (int, float)):
        return float(item) if item > 0 else 0.0

    if isinstance(item, datetime):
        return item.timestamp()

    if isinstance(item, time.struct_time):
        try:
            return float(calendar.timegm(item))
        except Exception:
            try:
                return float(time.mktime(item))
            except Exception:
                return 0.0

    # 1. Direkter Timestamp
    ts = None
    if isinstance(item, dict):
        ts = item.get("timestamp")
    elif hasattr(item, "timestamp"):
        ts = getattr(item, "timestamp")

    if ts is not None and isinstance(ts, (int, float)) and ts > 0:
        return float(ts)

    # 2. Parsed struct_time aus RSS/Atom
    parsed_time = None
    if isinstance(item, dict):
        parsed_time = item.get("published_parsed") or item.get("updated_parsed")
    elif hasattr(item, "published_parsed") or hasattr(item, "updated_parsed"):
        parsed_time = getattr(item, "published_parsed", None) or getattr(item, "updated_parsed", None)

    if parsed_time and isinstance(parsed_time, time.struct_time):
        try:
            return float(calendar.timegm(parsed_time))
        except Exception:
            try:
                return float(time.mktime(parsed_time))
            except Exception:
                pass

    # 3. String-Datum (RFC-822 oder ISO-8601)
    pub_str = ""
    if isinstance(item, dict):
        pub_str = item.get("published") or item.get("updated") or ""
    elif hasattr(item, "published") or hasattr(item, "updated"):
        pub_str = getattr(item, "published", "") or getattr(item, "updated", "") or ""

    if isinstance(pub_str, str) and pub_str.strip():
        s = pub_str.strip()
        try:
            dt = email.utils.parsedate_to_datetime(s)
            if dt:
                return dt.timestamp()
        except Exception:
            pass
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            pass

    return 0.0


def is_article_too_old(
    article_or_dict: Any,
    max_age_hours: float | None = DEFAULT_MAX_ARTICLE_AGE_HOURS,
    max_age_weeks: int | float | None = None,
    now_ts: float | None = None,
) -> bool:
    """
    Prüft, ob ein Artikel älter als max_age_hours (Standard: 24 Stunden) ist.
    Gibt True zurück, wenn der Artikel älter als der Stichtag ist und herausgefiltert werden soll.
    Falls max_age_weeks übergeben wird, wird es zur Abwärtskompatibilität in Stunden umgerechnet.
    Artikel ohne ermittelbares Datum (timestamp <= 0.0) werden nicht als zu alt gewertet.
    """
    if max_age_weeks is not None and float(max_age_weeks) > 0:
        hours = float(max_age_weeks) * 7.0 * 24.0
    elif max_age_hours is not None and float(max_age_hours) > 0:
        hours = float(max_age_hours)
    else:
        return False

    ts = get_article_timestamp(article_or_dict)
    if ts <= 0.0:
        return False

    if now_ts is None:
        now_ts = time.time()

    cutoff_ts = now_ts - (hours * 3600.0)
    return ts < cutoff_ts


def filter_articles_by_age(
    articles: list[dict[str, Any]],
    max_age_hours: float | None = DEFAULT_MAX_ARTICLE_AGE_HOURS,
    max_age_weeks: int | float | None = None,
    now_ts: float | None = None,
) -> list[dict[str, Any]]:
    """Filtert eine Artikelliste und schließt alle Artikel aus, die älter als max_age_hours (Standard: 24h) sind."""
    if (max_age_hours is None or max_age_hours <= 0) and (max_age_weeks is None or max_age_weeks <= 0):
        return articles

    if now_ts is None:
        now_ts = time.time()

    return [
        article for article in articles
        if not is_article_too_old(article, max_age_hours=max_age_hours, max_age_weeks=max_age_weeks, now_ts=now_ts)
    ]


def filter_news_data_by_age(
    news_data: dict[str, list[dict[str, Any]]],
    max_age_hours: float | None = DEFAULT_MAX_ARTICLE_AGE_HOURS,
    max_age_weeks: int | float | None = None,
    now_ts: float | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Filtert ein nach Kategorien gruppiertes News-Dictionary nach maximalem Artikel-Alter (Standard: 24h)."""
    if (max_age_hours is None or max_age_hours <= 0) and (max_age_weeks is None or max_age_weeks <= 0):
        return news_data

    if now_ts is None:
        now_ts = time.time()

    filtered: dict[str, list[dict[str, Any]]] = {}
    for category_name, items in news_data.items():
        filtered[category_name] = filter_articles_by_age(
            items,
            max_age_hours=max_age_hours,
            max_age_weeks=max_age_weeks,
            now_ts=now_ts,
        )
    return filtered
