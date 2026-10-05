"""
Spezialisierter Scraper und Cache für Berliner Polizeimeldungen (Ereignisort & Teaser-Text).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import requests

from src.filters import clean_html_text, unwrap_and_clean_url, get_canonical_url

_POLICE_TEASER_CACHE: dict[str, str] = {}
_POLICE_CACHE_FILE = Path("data/police_teasers_cache.json")


def _load_police_cache() -> None:
    global _POLICE_TEASER_CACHE
    if not _POLICE_TEASER_CACHE and _POLICE_CACHE_FILE.exists():
        try:
            with open(_POLICE_CACHE_FILE, "r", encoding="utf-8") as f:
                _POLICE_TEASER_CACHE = json.load(f)
        except Exception:
            pass


def _save_police_cache() -> None:
    try:
        _POLICE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_POLICE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_POLICE_TEASER_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def extract_police_teaser(url: str, session: requests.Session | None = None) -> str:
    """Extrahiert den Ereignisort (Bezirk/Stadtteil) und Teaser-Text einer Berliner Polizeimeldung aus dem HTML-Body."""
    if not url or "berlin.de/polizei" not in url:
        return ""
    _load_police_cache()
    clean_u = unwrap_and_clean_url(url)
    if clean_u in _POLICE_TEASER_CACHE and _POLICE_TEASER_CACHE[clean_u]:
        return _POLICE_TEASER_CACHE[clean_u]
    if url in _POLICE_TEASER_CACHE and _POLICE_TEASER_CACHE[url]:
        return _POLICE_TEASER_CACHE[url]

    for attempt in range(2):
        try:
            s = session or requests
            r = s.get(
                url,
                timeout=8.0,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NewsAggregatorBot/1.0"}
            )
            if r.status_code == 200:
                district = ""
                m_dist = re.search(r'title=[\'"]Ereignisort[\'"]>([^<]+)<', r.text, re.IGNORECASE)
                if m_dist:
                    district = clean_html_text(m_dist.group(1)).strip()

                teaser = ""
                m_nr = re.search(r'<p[^>]*>\s*<strong>Nr\.\s*\d+</strong><br\s*/?>\s*(.*?)</p>', r.text, re.DOTALL | re.IGNORECASE)
                if m_nr:
                    clean = clean_html_text(m_nr.group(1))
                    clean = re.sub(r"^Nr\.\s*\d+\s*", "", clean).strip()
                    if len(clean) > 300:
                        clean = clean[:297] + "..."
                    teaser = clean
                else:
                    for p in re.findall(r'<p.*?>(.*?)</p>', r.text, re.DOTALL):
                        clean = clean_html_text(p)
                        if len(clean) > 40 and not any(bad in clean.lower() for bad in ["barrierefrei", "berlin.de ist ein angebot", "kontakt zur ansprechperson", "landesbeauftragte", "impressum"]):
                            clean = re.sub(r"^Nr\.\s*\d+\s*", "", clean).strip()
                            if len(clean) > 300:
                                clean = clean[:297] + "..."
                            teaser = clean
                            break

                res = ""
                if district and teaser:
                    res = f"📍 **{district}** – {teaser}"
                elif district:
                    res = f"📍 **{district}**"
                elif teaser:
                    res = teaser

                if res:
                    _POLICE_TEASER_CACHE[url] = res
                    _POLICE_TEASER_CACHE[clean_u] = res
                    _POLICE_TEASER_CACHE[get_canonical_url(url)] = res
                    return res
        except Exception:
            pass
    return ""
