"""
Netzwerk-Abruf, Stream-Typerkennung, Auto-Discovery und Verbindungstests für RSS/Atom-Feeds.
"""

from __future__ import annotations

import re
import time
import urllib.parse
import logging
from pathlib import Path
from typing import Any

import requests
import feedparser

from src.filters import clean_html_text, unwrap_and_clean_url

logger = logging.getLogger(__name__)

FEED_REQUEST_HEADERS_READER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) NetNewsWire/6.1"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
}

FEED_REQUEST_HEADERS_BOT = {
    "User-Agent": "Feedfetcher-Google; (+http://www.google.com/feedfetcher.html)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

FEED_REQUEST_HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
}


def determine_stream_type(version: str, content_type: str, raw_content: bytes) -> str:
    """Bestimmt den lesbaren Typ des Datenstroms (z. B. RSS 2.0, Atom 1.0, HTML)."""
    v_low = (version or "").lower().strip()
    if v_low == "rss20":
        return "RSS 2.0"
    elif v_low == "atom10":
        return "Atom 1.0"
    elif v_low in ("rss091", "rss092"):
        return "RSS 0.9x"
    elif v_low == "rss10":
        return "RSS 1.0 (RDF)"
    elif v_low == "atom03":
        return "Atom 0.3"
    elif "rss" in v_low:
        return f"RSS ({version})"
    elif "atom" in v_low:
        return f"Atom ({version})"

    head = raw_content[:1500].decode("utf-8", errors="ignore").lower()
    if "<rss" in head:
        return "RSS 2.0"
    if "<feed" in head and ("xmlns=\"http://www.w3.org/2005/atom\"" in head or "xmlns='http://www.w3.org/2005/atom'" in head or "atom" in head):
        return "Atom 1.0"
    if "<rdf:rdf" in head:
        return "RSS 1.0 (RDF)"
    if "<!doctype html" in head or "<html" in head or "text/html" in (content_type or "").lower():
        return "HTML-Webseite (Kein RSS-Stream)"
    return "Unbekanntes Format"


def autodiscover_rss_feeds(raw_content: bytes, base_url: str) -> list[dict[str, str]]:
    """Sucht in HTML-Inhalten nach verlinkten RSS/Atom-Feeds (<link rel='alternate' ...>)."""
    discovered: list[dict[str, str]] = []
    if not raw_content:
        return discovered
    try:
        text = raw_content[:30000].decode("utf-8", errors="ignore")
        link_tags = re.findall(r"<link[^>]+>", text, re.IGNORECASE)
        seen_urls = set()
        for tag in link_tags:
            tag_l = tag.lower()
            if "alternate" in tag_l and ("rss" in tag_l or "atom" in tag_l or "xml" in tag_l):
                m_href = re.search(r'href=[\'"]([^\'"]+)[\'"]', tag, re.IGNORECASE)
                m_title = re.search(r'title=[\'"]([^\'"]+)[\'"]', tag, re.IGNORECASE)
                if m_href:
                    href = m_href.group(1).strip()
                    full_url = urllib.parse.urljoin(base_url, href)
                    if full_url not in seen_urls:
                        seen_urls.add(full_url)
                        title = m_title.group(1).strip() if m_title else "RSS-Feed"
                        discovered.append({"title": title, "url": full_url})
    except Exception:
        pass
    return discovered


