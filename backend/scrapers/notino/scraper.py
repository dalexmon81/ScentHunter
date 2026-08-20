"""
Notino.fr scraper for ScentHunter.
Generic discovery only. No product-specific seeds or prices.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = Exception
    sync_playwright = None

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = f"{BASE_URL}/search.asp?exps={{query}}"
DEFAULT_TIMEOUT_MS = int(os.getenv("NOTINO_TIMEOUT_MS", "30000"))
BROWSER_ENABLED = os.getenv("NOTINO_BROWSER", "1").lower() not in {"0", "false", "no"}
LOGGER = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

PRICE_RE = re.compile(
    r"(?<![\d.,])((?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.]\d{2})?)\s*(?:€|EUR)(?!\w)",
    re.I,
)

NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "set", "discovery set", "fragrance set",
    "perfume set", "parfum set", "coffret", "bundle", "pack", "travel set",
    "kit", "duo", "trio", "mystery box", "tester", "testeur", "sample",
    "shampoo", "shower gel", "body wash", "body lotion", "body cream",
    "body milk", "deodorant", "deo spray", "aftershave", "after shave",
    "body spray", "hair mist", "makeup", "cosmetics", "skincare",
}

PRODUCT_PATH_EXCLUSIONS = {
    "search.asp", "parfums", "parfums-homme", "parfums-femme",
    "cosmetiques", "maquillage", "cheveux", "corps", "visage",
    "promotions", "nouveaux", "marques", "panier", "checkout",
    "login", "account",
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: Any) -> str:
    text = _clean(value).lower()
    text = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿñæœ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: Any) -> set[str]:
    return {x for x in _norm(value).split() if len(x) >= 2}


def _non_perfume(value: Any) -> bool:
    tokens = _tokens(value)
    return any(set(_norm(marker).split()).issubset(tokens) for marker in NON_PERFUME_MARKERS)


def _normalise_url(href: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(BASE_URL, href)
    parsed = urlparse(href)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in {"notino.fr", "www.notino.fr"}:
        return None
    path = parsed.path.rstrip("/")
    if not path or path == "/" or path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".svg")):
        return None
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _looks_like_product_url(url: str) -> bool:
    path = urlparse(url).path.strip("/").lower()
    if not path or "search.asp" in path:
        return False
    return path.split("/", 1)[0] not in PRODUCT_PATH_EXCLUSIONS and len(path.split("/")) >= 2


def _extract_prices(text: str) -> list[str]:
    out = []
    for m in PRICE_RE.finditer(_clean(text)):
        raw = m.group(1).replace(" ", "")
        if raw.count(".") > 1:
            raw = raw.replace(".", "")
        elif "." in raw and "," not in raw:
            raw = raw.replace(".", ",")
        value = f"{raw} €"
        if value not in out:
            out.append(value)
    return out


def _query_matches(text: str, query: str) -> bool:
    wanted = _tokens(query)
    return bool(wanted) and wanted.issubset(_tokens(text))


def _candidate_container(anchor):
    node = anchor
    for _ in range(8):
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if len(text) >= 20 and _extract_prices(text):
            return node
        node = getattr(node, "parent", None)
    return anchor.parent


def _name_from_container(container, fallback):
    for selector in ("h1", "h2", "h3", "h4"):
        node = container.select_one(selector) if container else None
        if node:
            value = _clean(node.get_text(" ", strip=True))
            if 2 <= len(value) <= 300:
                return value
    if container:
        anchor = container.find("a", href=True)
        if anchor:
            value = _clean(anchor.get_text(" ", strip=True))
            if 2 <= len(value) <= 300:
                return value
    return fallback


def _walk_json_ld(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_ld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_ld(child)


def _parse_json_ld(soup):
    products = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except Exception:
            continue
        for obj in _walk_json_ld(data):
            typ = obj.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if any(str(x).lower() == "product" for x in types):
                products.append(obj)
    return products


def _jsonld_results(soup, query):
    results = []
    seen = set()
    for product in _parse_json_ld(soup):
        url = _normalise_url(str(product.get("url", "")))
        name = _clean(product.get("name"))
        if not url or not _looks_like_product_url(url) or not name:
            continue
        if not _query_matches(name, query) or _non_perfume(name):
            continue
        offers = product.get("offers", {})
        offers = offers if isinstance(offers, list) else [offers]
        for offer in offers:
            if not isinstance(offer, dict) or offer.get("price") is None:
                continue
            currency = _clean(offer.get("priceCurrency"))
            if currency and currency.upper() not in {"EUR", "€"}:
                continue
            price = str(offer.get("price")).replace(".", ",")
            key = (url, price)
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "store": STORE,
                "name": name,
                "price": f"{price} €",
                "url": url,
                "available": None,
                "availability": "unknown",
            })
    return results


def _availability_from_product_page(soup):
    # A real enabled purchase action is stronger than unrelated footer/recommendation text.
    for node in soup.find_all(["button", "a", "input"]):
        text = _clean(node.get("value") or node.get_text(" ", strip=True)).lower()
        disabled = node.has_attr("disabled") or str(node.get("aria-disabled", "")).lower() == "true"
        if disabled:
            continue
        if any(x in text for x in (
            "ajouter au panier", "ajouter dans le panier", "acheter", "add to cart", "buy now"
        )):
            return True, "in_stock"

    body = _norm(soup.get_text(" ", strip=True))
    negative = (
        "actuellement en rupture de stock",
        "en rupture de stock",
        "rupture de stock",
        "out of stock",
        "sold out",
    )
    positive = ("en stock", "disponible", "available", "in stock")
    if any(x in body for x in negative):
        return False, "out_of_stock"
    if any(x in body for x in positive):
        return True, "in_stock"

    # A real product page with a valid product price and no explicit
    # out-of-stock signal is treated as available. This prevents unrelated
    # footer/recommendation text such as "indisponible" from hiding the product.
    if _extract_prices(body):
        return True, "in_stock"

    return None, "unknown"


def _product_page_result(url, fallback_name, query):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if response.status_code >= 400:
            return None
    except requests.RequestException:
        return None

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        structured = _jsonld_results(soup, query)
        availability, availability_name = _availability_from_product_page(soup)

        if structured:
            # Override stale/ambiguous JSON-LD availability with the actual purchase state.
            item = structured[0]
            item["available"] = availability
            item["availability"] = availability_name
            return item

        h1 = soup.find("h1")
        name = _clean(h1.get_text(" ", strip=True)) if h1 else _clean(fallback_name)
        if not name or not _query_matches(name, query) or _non_perfume(name):
            return None
        prices = _extract_prices(_clean(soup.get_text(" ", strip=True)))
        if not prices:
            return None
        return {
            "store": STORE,
            "name": name,
            "price": prices[0],
            "url": _normalise_url(response.url) or url,
            "available": availability,
            "availability": availability_name,
        }
    finally:
        response.close()


def _candidate_product_urls(html, query):
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        url = _normalise_url(anchor.get("href", ""))
        if not url or not _looks_like_product_url(url) or url in seen:
            continue
        context = _clean(anchor.get_text(" ", strip=True))
        node = anchor
        for _ in range(10):
            if node is None:
                break
            text = _clean(node.get_text(" ", strip=True))
            if _query_matches(text, query):
                context = text
                break
            node = getattr(node, "parent", None)
        if _query_matches(f"{context} {url}", query):
            seen.add(url)
            candidates.append((url, context))
    return candidates[:30]


def _parse_html(html, query):
    soup = BeautifulSoup(html, "html.parser")
    results = _jsonld_results(soup, query)
    seen = {x["url"] for x in results}

    for anchor in soup.find_all("a", href=True):
        url = _normalise_url(anchor.get("href", ""))
        if not url or url in seen or not _looks_like_product_url(url):
            continue
        container = _candidate_container(anchor)
        if not container:
            continue
        text = _clean(container.get_text(" ", strip=True))
        if len(text) > 2500:
            continue
        name = _name_from_container(container, _clean(query))
        if not _query_matches(name, query) or _non_perfume(name):
            continue
        prices = _extract_prices(text)
        if not prices:
            continue
        results.append({
            "store": STORE,
            "name": name,
            "price": prices[0],
            "url": url,
            "available": None,
            "availability": "unknown",
        })
        seen.add(url)
        if len(results) >= 50:
            break
    return results


def _deduplicate(items):
    out, seen = [], set()
    for item in items:
        key = (_clean(item.get("url")), _clean(item.get("price")))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _search_requests(query):
    try:
        response = requests.get(
            SEARCH_URL.format(query=quote_plus(query)),
            headers=HEADERS, timeout=20, allow_redirects=True
        )
        if response.status_code >= 400:
            return []
        html = response.text
    except requests.RequestException:
        return []

    results = _deduplicate(_parse_html(html, query))
    if results:
        return results

    results = []
    for url, context in _candidate_product_urls(html, query):
        item = _product_page_result(url, context, query)
        if item:
            results.append(item)
    return _deduplicate(results)


def _search_playwright(query):
    if sync_playwright is None:
        return []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="fr-FR",
                extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
                viewport={"width": 1365, "height": 900},
            )
            page = context.new_page()
            page.goto(
                SEARCH_URL.format(query=quote_plus(query)),
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )
            try:
                page.wait_for_load_state("networkidle", timeout=min(DEFAULT_TIMEOUT_MS, 15000))
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1200)
            html = page.content()
            browser.close()
    except Exception as exc:
        LOGGER.warning("Notino browser error: %s", exc)
        return []

    results = _deduplicate(_parse_html(html, query))
    if results:
        return results

    return _deduplicate([
        item for url, context in _candidate_product_urls(html, query)
        for item in [_product_page_result(url, context, query)]
        if item
    ])


def search(query: str):
    query = _clean(query)
    if not query:
        return []

    if BROWSER_ENABLED:
        results = _search_playwright(query)
        if results:
            return results

    return _search_requests(query)


def scrape(query):
    return search(query)
