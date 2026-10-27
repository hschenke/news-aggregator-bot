"""
Offline-Archivierung, Webseiten-Snapshot-Extraktion (Text, HTML & Bilder),
Hintergrund-Worker und PDF-/HTML-Export für den News Aggregator Bot.
"""

from __future__ import annotations

import base64
import html
import io
import ipaddress
import json
import logging
import re
import socket
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import requests
from PIL import Image

from src.filters import clean_html_text, unwrap_and_clean_url
from src.models import OfflineArticle
from src.sources_manager import get_offline_enabled_feeds, load_sources
from src.storage import OFFLINE_RETENTION_DAYS, get_storage

logger = logging.getLogger(__name__)

# Sicherheits- und Ressourcen-Limits (DoS- & Speicherschutz)
DEFAULT_HTTP_TIMEOUT_SECONDS: tuple[float, float] = (4.0, 10.0)
MAX_HTML_BYTES: int = 2 * 1024 * 1024  # Max. 2 MB HTML pro Artikel
MAX_IMAGE_BYTES: int = 3 * 1024 * 1024  # Max. 3 MB Rohbild-Download
MAX_IMAGES_PER_ARTICLE: int = 4
MAX_IMAGE_DIMENSION_PX: int = 720
JPEG_COMPRESSION_QUALITY: int = 75
MAX_TEXT_CHARS_PER_ARTICLE: int = 25_000

BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
}

_TASK_LOCK = threading.Lock()
_TASK_STATUS: dict[str, Any] = {
    "is_running": False,
    "current_feed": "",
    "current_article": "",
    "processed_articles": 0,
    "total_articles": 0,
    "saved_articles": 0,
    "cleaned_articles": 0,
    "last_run_at": None,
    "last_error": None,
}


def get_offline_task_status() -> dict[str, Any]:
    """Gibt eine threadsichere Kopie des aktuellen Hintergrundtask-Status zurück."""
    with _TASK_LOCK:
        return dict(_TASK_STATUS)


def _update_task_status(**kwargs: Any) -> None:
    """Aktualisiert den Status des Hintergrund-Archivierungstasks threadsicher."""
    with _TASK_LOCK:
        _TASK_STATUS.update(kwargs)