def fetch_feed_raw(feed_url: str, timeout: int = 10) -> dict[str, Any]:
    """
    Lädt die Rohdaten einer Feed-URL robust mittels requests herunter.
    Unterstützt automatische RSS-Header, Fallback-Header bei 202/403/406,
    WAF-Bypass-Proxy (Jina AI) und lokalen Projekt-Mirror.
    """
    feed_url = (feed_url or "").strip()
    if not (feed_url.startswith("http://") or feed_url.startswith("https://")):
        return {
            "success": False,
            "status_code": 0,
            "error": "URL muss mit http:// oder https:// beginnen.",
            "content": b"",
            "headers": {},
            "final_url": feed_url,
            "is_redirected": False,
            "content_type": "",
            "latency_ms": 0,
            "is_proxied": False,
            "is_cached_mirror": False,
        }

    header_variants = [FEED_REQUEST_HEADERS_READER, FEED_REQUEST_HEADERS_BOT, FEED_REQUEST_HEADERS_BROWSER]
    last_err = None
    last_resp = None

    t0 = time.time()
    for headers in header_variants:
        try:
            with requests.Session() as session:
                resp = session.get(feed_url, headers=headers, timeout=timeout, allow_redirects=True)
                last_resp = resp
                if resp.status_code == 200:
                    # Validieren, dass nicht ein HTML-Challenge-Body fälschlicherweise mit 200 kam
                    head_l = resp.content[:1500].lower()
                    if b"<rss" in head_l or b"<feed" in head_l or b"<?xml" in head_l or b"<rdf:rdf" in head_l:
                        break
                    if "text/html" in resp.headers.get("content-type", "").lower():
                        continue
                    break
                # Bei WAF-Challenge (202), Forbidden (403), Not Acceptable (406) etc. nächsten Headersatz probieren
                if resp.status_code in [202, 403, 406, 429, 503]:
                    continue
                break
        except Exception as e:
            last_err = e

    latency_ms = int((time.time() - t0) * 1000)

    # 1. Erfolgreicher Direktabruf (echter XML-Stream mit Status 200)
    if last_resp is not None and last_resp.status_code == 200:
        head_l = last_resp.content[:1500].lower()
        if b"<rss" in head_l or b"<feed" in head_l or b"<?xml" in head_l or b"<rdf:rdf" in head_l or "xml" in last_resp.headers.get("content-type", "").lower():
            return {
                "success": True,
                "status_code": 200,
                "content": last_resp.content,
                "headers": dict(last_resp.headers),
                "final_url": str(last_resp.url),
                "is_redirected": str(last_resp.url).rstrip("/") != feed_url.rstrip("/"),
                "content_type": last_resp.headers.get("content-type", ""),
                "latency_ms": latency_ms,
                "is_proxied": False,
                "is_cached_mirror": False,
                "error": None,
            }

    # 2. Versuch über WAF-Bypass-Proxy (r.jina.ai) bei 202 (AWS WAF Challenge), 403 (Forbidden) oder HTML-Challenge
    if last_resp is None or last_resp.status_code in [202, 403, 406, 429, 500, 502, 503] or ("text/html" in getattr(last_resp, "headers", {}).get("content-type", "").lower()):
        try:
            proxy_url = f"https://r.jina.ai/{feed_url}"
            with requests.Session() as session:
                p_resp = session.get(proxy_url, timeout=timeout)
                if p_resp.status_code == 200:
                    text_p = p_resp.text
                    idx_rss = text_p.find("<rss")
                    if idx_rss == -1:
                        idx_rss = text_p.find("<feed")
                    if idx_rss != -1:
                        clean_xml = text_p[idx_rss:].encode("utf-8")
                        return {
                            "success": True,
                            "status_code": 200,
                            "content": clean_xml,
                            "headers": {"content-type": "application/rss+xml; charset=utf-8"},
                            "final_url": feed_url,
                            "is_redirected": False,
                            "content_type": "application/rss+xml; charset=utf-8",
                            "latency_ms": int((time.time() - t0) * 1000),
                            "is_proxied": True,
                            "is_cached_mirror": False,
                            "error": None,
                        }
        except Exception:
            pass

    # 3. Versuch: Synchronisierter lokaler oder GitHub-Projekt-Mirror (static/rss/feeds/)
    try:
        clean_url_key = feed_url.replace("https://", "").replace("http://", "").strip("/")
        feed_dir = Path("static/rss/feeds")
        if feed_dir.exists():
            for xml_file in feed_dir.glob("*.xml"):
                content = xml_file.read_bytes()
                if feed_url.encode("utf-8") in content or clean_url_key.encode("utf-8") in content:
                    return {
                        "success": True,
                        "status_code": 200,
                        "content": content,
                        "headers": {"content-type": "application/rss+xml; charset=utf-8"},
                        "final_url": feed_url,
                        "is_redirected": False,
                        "content_type": "application/rss+xml; charset=utf-8",
                        "latency_ms": int((time.time() - t0) * 1000),
                        "is_proxied": False,
                        "is_cached_mirror": True,
                        "error": None,
                    }
    except Exception:
        pass

    # 4. Falls alles fehlschlägt, letzten HTTP-Fehler zurückgeben
    if last_resp is not None:
        return {
            "success": False,
            "status_code": last_resp.status_code,
            "content": last_resp.content,
            "headers": dict(last_resp.headers),
            "final_url": str(last_resp.url),
            "is_redirected": str(last_resp.url).rstrip("/") != feed_url.rstrip("/"),
            "content_type": last_resp.headers.get("content-type", ""),
            "latency_ms": latency_ms,
            "is_proxied": False,
            "is_cached_mirror": False,
            "error": f"HTTP {last_resp.status_code}" if last_resp.status_code != 200 else "Kein valider RSS-Stream",
        }

    return {
        "success": False,
        "status_code": 0,
        "content": b"",
        "headers": {},
        "final_url": feed_url,
        "is_redirected": False,
        "content_type": "",
        "latency_ms": latency_ms,
        "is_proxied": False,
        "is_cached_mirror": False,
        "error": str(last_err or "Verbindungsaufbau fehlgeschlagen"),
    }


