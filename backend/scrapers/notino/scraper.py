from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.notino.fr"
SEARCH_TIMEOUT = (2.0, 8.0)
PRODUCT_TIMEOUT = (2.0, 8.0)
MAX_CANDIDATES = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

PRODUCT_RE = re.compile(
    r"https?://(?:www\.)?notino\.fr/[^\"'<>\s]+/p-\d+/?",
    re.I,
)

SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl|l)\b", re.I)
PRICE_RE = re.compile(r"(\d{1,4}(?:[.,]\d{1,2})?)\s*€", re.I)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _query_matches(name: str, query: str) -> bool:
    q = [x for x in _norm(query).split() if len(x) > 1]
    n = _norm(name)
    return bool(q) and all(x in n for x in q)


def _price(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    m = PRICE_RE.search(_clean(value))
    if not m:
        return None

    try:
        return float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _size(value: Any) -> Optional[float]:
    m = SIZE_RE.search(_clean(value))
    if not m:
        return None

    try:
        number = float(m.group(1).replace(",", "."))
        unit = m.group(2).lower()
        if unit == "cl":
            number *= 10
        elif unit == "l":
            number *= 1000
        return number
    except ValueError:
        return None


def _get(session: requests.Session, url: str, timeout) -> requests.Response:
    response = session.get(
        url,
        headers=HEADERS,
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


def _extract_urls(html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: List[str] = []

    def add(url: str):
        if not url:
            return
        if url.startswith("/"):
            url = urljoin(BASE, url)
        if not re.match(r"^https?://", url, re.I):
            return
        url = url.split("#", 1)[0].split("?", 1)[0].rstrip(".,;)")
        if "notino.fr" not in url.lower() or "/p-" not in url.lower():
            return
        if url not in found:
            found.append(url)

    for a in soup.find_all("a", href=True):
        add(a.get("href", ""))

    for url in PRODUCT_RE.findall(html or ""):
        add(url)

    return found


def _json_objects(soup: BeautifulSoup):
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        queue = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
            elif isinstance(item, dict):
                yield item
                graph = item.get("@graph")
                if isinstance(graph, list):
                    queue.extend(graph)


def _parse_product(url: str) -> Optional[Dict[str, Any]]:
    session = requests.Session()
    try:
        response = _get(session, url, PRODUCT_TIMEOUT)
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        product = {}
        for obj in _json_objects(soup):
            typ = obj.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if "Product" in types:
                product = obj
                break

        name = _clean(product.get("name"))
        if not name:
            h1 = soup.find("h1")
            name = _clean(h1.get_text(" ", strip=True) if h1 else "")
        if not name:
            title = soup.find("title")
            name = _clean(title.get_text(" ", strip=True) if title else "")

        if not name:
            return None

        brand = product.get("brand", "")
        if isinstance(brand, dict):
            brand = brand.get("name", "")

        price_num = None
        offers = product.get("offers")
        if isinstance(offers, dict):
            price_num = _price(offers.get("price"))
        elif isinstance(offers, list):
            for offer in offers:
                if isinstance(offer, dict):
                    price_num = _price(offer.get("price"))
                    if price_num is not None:
                        break

        if price_num is None:
            price_num = _price(text)

        size_ml = _size(name)

        lower = text.lower()
        unavailable = any(
            marker in lower
            for marker in (
                "rupture de stock",
                "indisponible",
                "épuisé",
                "out of stock",
                "sold out",
            )
        )

        return {
            "store": "notino",
            "shop": "Notino",
            "brand": _clean(brand),
            "name": name,
            "price": price_num,
            "price_num": price_num,
            "size_ml": size_ml,
            "url": url,
            "available": not unavailable,
            "availability": "En stock" if not unavailable else "Rupture de stock",
        }
    finally:
        session.close()


def search(query: str) -> List[Dict[str, Any]]:
    """
    Notino discovery follows the same architecture as the working scrapers:
    first-party search -> product URLs -> parallel product pages.

    No Jina, Google Translate, Browserless, hard-coded perfume, or external
    search engine is used.
    """
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    try:
        search_urls = [
            f"{BASE}/search.asp?exps={quote_plus(query)}",
            f"{BASE}/search/?exps={quote_plus(query)}",
            f"{BASE}/search?exps={quote_plus(query)}",
        ]

        response = None
        last_error = None

        for search_url in search_urls:
            try:
                response = _get(session, search_url, SEARCH_TIMEOUT)
                if response is not None:
                    break
            except Exception as exc:
                last_error = exc

        if response is None:
            raise last_error or RuntimeError("Notino search failed")

        urls = _extract_urls(response.text)

        # Search result HTML can contain products in JSON/script data even when
        # anchors are not present.
        if not urls:
            urls = _extract_urls(response.text.replace("\\/", "/"))

        urls = urls[:MAX_CANDIDATES]
    finally:
        session.close()

    if not urls:
        return []

    results: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=min(6, len(urls))) as executor:
        futures = {
            executor.submit(_parse_product, url): url
            for url in urls
        }

        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception:
                item = None

            if item:
                results.append(item)

    # The search page itself determines candidates; this final filter only
    # removes unrelated products that may have been embedded in page data.
    filtered = [
        item for item in results
        if _query_matches(item.get("name", ""), query)
    ]

    filtered.sort(
        key=lambda item: (
            not bool(item.get("available")),
            item.get("price_num") is None,
            item.get("price_num") or 0,
        )
    )

    return filtered


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)