def is_safe_external_url(url: str) -> bool:
    """
    Prüft eine URL gegen SSRF-Risiken (OWASP A10):
    Erlaubt ausschließlich http/https und blockiert Loopback, RFC-1918 Privatnetze,
    Link-Local sowie Cloud-Metadaten-Endpunkte (169.254.169.254).
    """
    if not url or not isinstance(url, str):
        return False
    clean_url = url.strip()
    try:
        parsed = urllib.parse.urlparse(clean_url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname or hostname in ("localhost", "0.0.0.0", "::1"):
            return False

        # Falls Hostname direkt eine IP ist
        try:
            ip_obj = ipaddress.ip_address(hostname)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                return False
            return True
        except ValueError:
            pass

        # DNS-Auflösung prüfen
        addr_info = socket.getaddrinfo(hostname, None)
        for item in addr_info:
            ip_str = item[4][0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                return False
        return True
    except Exception:
        return False


def _extract_article_paragraphs_from_html(raw_html: str) -> list[str]:
    """
    Extrahiert lesbare Textabsätze und Zwischenüberschriften aus einer HTML-Seite
    ohne störende Skripte, Styles, Navigation oder Footer.
    """
    if not raw_html:
        return []

    # Entferne nicht-redaktionelle Blöcke
    cleaned = re.sub(
        r"<(script|style|noscript|svg|iframe|nav|footer|header|aside|form)[^>]*>.*?</\1>",
        " ",
        raw_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)

    # Bevorzuge <article> oder <main>, falls vorhanden
    article_match = re.search(r"<article[^>]*>(.*?)</article>", cleaned, flags=re.IGNORECASE | re.DOTALL)
    main_match = re.search(r"<main[^>]*>(.*?)</main>", cleaned, flags=re.IGNORECASE | re.DOTALL)
    target_html = (
        article_match.group(1)
        if article_match and len(article_match.group(1)) > 200
        else (main_match.group(1) if main_match and len(main_match.group(1)) > 200 else cleaned)
    )

    blocks = re.findall(
        r"<(h[23]|p|blockquote|li)(?:\s+[^>]*)?>(.*?)</\1>",
        target_html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    paragraphs: list[str] = []
    seen_texts: set[str] = set()
    total_chars = 0

    for tag, inner in blocks:
        text = clean_html_text(inner)
        if not text:
            continue
        # Sehr kurze Fragmente (z. B. Menü-Links oder Cookie-Hinweise) überspringen
        if tag.lower() == "p" and len(text) < 25:
            continue
        if tag.lower() == "li" and len(text) < 35:
            continue
        norm = text.lower()
        if norm in seen_texts:
            continue
        seen_texts.add(norm)

        if tag.lower() in ("h2", "h3"):
            paragraphs.append(f"### {text}")
        else:
            paragraphs.append(text)

        total_chars += len(text)
        if total_chars >= MAX_TEXT_CHARS_PER_ARTICLE:
            break

    return paragraphs


def _extract_candidate_image_urls(raw_html: str, base_url: str, max_images: int = MAX_IMAGES_PER_ARTICLE) -> list[tuple[str, str]]:
    """
    Sucht relevante Artikelbilder (og:image, twitter:image sowie <img> innerhalb von <article>/<main>).
    Gibt eine Liste von (image_url, alt_text) zurück.
    """
    if not raw_html:
        return []

    candidates: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    def _add_candidate(raw_src: str, alt_txt: str = "") -> None:
        if not raw_src or len(candidates) >= max_images:
            return
        src = html.unescape(raw_src.strip())
        if src.startswith("data:") or src.lower().endswith((".svg", ".gif", ".ico")):
            return
        full_url = urllib.parse.urljoin(base_url, src)
        if not (full_url.startswith("http://") or full_url.startswith("https://")):
            return
        low_url = full_url.lower()
        if any(skip in low_url for skip in ["pixel", "tracker", "avatar", "logo", "icon", "sprite", "1x1", "badge", "doubleclick", "vgwort"]):
            return
        if full_url not in seen_urls:
            seen_urls.add(full_url)
            candidates.append((full_url, clean_html_text(alt_txt)[:140]))

    # 1. OpenGraph / Twitter Lead-Image
    for meta_pat in [
        r'<meta[^>]+property=[\'"]og:image[\'"][^>]+content=[\'"]([^\'"]+)[\'"]',
        r'<meta[^>]+content=[\'"]([^\'"]+)[\'"][^>]+property=[\'"]og:image[\'"]',
        r'<meta[^>]+name=[\'"]twitter:image[\'"][^>]+content=[\'"]([^\'"]+)[\'"]',
    ]:
        m = re.search(meta_pat, raw_html, flags=re.IGNORECASE)
        if m:
            _add_candidate(m.group(1), "Titelbild")

    # 2. Bilder im Hauptbereich (<article> / <main> / <body>)
    article_match = re.search(r"<article[^>]*>(.*?)</article>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    main_match = re.search(r"<main[^>]*>(.*?)</main>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    scope_html = (
        article_match.group(1)
        if article_match
        else (main_match.group(1) if main_match else raw_html)
    )

    for img_tag in re.findall(r"<img[^>]+>", scope_html, flags=re.IGNORECASE):
        if len(candidates) >= max_images:
            break
        src_m = re.search(r'(?:data-src|src)=[\'"]([^\'"]+)[\'"]', img_tag, flags=re.IGNORECASE)
        alt_m = re.search(r'alt=[\'"]([^\'"]*)[\'"]', img_tag, flags=re.IGNORECASE)
        if src_m:
            _add_candidate(src_m.group(1), alt_m.group(1) if alt_m else "")

    return candidates


def _download_and_compress_image(
    img_url: str,
    alt_text: str,
    session: requests.Session,
    timeout: tuple[float, float] = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """
    Lädt ein Bild sicher herunter, prüft Mindestgröße (filtert 1x1 Pixel/Icons aus),
    skaliert es auf max. MAX_IMAGE_DIMENSION_PX und komprimiert es als Base64-JPEG.
    """
    if not is_safe_external_url(img_url):
        return None
    try:
        resp = session.get(img_url, headers=BROWSER_HEADERS, timeout=timeout, stream=True)
        if resp.status_code != 200:
            return None

        raw_bytes = b""
        for chunk in resp.iter_content(chunk_size=16384):
            raw_bytes += chunk
            if len(raw_bytes) > MAX_IMAGE_BYTES:
                return None

        if len(raw_bytes) < 800:  # Zu klein (Tracking-Pixel / Mini-Icon)
            return None

        with Image.open(io.BytesIO(raw_bytes)) as img:
            width, height = img.size
            if width < 80 or height < 80:
                return None

            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                converted = img.convert("RGBA")
                bg.paste(converted, mask=converted.split()[-1])
                img_rgb = bg
            else:
                img_rgb = img.convert("RGB")

            img_rgb.thumbnail((MAX_IMAGE_DIMENSION_PX, MAX_IMAGE_DIMENSION_PX), Image.Resampling.LANCZOS)
            out_buf = io.BytesIO()
            img_rgb.save(out_buf, format="JPEG", quality=JPEG_COMPRESSION_QUALITY, optimize=True)
            jpeg_bytes = out_buf.getvalue()
            final_w, final_h = img_rgb.size

        b64_data = base64.b64encode(jpeg_bytes).decode("ascii")
        return {
            "url": img_url,
            "alt": alt_text,
            "mime_type": "image/jpeg",
            "width": final_w,
            "height": final_h,
            "data_b64": b64_data,
        }
    except Exception as exc:
        logger.debug("Bild-Download übersprungen (%s): %s", img_url, exc)
        return None


def _build_self_contained_html_body(
    title: str,
    paragraphs: list[str],
    images: list[dict[str, Any]],
    source_url: str,
) -> str:
    """Erstellt ein sauberes, in sich geschlossenes HTML-Fragment mit eingebetteten Base64-Bildern."""
    parts: list[str] = ['<article class="offline-article-snapshot">']
    parts.append(f"<h2>{html.escape(title)}</h2>")

    if images:
        lead_img = images[0]
        b64 = lead_img.get("data_b64", "")
        mime = lead_img.get("mime_type", "image/jpeg")
        alt = html.escape(lead_img.get("alt") or title)
        if b64:
            parts.append(
                f'<figure style="margin:1rem 0;">'
                f'<img src="data:{mime};base64,{b64}" alt="{alt}" style="max-width:100%;height:auto;border-radius:8px;" />'
                f"</figure>"
            )

    for p in paragraphs:
        if p.startswith("### "):
            parts.append(f"<h3>{html.escape(p[4:])}</h3>")
        else:
            parts.append(f"<p>{html.escape(p)}</p>")

    if len(images) > 1:
        parts.append('<div class="offline-gallery" style="display:flex;flex-wrap:wrap;gap:12px;margin-top:1rem;">')
        for extra_img in images[1:]:
            b64 = extra_img.get("data_b64", "")
            mime = extra_img.get("mime_type", "image/jpeg")
            alt = html.escape(extra_img.get("alt") or "")
            if b64:
                parts.append(
                    f'<img src="data:{mime};base64,{b64}" alt="{alt}" '
                    f'style="max-width:48%;height:auto;border-radius:6px;" />'
                )
        parts.append("</div>")

    if source_url and source_url != "#":
        safe_url = html.escape(source_url)
        parts.append(f'<p style="font-size:0.85rem;color:#64748b;margin-top:1rem;">Originalquelle: <a href="{safe_url}">{safe_url}</a></p>')

    parts.append("</article>")
    return "\n".join(parts)


def fetch_article_snapshot(
    url: str,
    title: str = "",
    fallback_summary: str = "",
    timeout: tuple[float, float] = DEFAULT_HTTP_TIMEOUT_SECONDS,
    download_images: bool = True,
) -> dict[str, Any]:
    """
    Lädt eine Artikel-Webseite herunter und extrahiert:
    - Volltext (content_text)
    - Komprimierte Base64-Bilder (images)
    - Selbstständiges HTML-Abbild (content_html)
    Nutzt bei nicht erreichbaren Seiten oder WAF-Sperren automatisch den RSS-Teaser als Fallback.
    """
    clean_url = unwrap_and_clean_url(url)
    fallback_text = clean_html_text(fallback_summary)

    if not is_safe_external_url(clean_url):
        paragraphs = [fallback_text] if fallback_text else []
        text_out = "\n\n".join(paragraphs)
        html_out = _build_self_contained_html_body(title or "Artikel", paragraphs, [], clean_url)
        return {
            "content_text": text_out,
            "content_html": html_out,
            "images": [],
            "images_json": "[]",
        }

    raw_html = ""
    final_url = clean_url
    images: list[dict[str, Any]] = []

    try:
        with requests.Session() as session:
            resp = session.get(clean_url, headers=BROWSER_HEADERS, timeout=timeout, stream=True)
            final_url = str(resp.url or clean_url)
            if resp.status_code == 200:
                raw_bytes = b""
                for chunk in resp.iter_content(chunk_size=16384):
                    raw_bytes += chunk
                    if len(raw_bytes) >= MAX_HTML_BYTES:
                        break
                encoding = resp.encoding or "utf-8"
                raw_html = raw_bytes.decode(encoding, errors="replace")

            paragraphs = _extract_article_paragraphs_from_html(raw_html)
            if not paragraphs and fallback_text:
                paragraphs = [fallback_text]
            elif fallback_text and sum(len(p) for p in paragraphs) < len(fallback_text):
                paragraphs.insert(0, fallback_text)

            if download_images and raw_html:
                img_candidates = _extract_candidate_image_urls(raw_html, final_url, max_images=MAX_IMAGES_PER_ARTICLE)
                for img_url, alt_txt in img_candidates:
                    img_obj = _download_and_compress_image(img_url, alt_txt, session=session, timeout=timeout)
                    if img_obj:
                        images.append(img_obj)
    except Exception as exc:
        logger.debug("Snapshot-Abruf für %s nutzte Fallback (%s)", clean_url, exc)
        paragraphs = [fallback_text] if fallback_text else []

    content_text = "\n\n".join(paragraphs).strip()
    if not content_text and fallback_text:
        content_text = fallback_text
        paragraphs = [fallback_text]

    content_html = _build_self_contained_html_body(
        title=title or "Artikel",
        paragraphs=paragraphs,
        images=images,
        source_url=final_url,
    )
    images_json = json.dumps(images, ensure_ascii=False)

    return {
        "content_text": content_text,
        "content_html": content_html,
        "images": images,
        "images_json": images_json,
    }


def run_offline_archive_for_feeds(
    config: dict[str, Any] | None = None,
    target_feed_url: str | None = None,
    storage: Any = None,
    max_items_per_feed: int = 30,
) -> dict[str, Any]:
    """
    Geht alle für den Offline-Download aktivierten Feeds durch, entfernt zunächst
    automatisch alle Artikel älter als 3 Monate (90 Tage) und speichert für neue Artikel
    das Webseiten-Abbild (Text, HTML & Bilder) in der Tabelle `offline_articles`.
    """
    from src.aggregator import fetch_feed_items

    if storage is None:
        storage = get_storage()
    if config is None:
        config = load_sources()

    _update_task_status(
        is_running=True,
        current_feed="Prüfe 3-Monats-Aufbewahrung...",
        current_article="",
        processed_articles=0,
        total_articles=0,
        saved_articles=0,
        last_error=None,
    )

    try:
        # 1. Automatische 3-Monats-Bereinigung (90 Tage)
        cleaned_count = storage.cleanup_offline_articles(max_age_days=OFFLINE_RETENTION_DAYS)
        _update_task_status(cleaned_articles=cleaned_count)

        offline_feeds = get_offline_enabled_feeds(config=config)
        if target_feed_url:
            offline_feeds = [
                f for f in offline_feeds
                if f.get("url", "").strip() == target_feed_url.strip()
            ]

        if not offline_feeds:
            now_iso = datetime.now(timezone.utc).isoformat()
            _update_task_status(
                is_running=False,
                current_feed="",
                current_article="",
                last_run_at=now_iso,
            )
            return {"saved": 0, "cleaned": cleaned_count, "feeds_processed": 0}

        settings = config.get("settings", {})
        filter_ads = bool(settings.get("filter_ads", True))
        custom_ad_keywords = settings.get("ad_keywords", [])
        max_age_hours_3m = float(OFFLINE_RETENTION_DAYS) * 24.0

        existing_urls = storage.get_offline_urls()

        # Alle Artikel der aktivierten Offline-Feeds sammeln
        pending_entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for feed_cfg in offline_feeds:
            f_name = feed_cfg["name"]
            f_url = feed_cfg["url"]
            _update_task_status(current_feed=f_name, current_article="Lade Feed-Einträge...")
            try:
                items = fetch_feed_items(
                    f_url,
                    max_items=max_items_per_feed,
                    include_keywords=feed_cfg.get("include_keywords"),
                    exclude_keywords=feed_cfg.get("exclude_keywords"),
                    filter_ads=filter_ads,
                    custom_ad_keywords=custom_ad_keywords,
                    max_age_hours=max_age_hours_3m,
                )
                for it in items:
                    link = str(it.get("link") or "").strip()
                    if link and link != "#" and link not in existing_urls:
                        pending_entries.append((feed_cfg, it))
                        existing_urls.add(link)
            except Exception as exc:
                logger.warning("Offline-Archivierung konnte Feed '%s' nicht lesen: %s", f_name, exc)

        total_to_process = len(pending_entries)
        _update_task_status(total_articles=total_to_process)

        saved_total = 0
        for idx, (feed_cfg, item) in enumerate(pending_entries, start=1):
            f_name = feed_cfg["name"]
            f_url = feed_cfg["url"]
            cat_name = feed_cfg["category"]
            art_title = str(item.get("title") or "Kein Titel").strip()
            art_url = str(item.get("link") or "").strip()
            art_summary = str(item.get("summary") or "").strip()
            art_pub = str(item.get("published") or "").strip()
            art_ts = float(item.get("timestamp") or 0.0)

            _update_task_status(
                current_feed=f_name,
                current_article=art_title,
                processed_articles=idx,
            )

            snapshot = fetch_article_snapshot(
                url=art_url,
                title=art_title,
                fallback_summary=art_summary,
            )

            offline_art = OfflineArticle(
                url=art_url,
                title=art_title,
                feed_name=f_name,
                feed_url=f_url,
                category=cat_name,
                published=art_pub,
                timestamp=art_ts if art_ts > 0.0 else time.time(),
                content_text=snapshot["content_text"],
                content_html=snapshot["content_html"],
                images_json=snapshot["images_json"],
                created_at=datetime.now(timezone.utc).isoformat(),
            )

            if storage.save_offline_article(offline_art):
                saved_total += 1
                _update_task_status(saved_articles=saved_total)

        now_iso = datetime.now(timezone.utc).isoformat()
        _update_task_status(
            is_running=False,
            current_feed="",
            current_article="",
            last_run_at=now_iso,
        )
        logger.info(
            "Offline-Archivierung abgeschlossen: %d neue Artikel gespeichert, %d veraltete (>3M) entfernt.",
            saved_total,
            cleaned_count,
        )
        return {
            "saved": saved_total,
            "cleaned": cleaned_count,
            "feeds_processed": len(offline_feeds),
        }
    except Exception as exc:
        logger.warning("Fehler im Offline-Archivierungs-Task: %s", exc)
        _update_task_status(
            is_running=False,
            current_feed="",
            current_article="",
            last_error=str(exc),
        )
        return {"saved": 0, "cleaned": 0, "feeds_processed": 0, "error": str(exc)}


def start_offline_archive_task(
    config: dict[str, Any] | None = None,
    target_feed_url: str | None = None,
) -> threading.Thread | None:
    """
    Startet die Offline-Archivierung als nicht-blockierenden Daemon-Hintergrundthread.
    Falls bereits ein Lauf aktiv ist, wird kein zweiter konkurrierender Thread gestartet.
    """
    with _TASK_LOCK:
        if _TASK_STATUS.get("is_running"):
            logger.info("Offline-Archivierungs-Task läuft bereits im Hintergrund.")
            return None
        _TASK_STATUS["is_running"] = True

    import copy
    config_snapshot = copy.deepcopy(config) if config is not None else None

    def _worker() -> None:
        run_offline_archive_for_feeds(config=config_snapshot, target_feed_url=target_feed_url)

    thread = threading.Thread(target=_worker, daemon=True, name="OfflineArchiveWorker")
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# HTML & PDF EXPORT FÜR EINZELNE ARTIKEL UND KOMPLETTE FEEDS
# ---------------------------------------------------------------------------

def generate_offline_article_html(article: OfflineArticle | dict[str, Any]) -> str:
    """
    Erzeugt eine vollständig autarke, offline-fähige HTML5-Datei (inkl. eingebetteten
    Base64-Bildern und integriertem 'Als PDF drucken / speichern'-Button) für einen einzelnen Artikel.
    """
    art = OfflineArticle.from_dict(article) if not isinstance(article, OfflineArticle) else article
    return generate_offline_feed_html(
        feed_name=art.feed_name or "Offline-Artikel",
        articles=[art],
        single_article_mode=True,
    )


def generate_offline_feed_html(
    feed_name: str,
    articles: list[OfflineArticle | dict[str, Any]],
    single_article_mode: bool = False,
) -> str:
    """
    Erzeugt eine vollständig autarke, druck- und offline-optimierte HTML5-Datei
    für alle gespeicherten Artikel eines Feeds (oder einen einzelnen Artikel)
    inklusive eingebetteter Base64-Bilder und direkter Druck-/PDF-Funktion.
    """
    parsed_articles = [
        OfflineArticle.from_dict(a) if not isinstance(a, OfflineArticle) else a
        for a in articles
    ]
    doc_title = (
        parsed_articles[0].title
        if (single_article_mode and parsed_articles)
        else f"Offline-Archiv: {feed_name} ({len(parsed_articles)} Artikel)"
    )
    export_dt = datetime.now().strftime("%d.%m.%Y, %H:%M Uhr")

    toc_html = ""
    if not single_article_mode and len(parsed_articles) > 1:
        toc_items = []
        for idx, art in enumerate(parsed_articles, start=1):
            toc_items.append(
                f'<li><a href="#art-{idx}">{html.escape(art.title)}</a> '
                f'<span class="meta-inline">({html.escape(art.published or art.created_at[:10])})</span></li>'
            )
        toc_html = (
            '<nav class="toc-box no-print-break">'
            "<h3>Inhaltsverzeichnis</h3>"
            f"<ol>{''.join(toc_items)}</ol>"
            "</nav>"
        )

    articles_blocks: list[str] = []
    for idx, art in enumerate(parsed_articles, start=1):
        date_str = art.published or (art.created_at[:19].replace("T", " ") if art.created_at else "")
        imgs = art.images
        images_html_parts: list[str] = []
        for img in imgs:
            if isinstance(img, dict):
                b64 = img.get("data_b64", "")
                mime = img.get("mime_type", "image/jpeg")
                alt = html.escape(img.get("alt") or art.title)
                src_uri = f"data:{mime};base64,{b64}" if b64 else ""
            else:
                src_uri = str(img).strip()
                alt = html.escape(art.title)
            if src_uri:
                images_html_parts.append(
                    f'<figure class="article-figure">'
                    f'<img src="{src_uri}" alt="{alt}" />'
                    f"</figure>"
                )

        paragraphs_html: list[str] = []
        raw_text = (art.content_text or "").strip()
        if raw_text:
            for block in raw_text.split("\n\n"):
                clean_block = block.strip()
                if not clean_block:
                    continue
                if clean_block.startswith("### "):
                    paragraphs_html.append(f"<h3>{html.escape(clean_block[4:])}</h3>")
                else:
                    paragraphs_html.append(f"<p>{html.escape(clean_block)}</p>")
        elif art.content_html:
            paragraphs_html.append(art.content_html)
        else:
            paragraphs_html.append("<p><em>Kein Textinhalt gespeichert.</em></p>")

        lead_img_html = images_html_parts[0] if images_html_parts else ""
        extra_imgs_html = (
            f'<div class="extra-images">{"".join(images_html_parts[1:])}</div>'
            if len(images_html_parts) > 1
            else ""
        )

        articles_blocks.append(f"""
        <section id="art-{idx}" class="offline-card">
            <div class="meta-badges">
                <span class="badge badge-cat">{html.escape(art.category or "Allgemein")}</span>
                <span class="badge badge-feed">{html.escape(art.feed_name or feed_name)}</span>
                <span class="badge badge-date">{html.escape(date_str)}</span>
            </div>
            <h2>{html.escape(art.title)}</h2>
            {lead_img_html}
            <div class="article-body">
                {''.join(paragraphs_html)}
            </div>
            {extra_imgs_html}
            <div class="source-footer">
                Original-URL: <a href="{html.escape(art.url)}" target="_blank" rel="noopener noreferrer">{html.escape(art.url)}</a>
            </div>
        </section>
        """)

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{html.escape(doc_title)}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.65;
            color: #1e293b;
            background-color: #f8fafc;
            margin: 0;
            padding: 1.5rem;
        }}
        .container {{
            max-width: 860px;
            margin: 0 auto;
        }}
        .toolbar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 0.85rem 1.25rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        .print-btn {{
            background: #2563eb;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 0.5rem 1rem;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
        }}
        .print-btn:hover {{
            background: #1d4ed8;
        }}
        .toc-box {{
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 1rem 1.5rem;
            margin-bottom: 1.5rem;
        }}
        .toc-box h3 {{
            margin-top: 0;
        }}
        .toc-box a {{
            color: #2563eb;
            text-decoration: none;
        }}
        .meta-inline {{
            color: #64748b;
            font-size: 0.85rem;
        }}
        .offline-card {{
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 1.75rem;
            margin-bottom: 1.75rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }}
        .meta-badges {{
            margin-bottom: 0.75rem;
        }}
        .badge {{
            display: inline-block;
            padding: 0.2rem 0.6rem;
            font-size: 0.78rem;
            font-weight: 600;
            border-radius: 4px;
            margin-right: 0.4rem;
        }}
        .badge-cat {{ background: #dbeafe; color: #1d4ed8; }}
        .badge-feed {{ background: #f1f5f9; color: #334155; }}
        .badge-date {{ background: #f8fafc; color: #64748b; border: 1px solid #e2e8f0; }}
        h2 {{
            margin-top: 0.2rem;
            margin-bottom: 1rem;
            color: #0f172a;
            font-size: 1.45rem;
        }}
        .article-figure img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            display: block;
            margin: 0.75rem 0 1.25rem 0;
        }}
        .extra-images {{
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            margin-top: 1rem;
        }}
        .extra-images .article-figure {{
            flex: 1 1 45%;
            margin: 0;
        }}
        .source-footer {{
            margin-top: 1.25rem;
            padding-top: 0.75rem;
            border-top: 1px solid #e2e8f0;
            font-size: 0.85rem;
            color: #64748b;
            word-break: break-all;
        }}
        .source-footer a {{ color: #2563eb; }}
        @media print {{
            body {{ background: #ffffff; padding: 0; }}
            .toolbar {{ display: none !important; }}
            .offline-card {{
                box-shadow: none;
                border: none;
                border-bottom: 2px solid #cbd5e1;
                border-radius: 0;
                padding: 1rem 0;
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="toolbar">
            <div>
                <strong>📦 {html.escape(doc_title)}</strong>
                <div style="font-size:0.82rem;color:#64748b;">Offline-Abbild · Exportiert am {export_dt}</div>
            </div>
            <button class="print-btn" onclick="window.print()">🖨️ Als PDF drucken / speichern</button>
        </div>
        {toc_html}
        {''.join(articles_blocks)}
    </div>
</body>
</html>"""


def _sanitize_pdf_text(text: str) -> str:
    """
    Bereinigt typografische Sonderzeichen (Anführungszeichen, Gedankenstriche, Euro, Punkte)
    für zuverlässiges Core-Font-Rendering (ISO-8859-1 / Latin-1) in fpdf2.
    """
    if not text:
        return ""
    replacements = {
        "„": '"',
        "“": '"',
        "”": '"',
        "‚": "'",
        "‘": "'",
        "’": "'",
        "–": "-",
        "—": "--",
        "…": "...",
        "•": "*",
        "€": "EUR",
        "→": "->",
        "←": "<-",
        "\u00a0": " ",
        "\u200b": "",
    }
    res = text
    for k, v in replacements.items():
        res = res.replace(k, v)
    return res.encode("latin-1", errors="replace").decode("latin-1")


def generate_offline_article_pdf(article: OfflineArticle | dict[str, Any]) -> bytes:
    """Erstellt ein PDF-Dokument (inkl. Text und gespeicherten Bildern) für einen einzelnen Offline-Artikel."""
    art = OfflineArticle.from_dict(article) if not isinstance(article, OfflineArticle) else article
    return generate_offline_feed_pdf(
        feed_name=art.feed_name or "Offline-Artikel",
        articles=[art],
        single_article_mode=True,
    )


def generate_offline_feed_pdf(
    feed_name: str,
    articles: list[OfflineArticle | dict[str, Any]],
    single_article_mode: bool = False,
) -> bytes:
    """
    Erstellt ein PDF-Dokument für alle gespeicherten Offline-Artikel eines Feeds
    (oder einen einzelnen Artikel) inklusive eingebetteter Bilder und Volltext.
    """
    from fpdf import FPDF
    from fpdf.enums import WrapMode

    parsed_articles = [
        OfflineArticle.from_dict(a) if not isinstance(a, OfflineArticle) else a
        for a in articles
    ]

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    if not single_article_mode:
        pdf.set_font("Helvetica", "B", 18)
        pdf.multi_cell(
            0,
            10,
            _sanitize_pdf_text(f"Offline-Archiv: {feed_name}"),
            wrapmode=WrapMode.CHAR,
        )
        pdf.set_font("Helvetica", "", 10)
        export_dt = datetime.now().strftime("%d.%m.%Y %H:%M")
        pdf.cell(
            0,
            7,
            _sanitize_pdf_text(f"Anzahl Artikel: {len(parsed_articles)} | Exportiert am: {export_dt}"),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(4)

    for idx, art in enumerate(parsed_articles):
        if idx > 0 and not single_article_mode:
            pdf.add_page()

        # Metadaten-Zeile
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(71, 85, 105)
        meta_line = f"[{art.category or 'Allgemein'}] {art.feed_name or feed_name}"
        if art.published:
            meta_line += f" | {art.published}"
        pdf.multi_cell(0, 5, _sanitize_pdf_text(meta_line), wrapmode=WrapMode.CHAR)
        pdf.ln(1)

        # Titel
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(15, 23, 42)
        pdf.multi_cell(0, 7, _sanitize_pdf_text(art.title), wrapmode=WrapMode.CHAR)
        pdf.ln(2)

        # Quelle
        if art.url and art.url != "#":
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(37, 99, 235)
            pdf.multi_cell(0, 4.5, _sanitize_pdf_text(f"Quelle: {art.url}"), wrapmode=WrapMode.CHAR)
            pdf.ln(2)

        # Gespeicherte Bilder einbetten
        for img_item in art.images[:2]:
            if isinstance(img_item, dict):
                b64_str = img_item.get("data_b64", "")
            elif isinstance(img_item, str) and "," in img_item:
                b64_str = img_item.split(",", 1)[1]
            else:
                b64_str = ""
            if not b64_str:
                continue
            try:
                img_bytes = base64.b64decode(b64_str)
                img_stream = io.BytesIO(img_bytes)
                pdf.image(img_stream, w=135)
                pdf.ln(3)
            except Exception as exc:
                logger.debug("Bild konnte nicht in PDF eingebettet werden: %s", exc)

        # Volltext
        pdf.set_font("Helvetica", "", 10.5)
        pdf.set_text_color(30, 41, 59)
        body_text = (art.content_text or "").strip()
        if not body_text and art.content_html:
            body_text = clean_html_text(art.content_html)
        if not body_text:
            body_text = "(Kein Textinhalt gespeichert)"

        for paragraph in body_text.split("\n\n"):
            clean_p = paragraph.strip()
            if not clean_p:
                continue
            if clean_p.startswith("### "):
                pdf.set_font("Helvetica", "B", 11.5)
                pdf.multi_cell(0, 6, _sanitize_pdf_text(clean_p[4:]), wrapmode=WrapMode.CHAR)
                pdf.set_font("Helvetica", "", 10.5)
            else:
                pdf.multi_cell(0, 5.5, _sanitize_pdf_text(clean_p), wrapmode=WrapMode.CHAR)
            pdf.ln(2)

    return bytes(pdf.output())
