"""Sabina scraper for ScentHunter.

Generic flow:
category/search HTML -> product-card discovery -> product page validation -> results.
No product-, brand-, or query-specific URLs are hard-coded.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import unicodedata
from collections import deque
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 8
MAX_PAGES = 80
MAX_CANDIDATES = 48
MAX_RESULTS = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7,it;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/fr/",
}

ROOTS = (
    BASE + "/fr/7-parfums-pour-homme",
    BASE + "/fr/31-fragrances-pour-homme",
    BASE + "/fr/6-parfums-pour-femme",
    BASE + "/fr/30-fragrances-pour-femme",
    BASE + "/fr/864-parfums-arabes-pour-femmes",
    BASE + "/fr/865-parfums-arabes-pour-hommes",
    BASE + "/fr/890-parfumerie-de-niche",
    BASE + "/fr/688-parfums-de-niche-pour-femme",
    BASE + "/fr/891-perfumes-nicho-unisex",
)

SEARCH_ROUTES = (
    "/fr/recherche?controller=search&s={query}",
    "/fr/search?controller=search&s={query}",
    "/fr/search?s={query}",
)

NON_PRODUCT_PATH_PARTS = (
    "/content/", "/search", "/recherche", "/login", "/mon-compte",
    "/panier", "/cart", "/contact", "/faq", "/magasins",
    "/ordre-final", "/etat-de-la-commande",
)

NON_FRAGRANCE = (
    "body mist", "body spray", "body lotion", "body cream", "body oil",
    "body wash", "shower gel", "shower oil", "hand cream", "deodorant",
    "after shave", "aftershave", "hair mist", "hair spray", "soap",
)

PRICE_RE = re.compile(r"(?:€\s*)?(\d{1,4}(?:[.,]\d{1,2})?)(?:\s*€)?")
PRODUCT_PATH_RE = re.compile(r"^/fr/(?!content/|search|recherche|login|mon-compte|panier|cart|contact|faq|magasins).+\.html$", re.I)


def _clean(value) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


def _norm(value) -> str:
    value = unicodedata.normalize("NFKD", _clean(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().lower()


def _tokens(value) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", _norm(value)) if len(token) > 1]


def _token_set(value) -> set[str]:
    return set(_tokens(value))


def _score(query, text) -> float:
    wanted = _token_set(query)
    if not wanted:
        return 0.0
    return len(wanted & _token_set(text)) / len(wanted)


def _clean_url(url) -> str:
    absolute = urljoin(BASE, str(url or ""))
    parsed = urlsplit(absolute)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))


def _internal(url) -> bool:
    try:
        return urlsplit(url).netloc.lower() in {"sabina.com", "www.sabina.com"}
    except Exception:
        return False


def _is_product_url(url) -> bool:
    if not _internal(url):
        return False
    path = urlsplit(url).path.lower()
    if not path.startswith("/fr/"):
        return False
    if any(part in path for part in NON_PRODUCT_PATH_PARTS):
        return False
    return bool(PRODUCT_PATH_RE.match(path))


def _price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".replace(".", ",") + " €"

    text = _clean(value)
    matches = list(PRICE_RE.finditer(text))
    if not matches:
        return None

    for match in reversed(matches):
        try:
            number = float(match.group(1).replace(",", "."))
        except ValueError:
            continue
        if 1 <= number <= 5000:
            return f"{number:.2f}".replace(".", ",") + " €"
    return None


def _query_wants_non_fragrance(query) -> bool:
    wanted = _token_set(query)
    return any(_token_set(phrase).issubset(wanted) for phrase in NON_FRAGRANCE)


def _contains_non_fragrance(name) -> bool:
    normalized = _norm(name)
    return any(_norm(phrase) in normalized for phrase in NON_FRAGRANCE)


def _valid_product_name(name, query) -> bool:
    wanted = _token_set(query)
    actual = _token_set(name)
    return bool(wanted) and wanted.issubset(actual) and (
        _query_wants_non_fragrance(query) or not _contains_non_fragrance(name)
    )


def _fetch(session, url):
    try:
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        print(f"SABINA: FETCH_ERROR url={url} error={type(exc).__name__}: {exc}", flush=True)
        return None, None

    try:
        content_type = (response.headers.get("content-type") or "").lower()
        if response.status_code in {403, 429}:
            print(f"SABINA: BLOCKED status={response.status_code} url={url}", flush=True)
            return None, None
        if response.status_code != 200 or "html" not in content_type:
            return None, None
        return response.url, response.text
    finally:
        response.close()


def _card_container(anchor):
    node = anchor
    fallback = anchor.parent
    for _ in range(8):
        node = getattr(node, "parent", None)
        if node is None:
            break
        classes = " ".join(node.get("class", [])) if hasattr(node, "get") else ""
        marker = _norm(f"{getattr(node, 'name', '')} {classes} {node.get('id', '') if hasattr(node, 'get') else ''}")
        text = _clean(node.get_text(" ", strip=True))
        if not text or len(text) > 2500:
            continue
        if node.name in {"article", "li"} or any(word in marker for word in ("product", "card", "item", "thumbnail")):
            return node
    return fallback or anchor


def _card_name(container, anchor) -> str:
    selectors = (
        "[itemprop='name']", ".product-name", ".product-title", ".product_name",
        ".name", "h1", "h2", "h3", "h4",
    )
    for selector in selectors:
        element = container.select_one(selector)
        if element:
            value = _clean(element.get("content") or element.get_text(" ", strip=True))
            if value:
                return value

    for value in (anchor.get("title"), anchor.get("aria-label"), anchor.get("data-product-name")):
        value = _clean(value)
        if value:
            return value

    return _clean(anchor.get_text(" ", strip=True))


def _card_price(container):
    for selector in (
        "[itemprop='price']", ".price", ".product-price", ".current-price",
        ".discounted-price", "meta[property='product:price:amount']",
    ):
        element = container.select_one(selector)
        if element:
            value = element.get("content") or element.get("data-price") or element.get_text(" ", strip=True)
            price = _price(value)
            if price:
                return price
    return _price(container.get_text(" ", strip=True))


def _extract_cards(soup, base_url) -> list[dict]:
    rows = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        url = _clean_url(urljoin(base_url, anchor.get("href")))
        if not _is_product_url(url):
            continue

        container = _card_container(anchor)
        name = _card_name(container, anchor)
        price = _card_price(container)
        text = _clean(container.get_text(" ", strip=True))
        key = (url, name, price)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"url": url, "name": name, "price": price, "text": text})

    return rows


def _extract_jsonld_products(soup, base_url) -> list[dict]:
    rows = []

    def walk(value):
        if isinstance(value, list):
            for child in value:
                walk(child)
            return
        if not isinstance(value, dict):
            return

        typ = value.get("@type")
        is_product = typ == "Product" or (isinstance(typ, list) and "Product" in typ)
        if is_product:
            name = _clean(value.get("name"))
            raw_url = value.get("url")
            url = _clean_url(urljoin(base_url, raw_url)) if isinstance(raw_url, str) else ""
            offers = value.get("offers")
            if isinstance(offers, dict):
                price = _price(offers.get("price") or offers.get("lowPrice"))
            elif isinstance(offers, list):
                price = next((_price(item.get("price") or item.get("lowPrice")) for item in offers if isinstance(item, dict)), None)
            else:
                price = None
            if name and _is_product_url(url):
                rows.append({"url": url, "name": name, "price": price, "text": name})

        for child in value.values():
            if isinstance(child, (dict, list)):
                walk(child)

    for script in soup.find_all("script", type=lambda value: value and "ld+json" in value):
        try:
            walk(json.loads(script.get_text()))
        except Exception:
            continue
    return rows


def _extract_pagination(soup, base_url) -> list[str]:
    pages = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        url = _clean_url(urljoin(base_url, anchor.get("href")))
        if not _internal(url) or url in seen:
            continue
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        text = _norm(anchor.get_text(" ", strip=True))
        is_numbered = any(key in params and any(str(value).isdigit() for value in values) for key, values in params.items() if key in {"p", "page"})
        is_navigation = any(word in text for word in ("suivant", "next", "siguiente", "prochaine", "precedent", "precedent"))
        if is_numbered or is_navigation:
            seen.add(url)
            pages.append(url)
    return pages


def _parse_listing(html, base_url, query):
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    seen = set()

    for row in _extract_cards(soup, base_url) + _extract_jsonld_products(soup, 