def test_feed_connection(feed_url: str, timeout: int = 10) -> dict[str, Any]:
    """Testet die Erreichbarkeit, Stream-Validität und Metadaten einer Feed-URL."""
    feed_url = (feed_url or "").strip()
    if not feed_url:
        return {"success": False, "is_valid_feed": False, "error": "URL ist leer.", "item_count": 0, "title": "Keine URL"}

    if not (feed_url.startswith("http://") or feed_url.startswith("https://")):
        return {"success": False, "is_valid_feed": False, "error": "URL muss mit http:// oder https:// beginnen.", "item_count": 0, "title": "Ungültige URL"}

    import sys
    _agg_mod = sys.modules.get("src.aggregator")
    _fetch_fn = getattr(_agg_mod, "fetch_feed_raw", fetch_feed_raw) if _agg_mod else fetch_feed_raw

    raw_res = _fetch_fn(feed_url, timeout=timeout)
    if not raw_res["success"] and not raw_res["content"]:
        # Fallback auf direkte feedparser URL-Auflösung
        try:
            p_fallback = feedparser.parse(feed_url)
            fb_entries = getattr(p_fallback, "entries", [])
            if fb_entries or getattr(p_fallback, "version", ""):
                feed_title = clean_html_text(p_fallback.feed.get("title", "")) if hasattr(p_fallback, "feed") else ""
                latest_title = clean_html_text(fb_entries[0].get("title", "Kein Titel")) if fb_entries else "Keine Artikel vorhanden"
                return {
                    "success": True,
                    "is_valid_feed": True,
                    "title": feed_title or "Unbekannter Titel",
                    "description": clean_html_text(getattr(p_fallback.feed, "description", "")),
                    "site_url": getattr(p_fallback.feed, "link", ""),
                    "language": getattr(p_fallback.feed, "language", ""),
                    "last_updated": getattr(p_fallback.feed, "updated", "") or getattr(p_fallback.feed, "published", ""),
                    "item_count": len(fb_entries),
                    "latest_title": latest_title,
                    "stream_type": getattr(p_fallback, "version", "RSS/Atom"),
                    "feed_version": getattr(p_fallback, "version", ""),
                    "status_code": getattr(p_fallback, "status", 200),
                    "content_type": p_fallback.get("headers", {}).get("content-type", "application/xml"),
                    "content_length": len(getattr(p_fallback, "raw", b"")),
                    "latency_ms": raw_res.get("latency_ms", 0),
                    "final_url": feed_url,
                    "is_redirected": False,
                    "sample_items": [
                        {
                            "title": clean_html_text(getattr(e, "title", "Ohne Titel")),
                            "link": unwrap_and_clean_url(getattr(e, "link", "").strip()),
                            "published": getattr(e, "published", "") or getattr(e, "updated", ""),
                            "summary": clean_html_text(getattr(e, "summary", "") or getattr(e, "description", ""))[:160],
                        }
                        for e in fb_entries[:3]
                    ],
                    "warning": None,
                    "error": None,
                    "autodiscovered_feeds": [],
                }
        except Exception:
            pass

        return {
            "success": False,
            "is_valid_feed": False,
            "title": "Verbindung fehlgeschlagen",
            "stream_type": "Kein Stream",
            "item_count": 0,
            "latest_title": "Keine Artikel vorhanden",
            "status_code": raw_res.get("status_code", 0),
            "content_type": raw_res.get("content_type", ""),
            "content_length": 0,
            "latency_ms": raw_res.get("latency_ms", 0),
            "final_url": feed_url,
            "is_redirected": False,
            "sample_items": [],
            "error": raw_res.get("error") or "Feed-URL konnte nicht erreicht werden.",
            "warning": None,
            "autodiscovered_feeds": [],
        }

    raw_data = raw_res["content"]
    content_type = raw_res.get("content_type", "")
    final_url = raw_res.get("final_url", feed_url)

    parsed = feedparser.parse(raw_data)
    entries = getattr(parsed, "entries", [])
    feed_meta = getattr(parsed, "feed", {})

    feed_title = clean_html_text(feed_meta.get("title", "")) if hasattr(feed_meta, "get") else ""
    feed_desc = clean_html_text(feed_meta.get("description", "") or feed_meta.get("subtitle", "")) if hasattr(feed_meta, "get") else ""
    feed_link = feed_meta.get("link", "") if hasattr(feed_meta, "get") else ""
    feed_lang = feed_meta.get("language", "") if hasattr(feed_meta, "get") else ""
    feed_updated = feed_meta.get("updated", "") or feed_meta.get("published", "") or feed_meta.get("pubDate", "") if hasattr(feed_meta, "get") else ""

    stream_version = getattr(parsed, "version", "")
    stream_type = determine_stream_type(stream_version, content_type, raw_data)

    is_html = "html" in stream_type.lower() or ("text/html" in content_type.lower() and not entries)
    discovered_feeds = []
    if is_html or (not entries and "text/html" in content_type.lower()):
        discovered_feeds = autodiscover_rss_feeds(raw_data, final_url)

    # Wenn 0 Einträge und HTML oder WAF-Block:
    if not entries and is_html:
        err_msg = "Die URL liefert eine HTML-Webseite statt eines RSS-Streams."
        text_preview = raw_data[:1000].decode("utf-8", errors="ignore").lower()
        if any(term in text_preview for term in ["cloudflare", "waf", "challenge", "403 forbidden", "access denied", "bot"]):
            err_msg += " (Hinweis: Die Website blockiert den automatisierten Zugriff durch einen WAF-/Bot-Schutz)."
        return {
            "success": False,
            "is_valid_feed": False,
            "title": feed_title or "HTML Webseite (Kein Feed)",
            "description": feed_desc,
            "site_url": feed_link or final_url,
            "language": feed_lang,
            "last_updated": feed_updated,
            "stream_type": "HTML-Webseite (Kein RSS-Stream)",
            "feed_version": "",
            "item_count": 0,
            "latest_title": "Keine Artikel vorhanden",
            "status_code": raw_res.get("status_code", 200),
            "content_type": content_type,
            "content_length": len(raw_data),
            "latency_ms": raw_res.get("latency_ms", 0),
            "final_url": final_url,
            "is_redirected": raw_res.get("is_redirected", False),
            "sample_items": [],
            "error": err_msg,
            "warning": None,
            "autodiscovered_feeds": discovered_feeds,
        }

    # Wenn 0 Einträge und fehlerhafte XML-Syntax:
    if not entries and hasattr(parsed, "bozo") and parsed.bozo:
        bozo_exc = getattr(parsed, "bozo_exception", "Unbekannter Parsing-Fehler")
        return {
            "success": False,
            "is_valid_feed": False,
            "title": feed_title or "Ungültiger Stream",
            "description": feed_desc,
            "site_url": feed_link or final_url,
            "language": feed_lang,
            "last_updated": feed_updated,
            "stream_type": stream_type,
            "feed_version": stream_version,
            "item_count": 0,
            "latest_title": "Keine Artikel vorhanden",
            "status_code": raw_res.get("status_code", 200),
            "content_type": content_type,
            "content_length": len(raw_data),
            "latency_ms": raw_res.get("latency_ms", 0),
            "final_url": final_url,
            "is_redirected": raw_res.get("is_redirected", False),
            "sample_items": [],
            "error": f"Fehler beim Parsen des Feeds: {bozo_exc}",
            "warning": None,
            "autodiscovered_feeds": discovered_feeds,
        }

    sample_items = []
    for e in entries[:3]:
        e_title = clean_html_text(getattr(e, "title", "Ohne Titel"))
        e_link = unwrap_and_clean_url(getattr(e, "link", "").strip())
        e_pub = getattr(e, "published", "") or getattr(e, "updated", "") or ""
        e_desc = clean_html_text(getattr(e, "summary", "") or getattr(e, "description", ""))
        if len(e_desc) > 160:
            e_desc = e_desc[:157] + "..."
        sample_items.append({
            "title": e_title,
            "link": e_link,
            "published": e_pub,
            "summary": e_desc,
        })

    latest_title = sample_items[0]["title"] if sample_items else "Keine Artikel vorhanden"
    latest_date = sample_items[0]["published"] if sample_items else ""
    latest_link = sample_items[0]["link"] if sample_items else ""

    display_title = feed_title or (f"Feed ({urllib.parse.urlparse(feed_url).netloc})" if entries else "Unbekannter Titel")

    warning = None
    if raw_res.get("is_proxied"):
        warning = "Der Feed liegt hinter einem WAF-/Bot-Schutz (z. B. CloudFront HTTP 202) und wurde erfolgreich über einen WAF-Proxy geladen."
    elif raw_res.get("is_cached_mirror"):
        warning = "Der Feed liegt hinter einem WAF-/Bot-Schutz und wurde aus dem synchronisierten Projekt-Mirror geladen."
    elif len(entries) == 0:
        warning = "Feed ist erreichbar und syntaktisch valide, enthält aber aktuell 0 Einträge."
    elif raw_res.get("is_redirected"):
        warning = f"URL wurde weitergeleitet auf: {final_url}"

    return {
        "success": True,
        "is_valid_feed": True,
        "title": display_title,
        "description": feed_desc,
        "site_url": feed_link or final_url,
        "language": feed_lang,
        "last_updated": feed_updated,
        "stream_type": stream_type,
        "feed_version": stream_version,
        "status_code": raw_res.get("status_code", 200),
        "content_type": content_type,
        "content_length": len(raw_data),
        "latency_ms": raw_res.get("latency_ms", 0),
        "final_url": final_url,
        "is_redirected": raw_res.get("is_redirected", False),
        "item_count": len(entries),
        "latest_title": latest_title,
        "latest_date": latest_date,
        "latest_link": latest_link,
        "sample_items": sample_items,
        "warning": warning,
        "error": None,
        "autodiscovered_feeds": discovered_feeds,
    }


# Pytest daran hindern, diese Hilfsfunktion als Test-Fixture zu behandeln
test_feed_connection.__test__ = False
