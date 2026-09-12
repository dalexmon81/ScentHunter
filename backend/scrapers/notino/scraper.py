from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.notino.fr"
JINA_URL = "https://r.jina.ai/"
TIMEOUT = 25

log = logging.getLogger("scenthunter.notino")
if not log.handlers:
    logging.basicConfig(level=logging.INFO)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

PRODUCT_RE = re.compile(r"https?://(?:www\.)?notino\.fr/[^ \n\]\)\"<>]+/p-\d+/?", re.I)
REL_PRODUCT_RE = re.compile(r"(/[^ \n\]\)\"<>]+/p-\d+/?)(?:[?#][^ \n\]\)\"<>]*)?", re.I)


def _jina_get(target_url: str) -> requests.Response:
    url = JINA_URL + target_url
    headers = {
        **HEADERS,
        "X-Engine": "browser",
        "X-Respond-With": "markdown",
        "X-Base": "true",
        "X-No-Cache": "true",
    }
    log.info("NOTINO JINA GET %s", target_url)
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    log.info("NOTINO JINA status=%s bytes=%s final=%s",
             r.status_code, len(r.content), r.url)
    r.raise_for_status()
    return r


def _extract_product_urls(text: str) -> List[str]:
    found: List[str] = []

    for m in PRODUCT_RE.findall(text or ""):
        u = m.rstrip(".,;")
        if u not in found:
            found.append(u)

    for m in REL_PRODUCT_RE.findall(text or ""):
        u = urljoin(BASE_URL, m).rstrip(".,;")
        if u not in found:
            found.append(u)

    return found


def _first(text: str, patterns: List[str]) -> Optional[str]:
    for pattern in patterns:
        m = re.search(pattern, text or "", re.I | re.S)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _parse_price(text: str) -> Optional[float]:
    value = _first(text, [
        r"(\d{1,4}(?:[.,]\d{1,2})?)\s*€",
        r"€\s*(\d{1,4}(?:[.,]\d{1,2})?)",
    ])
    if not value:
        return None
    try:
        return float(value.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _parse_product(url: str) -> Optional[Dict[str, Any]]:
    try:
        r = _jina_get(url)
        text = r.text
    except Exception as exc:
        log.exception("NOTINO PRODUCT FAILED %s: %s", url, exc)
        return None

    name = _first(text, [
        r"^#\s*(.+)$",
        r"\*\*(?:Product|Produit)\*\*\s*[:\-]\s*(.+)",
    ])

    if not name:
        title = _first(text, [r"Title:\s*(.+)"])
        name = title

    if not name:
        # Fallback from URL slug
        slug = url.rstrip("/").split("/")[-2] if "/p-" in url else ""
        name = slug.replace("-", " ").strip().title() or "Notino product"

    price_num = _parse_price(text)

    size = _first(text, [
        r"\b(\d{2,4})\s*ml\b",
        r"\b(\d+(?:[.,]\d+)?)\s*ml\b",
    ])
    size_ml = None
    if size:
        try:
            size_ml = float(size.replace(",", "."))
        except ValueError:
            pass

    lower = text.lower()
    unavailable_words = [
        "rupture de stock",
        "indisponible",
        "épuisé",
        "out of stock",
        "sold out",
    ]
    available = not any(x in lower for x in unavailable_words)

    return {
        "store": "notino",
        "shop": "Notino",
        "brand": "French Avenue" if "french avenue" in lower else "",
        "name": name,
        "price": price_num,
        "price_num": price_num,
        "size_ml": size_ml,
        "url": url,
        "available": available,
        "availability": "En stock" if available else "Rupture de stock",
    }


def search(query: str) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []

    search_url = f"{BASE_URL}/search.asp?exps={quote_plus(q)}"
    log.info("NOTINO SEARCH START query=%r url=%s", q, search_url)

    # First attempt: Jina's browser-backed Reader, which is specifically
    # designed to fetch/render third-party pages server-side.
    response = _jina_get(search_url)
    text = response.text

    urls = _extract_product_urls(text)
    log.info("NOTINO SEARCH extracted %s product URLs", len(urls))

    # If the rendered search page does not expose product URLs, use Jina Search
    # as a second discovery route. This is still external retrieval, not a
    # fabricated Notino endpoint.
    if not urls:
        search_proxy = JINA_URL + "https://www.google.com/search?q=" + quote_plus(
            f"site:notino.fr {q} Notino"
        )
        log.info("NOTINO DISCOVERY FALLBACK %s", search_proxy)
        rr = requests.get(
            search_proxy,
            headers={**HEADERS, "X-Engine": "browser"},
            timeout=TIMEOUT,
        )
        log.info("NOTINO DISCOVERY status=%s bytes=%s", rr.status_code, len(rr.content))
        rr.raise_for_status()
        urls = _extract_product_urls(rr.text)

    # Keep this deliberately small: first prove retrieval works.
    urls = urls[:8]

    if not urls:
        log.warning("NOTINO SEARCH: zero product URLs for query=%r", q)
        return []

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(4, len(urls))) as pool:
        futures = {pool.submit(_parse_product, u): u for u in urls}
        for future in as_completed(futures):
            item = future.result()
            if item:
                results.append(item)

    results.sort(key=lambda x: (
        not bool(x.get("available")),
        x.get("price_num") is None,
        x.get("price_num") or 0,
    ))

    log.info("NOTINO SEARCH DONE query=%r results=%s", q, len(results))
    return results


if __name__ == "__main__":
    print(json.dumps(search("Liquid Brun"), ensure_ascii=False, indent=2))
