"""
Sabina diagnostic v1.

Purpose:
- Diagnose why the scraper receives zero results from Sabina.
- No product-specific names, URLs, seeds or exceptions.
- Does NOT try to return normal product results.
- Reports the exact HTTP/search-page conditions that determine whether
  discovery is possible with the current requests-based approach.
"""

import json
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.sabina.com"
SEARCH_PATH = "/es/buscar_old"
TIMEOUT = 20
VERSION = "sabina-DIAGNOSTIC-2026-08-18-FINAL"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL + "/es/",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

PRODUCT_PATH_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl)/.+?/(\d+)-[^/]+\.html$",
    re.I,
)

PRODUCT_URL_RE = re.compile(
    r"(?:https?:\\?/\\?/www\.sabina\.com)?"
    r"/(?:es|it|fr|en|de|nl)/[^\"'< >\\s]+?/"
    r"(\d+)-[^\"'< >\\s]+?\.html",
    re.I,
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def absolute(page_url, href):
    return urljoin(page_url, href).split("#", 1)[0]


def is_product_url(url):
    return bool(PRODUCT_PATH_RE.match(urlparse(url).path))


def page_snapshot(session, label, url, query):
    info = {
        "label": label,
        "requested_url": url,
    }

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except Exception as exc:
        info["request_error"] = f"{type(exc).__name__}: {exc}"
        return info

    html = response.text or ""
    soup = BeautifulSoup(html, "html.parser")

    title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    body_text = clean(soup.get_text(" ", strip=True))
    lower_html = html.lower()
    lower_text = body_text.lower()
    q = clean(query).lower()

    anchor_urls = []
    anchor_product_urls = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not href:
            continue
        absolute_url = absolute(response.url, href)
        if absolute_url in seen:
            continue
        seen.add(absolute_url)
        anchor_urls.append(absolute_url)
        if is_product_url(absolute_url):
            anchor_product_urls.append(absolute_url)

    raw_matches = []
    raw_seen = set()
    for match in PRODUCT_URL_RE.finditer(
        html.replace("\\/", "/")
    ):
        candidate = match.group(0)
        if candidate.startswith("/"):
            candidate = urljoin(response.url, candidate)
        candidate = candidate.replace("\\/", "/")
        candidate = candidate.split("#", 1)[0]
        if candidate not in raw_seen and is_product_url(candidate):
            raw_seen.add(candidate)
            raw_matches.append(candidate)

    info.update(
        {
            "status": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(html.encode("utf-8", errors="ignore")),
            "title": title,
            "query_in_html": q in lower_html if q else False,
            "query_in_visible_text": q in lower_text if q else False,
            "anchor_count": len(anchor_urls),
            "anchor_product_url_count": len(anchor_product_urls),
            "raw_product_url_count": len(raw_matches),
            "sample_anchor_product_urls": anchor_product_urls[:10],
            "sample_raw_product_urls": raw_matches[:10],
            "contains_search_results_word": any(
                token in lower_text
                for token in (
                    "resultados",
                    "results",
                    "produits",
                    "productos",
                )
            ),
            "contains_block_or_challenge": any(
                token in lower_html
                for token in (
                    "captcha",
                    "cloudflare",
                    "access denied",
                    "forbidden",
                    "verify you are human",
                    "challenge",
                )
            ),
            "html_head": clean(html[:500]),
        }
    )

    return info


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()

    diagnostics = {
        "diagnostic_version": VERSION,
        "store": "sabina",
        "query": query,
        "base_url": BASE_URL,
        "search_path": SEARCH_PATH,
        "method": "requests",
        "steps": [],
        "interpretation": {},
    }

    # Establish the first-party session first.
    diagnostics["steps"].append(
        page_snapshot(
            session,
            "homepage",
            BASE_URL + "/es/",
            query,
        )
    )

    search_urls = (
        (
            "legacy_search",
            BASE_URL + SEARCH_PATH + "?s=" + quote_plus(query),
        ),
        (
            "legacy_controller_search",
            BASE_URL + SEARCH_PATH + "?controller=search&s=" + quote_plus(query),
        ),
        (
            "modern_search_fallback",
            BASE_URL + "/es/buscar?s=" + quote_plus(query),
        ),
    )

    for label, url in search_urls:
        diagnostics["steps"].append(
            page_snapshot(session, label, url, query)
        )

    searches = [
        x for x in diagnostics["steps"]
        if x.get("label") != "homepage"
    ]

    usable = [
        x for x in searches
        if x.get("status") == 200
        and x.get("bytes", 0) > 0
    ]

    product_candidates = []
    for item in searches:
        product_candidates.extend(item.get("sample_anchor_product_urls", []))
        product_candidates.extend(item.get("sample_raw_product_urls", []))

    unique_candidates = []
    seen = set()
    for url in product_candidates:
        if url not in seen:
            seen.add(url)
            unique_candidates.append(url)

    if unique_candidates:
        diagnostics["interpretation"] = {
            "discovery": "WORKS",
            "reason": (
                "At least one search response exposes product URLs. "
                "The failure is therefore later in product extraction/validation."
            ),
            "candidate_count": len(unique_candidates),
        }
    elif usable:
        diagnostics["interpretation"] = {
            "discovery": "FAILS",
            "reason": (
                "The HTTP requests return usable pages, but no product URLs "
                "are exposed in ordinary anchors or the raw HTML. "
                "This strongly indicates that the result cards are rendered "
                "client-side or embedded in a structure not handled by the "
                "requests/HTML discovery path."
            ),
            "candidate_count": 0,
        }
    else:
        diagnostics["interpretation"] = {
            "discovery": "BLOCKED_OR_REDIRECTED",
            "reason": (
                "The scraper cannot obtain a usable search response. "
                "Inspect status, final_url, content_type, bytes and challenge "
                "fields above."
            ),
            "candidate_count": 0,
        }

    # IMPORTANT:
    # /test-store passes scraper output through the normal result pipeline.
    # The first diagnostic version used a custom shape that main.py discarded.
    # Return a normal scraper-shaped record and put the complete diagnostic
    # payload inside raw_data so the existing pipeline preserves it.
    return [
        {
            "store": "Sabina",
            "source": {
                "url": BASE_URL,
                "name": f"SABINA_DIAGNOSTIC {query}",
                "brand": "Sabina",
                "image": None,
            },
            "identity": {
                "gtin": None,
                "mpn": None,
                "sku": None,
                "store_product_id": None,
                "store_variant_id": None,
            },
            "attributes": {
                "size_ml": {"value": None, "source": "diagnostic"},
                "concentration": {"value": None, "source": "diagnostic"},
                "gender": {"value": "unknown", "source": "diagnostic"},
                "packaging_type": {"value": "product", "source": "default"},
            },
            "offer": {
                "price": 0.0,
                "currency": "EUR",
                "availability": "diagnostic",
            },
            "provenance": {
                "name": "diagnostic",
                "brand": "diagnostic",
                "price": "diagnostic",
                "availability": "diagnostic",
                "image": "diagnostic",
                "store_product_id": "diagnostic",
                "store_variant_id": "diagnostic",
                "sku": "diagnostic",
                "gtin": "diagnostic",
            },
            "raw_data": {
                "diagnostic": diagnostics,
            },
            "name": "SABINA_DIAGNOSTIC",
            "price": 0.0,
            "url": BASE_URL,
            "available": False,
        }
    ]


# Compatibilita con il loader generico di ScentHunter.
def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sabina diagnostic")
    parser.add_argument("query", help="Runtime search query")
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query)[0],
            ensure_ascii=False,
            indent=2,
        )
    )
