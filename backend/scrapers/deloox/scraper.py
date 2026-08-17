"""Deloox scraper replacement for ScentHunter.

Discovery is intentionally conservative and generic:
query -> matching category links -> category page -> product URLs -> parser.
No product-specific URL or ID is hardcoded.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "deloox"
BASE_URL = "https://www.deloox.com"
HTTP_TIMEOUT = 8
MAX_CANDIDATES = 24
MAX_CATEGORY_LINKS = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9,it;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
    "spray", "ml", "for", "by", "pour", "the", "and", "men",
    "man", "women", "woman", "herren", "damen",
}

NON_PERFUME_WORDS = {
    "gift set", "set regalo", "coffret", "bundle", "deodorant",
    "deo spray", "shower gel", "body lotion", "after shave",
    "aftershave", "travel set", "discovery set", "kit",
}


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value) -> str:
    value = clean(value).lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def query_tokens(query: str) -> set[str]:
    return {
        token
        for token in norm(query).split()
        if token and token not in IGNORED_QUERY_WORDS and len(token) > 1
    }


def tokens_match(text: str, query: str) -> bool:
    wanted = query_tokens(query)
    return bool(wanted) and wanted.issubset(set(norm(text).split()))


def absolute_url(raw_url: str) -> str | None:
    raw_url = clean(raw_url).replace("\\/", "/")
    if not raw_url or raw_url.startswith(("javascript:", "mailto:", "#")):
        return None

    url = urljoin(BASE_URL, raw_url).split("#", 1)[0].split("?", 1)[0]
    parsed = urlparse(url)

    if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
        return None
    return url


def is_category_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return "/category/" in path and path.endswith(".html")


def is_product_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return "/product/" in path or "/products/" in path


def category_slug(url: str) -> str:
    slug = urlparse(url).path.rsplit("/", 1)[-1]
    return re.sub(r"\.html$", "", slug, flags=re.I).replace("-", " ")


def category_score(url: str, label: str, query: str) -> int:
    haystack = f"{category_slug(url)} {label}"
    return sum(token in norm(haystack).split() for token in query_tokens(query))


def product_slug_score(url: str, query: str) -> int:
    return sum(
        token in norm(urlparse(url).path).split()
        for token in query_tokens(query)
    )


def candidate_queries(query: str) -> list[str]:
    raw = clean(query)
    words = [word for word in norm(raw).split() if word]
    meaningful = [word for word in words if word not in IGNORED_QUERY_WORDS]

    values = [raw, " ".join(meaningful)]
    if len(meaningful) >= 2:
        values.extend([
            " ".join(meaningful[:2]),
            " ".join(meaningful[-2:]),
        ])
    values.extend(sorted(set(meaningful), key=lambda x: (-len(x), x)))

    result = []
    seen = set()
    for value in values:
        key = norm(value)
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result[:8]


def extract_category_links(html: str, query: str) -> list[tuple[int, str, str]]:
    """Return relevant category links as (score, url, label)."""
    soup = BeautifulSoup(html or "", "html.parser")
    found: dict[str, tuple[int, str, str]] = {}

    def add(raw_url, label=""):
        url = absolute_url(raw_url)
        if not url or not is_category_url(url):
            return

        score = category_score(url, label, query)
        if score <= 0:
            return

        previous = found.get(url)
        candidate = (score, url, clean(label))
        if previous is None or score > previous[0]:
            found[url] = candidate

    for anchor in soup.find_all("a", href=True):
        label = " ".join(
            clean(value)
            for value in (
                anchor.get_text(" ", strip=True),
                anchor.get("aria-label", ""),
                anchor.get("title", ""),
                anchor.get("data-category-name", ""),
            )
            if clean(value)
        )
        add(anchor.get("href"), label)

    raw = (html or "").replace("\\\\/", "/").replace("\\/", "/")
    patterns = [
        r"https?://(?:www\.)?deloox\.com/(?:[a-z]{2}/)?category/\d+/[^\"'<>\s]+\.html",
        r"[\"']((?:/)?(?:[a-z]{2}/)?category/\d+/[^\"']+\.html)[\"']",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, raw, re.I):
            url = match.group(0)
            if match.groups():
                url = match.group(1)
            start = max(0, match.start() - 700)
            end = min(len(raw), match.end() + 700)
            local = raw[start:end]
            add(url, local)

    return sorted(found.values(), key=lambda item: (-item[0], len(item[1])))


def extract_product_urls(html: str, query: str, strict: bool = True) -> list[str]:
    """Extract product URLs; use the URL slug as the primary signal."""
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: dict[str, int] = {}

    def add(raw_url, context=""):
        url = absolute_url(raw_url)
        if not url or not is_product_url(url):
            return

        score = max(
            product_slug_score(url, query),
            sum(token in norm(context).split() for token in query_tokens(query)),
        )

        if strict and score < len(query_tokens(query)):
            return

        candidates[url] = max(score, candidates.get(url, 0))

    for anchor in soup.find_all("a", href=True):
        context = " ".join(
            clean(value)
            for value in (
                anchor.get_text(" ", strip=True),
                anchor.get("aria-label", ""),
                anchor.get("title", ""),
                anchor.get("data-name", ""),
                anchor.get("data-product-name", ""),
            )
            if clean(value)
        )
        add(anchor.get("href"), context)

    raw = (html or "").replace("\\\\/", "/").replace("\\/", "/")
    patterns = [
        r"https?://(?:www\.)?deloox\.com/[^\"'<>\s]*/(?:product|products)/[^\"'<>\s]+",
        r"[\"']((?:/)?(?:[a-z]{2}/)?(?:product|products)/[^\"']+)[\"']",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, raw, re.I):
            url = match.group(0)
            if match.groups():
                url = match.group(1)
            local = raw[max(0, match.start() - 500):match.end() + 500]
            add(url, local)

    return [
        url
        for url, _score in sorted(
            candidates.items(),
            key=lambda item: (-item[1], len(item[0])),
        )
    ][:MAX_CANDIDATES]


def fetch(session: requests.Session, url: str):
    try:
        response = session.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT)
        return response if response.status_code < 400 else None
    except requests.RequestException:
        return None


def discover_from_category(session: requests.Session, category_url: str, query: str) -> list[str]:
    response = fetch(session, category_url)
    if response is None:
        return []

    urls = extract_product_urls(response.text, query, strict=True)
    if urls:
        return urls

    # Fallback: collect products from the category page, then let the
    # product-page parser perform the authoritative name check.
    return extract_product_urls(response.text, query, strict=False)


def discover_from_search(session: requests.Session, query: str) -> list[str]:
    routes = (
        "/en/search?query=",
        "/en/search?search=",
        "/en/search?q=",
    )
    categories: list[tuple[int, str, str]] = []
    products: list[str] = []
    seen_categories = set()
    seen_products = set()

    for candidate_query in candidate_queries(query)[:4]:
        for route in routes:
            url = BASE_URL + route + requests.utils.quote(candidate_query, safe="")
            response = fetch(session, url)
            if response is None:
                continue

            direct = extract_product_urls(response.text, query, strict=True)
            for product_url in direct:
                if product_url not in seen_products:
                    seen_products.add(product_url)
                    products.append(product_url)

            for score, category_url, label in extract_category_links(response.text, query):
                if category_url not in seen_categories:
                    seen_categories.add(category_url)
                    categories.append((score, category_url, label))

    if products:
        return products[:MAX_CANDIDATES]

    categories.sort(key=lambda item: (-item[0], len(item[1])))
    for _score, category_url, _label in categories[:MAX_CATEGORY_LINKS]:
        for product_url in discover_from_category(session, category_url, query):
            if product_url not in seen_products:
                seen_products.add(product_url)
                products.append(product_url)
            if len(products) >= MAX_CANDIDATES:
                return products

    return products


def discover_from_catalog(session: requests.Session, query: str) -> list[str]:
    roots = (
        BASE_URL + "/en/category/1025540/trending.html",
        BASE_URL + "/category/1075660/womens-perfume.html",
        BASE_URL + "/category/1075750/mens-perfume.html",
    )

    categories: list[tuple[int, str, str]] = []
    seen_categories = set()

    for root in roots:
        response = fetch(session, root)
        if response is None:
            continue
        for score, url, labe
