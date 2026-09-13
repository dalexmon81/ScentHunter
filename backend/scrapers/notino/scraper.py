from __future__ import annotations

import json
import logging
import re
import time
import requests
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.notino.fr"
SEARCH_TIMEOUT = (2.0, 8.0)
PRODUCT_TIMEOUT = (2.0, 8.0)
MAX_CANDIDATES = 12
NOTINO_PROXY_URL = os.getenv("NOTINO_PROXY_URL", "").strip()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "DNT": "1",
}

def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.cookies.update({"hl": "fr", "country": "FR"})
    if NOTINO_PROXY_URL:
        s.proxies.update({
            "http": NOTINO_PROXY_URL,
            "https": NOTINO_PROXY_URL,
        })
    return s

def _http_get(url: str, timeout=(3, 12)) -> requests.Response:
    last_exc = None
    session = _build_session()
    try:
        for i in range(3):
            try:
                r = session.get(
                    url,
                    timeout=timeout,
                    allow_redirects=True,
                    headers={**HEADERS, "Referer": "https://www.notino.fr/"},
                )
                if r.status_code in (403, 429):
                    raise requests.HTTPError(f"{r.status_code} blocked: {url}", response=r)
                r.raise_for_status()
                return r
            except Exception as exc:
                last_exc = exc
                time.sleep(0.6 * (i + 1))
    finally:
        session.close()
    raise last_exc if last_exc else RuntimeError("http_get_failed")

PRODUCT_RE = re.compile(
    r"https?://(?:www\.)?notino\.fr/[^\"'<>\s]+/p-\d+/?",
    re.I,
)

SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl|l)\b", re.I)
PRICE_RE = re.compile(r"(\d{1,4}(?:[.,]\d{1,2})?)\s*€", re.I)

logger = logging.getLogger(__name__)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _query_matches(name: str, query: str) -> bool:
    """
    Fuzzy-ish matcher:
    - query <=2 token: almeno 1 match
    - query >2 token: almeno 50% token match
    """
    q_tokens = [x for x in _norm(query).split() if len(x) > 1]
    n_tokens = set(_norm(name).split())
    if not q_tokens or not n_tokens:
        return False

    matched = sum(1 for t in q_tokens if t in n_tokens)
    ratio = matched / len(q_tokens)

    return matched >= 1 if len(q_tokens) <= 2 else ratio >= 0.5


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
        low = url.lower()

        if "notino.fr" not in low:
            return

        blocked = ("/search", "/blog", "/about", "/kontakt", "/cart", "/panier")
        if any(x in low for x in blocked):
            return

        path = urlparse(url).path.strip("/")
        if len(path.split("/")) < 2:
            return

        if url not in found:
            found.append(url)

    for a in soup.find_all("a", href=True):
        add(a.get("href", ""))

    # fallback regex scan
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
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    try:
        logger.info("notino proxy enabled=%s", bool(NOTINO_PROXY_URL))
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
            logger.warning("notino blocked (403) query=%r err=%r", query, last_error)
            return []

        urls = _extract_urls(response.text)

        if not urls:
            urls = _extract_urls(response.text.replace("\\/", "/"))

        urls = urls[:MAX_CANDIDATES]
        logger.info("notino: query=%r candidates=%d", query, len(urls))
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

    logger.info("notino: query=%r parsed=%d", query, len(results))

    filtered = [
        item for item in results
        if _query_matches(item.get("name", ""), query)
    ]

    # fallback anti-empty
    if not filtered:
        logger.info("notino: query=%r filter-empty -> fallback to parsed", query)
        filtered = results[:]

    filtered.sort(
        key=lambda item: (
            not bool(item.get("available")),
            item.get("price_num") is None,
            item.get("price_num") or 0,
        )
    )

    logger.info("notino: query=%r final=%d", query, len(filtered))
    return filtered


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)
    
def diagnose(query: str) -> Dict[str, Any]:
    query = _clean(query)
    report: Dict[str, Any] = {
        "query": query,
        "search_urls": [],
        "candidates_count": 0,
        "candidates": [],
        "parsed_count": 0,
        "filtered_count": 0,
        "results": [],
        "errors": [],
    }

    if not query:
        report["errors"].append("empty_query")
        return report

    session = requests.Session()
    try:
        search_urls = [
            f"{BASE}/search.asp?exps={quote_plus(query)}",
            f"{BASE}/search/?exps={quote_plus(query)}",
            f"{BASE}/search?exps={quote_plus(query)}",
        ]
        report["search_urls"] = search_urls

        response = None
        last_error = None
        for u in search_urls:
            try:
                response = _get(session, u, SEARCH_TIMEOUT)
                if response is not None:
                    break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                report["errors"].append(f"search_url_failed {u} -> {last_error}")

        if response is None:
            msg = str(last_error or "search_failed")
            if "403" in msg:
                report["blocked"] = True
                report["block_reason"] = "http_403_forbidden"
            report["errors"].append(msg)
            return report

        urls = _extract_urls(response.text)
        if not urls:
            urls = _extract_urls(response.text.replace("\\/", "/"))

        urls = urls[:MAX_CANDIDATES]
        report["candidates"] = urls
        report["candidates_count"] = len(urls)
    finally:
        session.close()

    parsed: List[Dict[str, Any]] = []
    for u in report["candidates"]:
        try:
            item = _parse_product(u)
            if item:
                parsed.append(item)
        except Exception as exc:
            report["errors"].append(f"parse_failed {u} -> {type(exc).__name__}: {exc}")

    report["parsed_count"] = len(parsed)

    filtered = [x for x in parsed if _query_matches(x.get("name", ""), query)]
    report["filtered_count"] = len(filtered)

    if not filtered:
        filtered = parsed[:]  # fallback anti-empty

    filtered.sort(
        key=lambda item: (
            not bool(item.get("available")),
            item.get("price_num") is None,
            item.get("price_num") or 0,
        )
    )

    report["results"] = filtered[:20]
    return report    
