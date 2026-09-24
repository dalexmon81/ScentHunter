from fastapi import APIRouter, Query
import concurrent.futures
import json
import re
import time
from urllib.parse import quote, urljoin

import requests

router = APIRouter()

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"}
TOKEN_RE = re.compile(r"\b(liquid|brun)\b", re.I)

def _get(url, timeout=(1.5, 5.0), headers=None):
    t = time.monotonic()
    try:
        r = requests.get(url, headers=headers or HEADERS, timeout=timeout, allow_redirects=True)
        return {
            "ok": True,
            "status": r.status_code,
            "url": r.url,
            "elapsed_sec": round(time.monotonic()-t, 3),
            "bytes": len(r.content),
            "text": r.text,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "elapsed_sec": round(time.monotonic()-t, 3),
            "bytes": 0,
            "text": "",
            "error": f"{type(e).__name__}: {e}",
        }

def _compact(s, n=500):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:n]

@router.get("/diagnose-sabina-catalog")
def diagnose_sabina_precise(q: str = Query("Liquid Brun")):
    base = "https://www.sabina.com"
    urls = [
        f"{base}/it/ricerca_old?s={quote(q)}",
        f"{base}/it/ricerca?search_query={quote(q)}",
        f"{base}/it/ricerca_old?search_query={quote(q)}",
    ]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        pages = list(ex.map(lambda u: _get(u), urls))

    probes = []
    for p in pages:
        text = p["text"]
        low = text.lower()
        hits = {}
        for marker in [q, "liquid brun", "liquid-brun", "34982", "720100",
                       "french avenue", "profumi-da-uomo", "/it/profumi-da-uomo/"]:
            i = low.find(marker.lower())
            hits[marker] = None if i < 0 else {
                "offset": i,
                "context": _compact(text[max(0, i-350):i+700], 1050)
            }

        # Inspect links around product-like references.
        links = []
        for m in re.finditer(r'href=["\']([^"\']+)["\']', text, re.I):
            href = m.group(1)
            if any(x in href.lower() for x in ["34982", "liquid", "brun", "profumi-da-uomo"]):
                links.append(urljoin(p["url"], href))
        probes.append({
            "url": p["url"],
            "status": p["status"],
            "elapsed_sec": p["elapsed_sec"],
            "bytes": p["bytes"],
            "error": p["error"],
            "markers": hits,
            "matching_links": list(dict.fromkeys(links))[:50],
        })

    return {
        "diagnostic": True,
        "store": "Sabina",
        "query": q,
        "elapsed_sec": round(time.monotonic()-started, 3),
        "purpose": "read-only inspection of real search responses; no production search() and no product-specific rule",
        "probes": probes,
    }

@router.get("/diagnose-deloox-catalog")
def diagnose_deloox_precise(q: str = Query("Liquid Brun")):
    urls = [
        "https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html",
        "https://www.deloox.com/en/category/1121322/french-avenue-fragrances.html",
        "https://www.deloox.com/en/category/1132834/liquid-brun.html",
    ]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        pages = list(ex.map(lambda u: _get(u, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}), urls))

    out = []
    for p in pages:
        text = p["text"]
        low = text.lower()
        # Capture product-card-like anchors whose nearby text contains a query token.
        matches = []
        for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S):
            href, inner = m.group(1), m.group(2)
            visible = re.sub(r"<[^>]+>", " ", inner)
            visible = _compact(visible, 800)
            if TOKEN_RE.search(visible):
                matches.append({
                    "url": urljoin(p["url"], href),
                    "text": visible,
                })
        # Also locate raw occurrences in page text, independent of href.
        raw_contexts = []
        for m in list(TOKEN_RE.finditer(text))[:20]:
            raw_contexts.append(_compact(text[max(0, m.start()-300):m.end()+500], 900))
        out.append({
            "url": p["url"],
            "status": p["status"],
            "elapsed_sec": p["elapsed_sec"],
            "bytes": p["bytes"],
            "error": p["error"],
            "card_token_hits": matches[:50],
            "raw_token_contexts": raw_contexts,
        })

    return {
        "diagnostic": True,
        "store": "Deloox",
        "query": q,
        "elapsed_sec": round(time.monotonic()-started, 3),
        "purpose": "read-only inspection of category/card text; no URL-token discovery and no production search()",
        "pages": out,
    }

@router.get("/diagnose-sabina-runtime")
def diagnose_sabina_runtime(q: str = Query("9 PM")):
    """Read-only diagnostic of the exact deployed Sabina scraper discovery."""
    started = time.monotonic()
    try:
        from scrapers.sabina import scraper
        import requests

        session = requests.Session()
        try:
            urls = scraper.discover_product_urls(session, q)
        finally:
            session.close()

        return {
            "diagnostic": True,
            "store": "Sabina",
            "query": q,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "purpose": "read-only execution of the deployed Sabina discovery function",
            "scraper_module": getattr(scraper, "__file__", None),
            "discovery": {
                "ok": True,
                "count": len(urls),
                "urls": urls,
            },
        }
    except Exception as exc:
        return {
            "diagnostic": True,
            "store": "Sabina",
            "query": q,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "purpose": "read-only execution of the deployed Sabina discovery function",
            "discovery": {
                "ok": False,
                "count": 0,
                "urls": [],
                "error": f"{type(exc).__name__}: {exc}",
            },
        }


@router.get("/diagnose-sabina-html")
def diagnose_sabina_html(q: str = Query("9 PM")):
    """Inspect the raw Sabina search response without using production discovery."""
    started = time.monotonic()
    base = "https://www.sabina.com"
    url = f"{base}/es/buscar?search_query={quote(q)}"
    page = _get(url, headers=HEADERS)
    text = page["text"]
    low = text.lower()

    query_hits = []
    needle = (q or "").lower()
    if needle:
        for m in list(re.finditer(re.escape(needle), low))[:20]:
            query_hits.append(_compact(text[max(0, m.start()-300):m.end()+500], 900))

    product_links = []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', text, re.I):
        href = m.group(1)
        if re.search(r'/es/[^/]+/\d+-[^/]+\.html$', href, re.I):
            product_links.append(urljoin(page["url"], href))

    soup_text = re.sub(r'<[^>]+>', ' ', text)
    heading = None
    warning = None
    mh = re.search(r'<h1\b[^>]*>(.*?)</h1>', text, re.I | re.S)
    mw = re.search(r'<p\b[^>]*class=["\'][^"\']*alert[^"\']*["\'][^>]*>(.*?)</p>', text, re.I | re.S)
    if mh:
        heading = _compact(re.sub(r'<[^>]+>', ' ', mh.group(1)), 500)
    if mw:
        warning = _compact(re.sub(r'<[^>]+>', ' ', mw.group(1)), 500)

    return {
        "diagnostic": True,
        "store": "Sabina",
        "query": q,
        "elapsed_sec": round(time.monotonic() - started, 3),
        "purpose": "raw HTML inspection only; no production discovery/search and no product-specific rule",
        "page": {
            "url": page["url"],
            "status": page["status"],
            "bytes": page["bytes"],
            "error": page["error"],
            "heading": heading,
            "warning": warning,
            "literal_query_occurrences": len(list(re.finditer(re.escape(needle), low))) if needle else 0,
            "query_contexts": query_hits,
            "product_like_links": list(dict.fromkeys(product_links))[:100],
        },
    }
