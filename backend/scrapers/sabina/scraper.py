"""Syntax-safe diagnostic Sabina scraper for ScentHunter.

Temporary diagnostic version. It keeps the public API used by main.py:
    search(query), scrape(query), search_sabina(query)

It emits SABINA_DIAGNOSTIC JSON logs for every stage.
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import sys
import unicodedata
from collections import Counter, deque
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 8
MAX_PAGES = 80
MAX_CANDIDATES = 48
MAX_RESULTS = 12
DEBUG = os.getenv("SABINA_DEBUG", "1") != "0"
FIXTURE_PATH = os.getenv("SABINA_FIXTURE_PATH", "").strip()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
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


def _log(stage: str, **data) -> None:
    if DEBUG:
        print(
            "SABINA_DIAGNOSTIC " + json.dumps(
                {"stage": stage, **data},
                ensure_ascii=False,
                default=str,
            ),
            flush=True,
        )


def _clean(value) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


def _norm(value) -> str:
    value = unicodedata.normalize("NFKD", _clean(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().lower()


def _tokens(value) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", _norm(value))
        if len(token) > 1
    }


def _score(query, value) -> float:
    wanted = _tokens(query)
    if not wanted:
        return 0.0
    return len(wanted & _tokens(value)) / len(wanted)


def _clean_url(raw_url) -> str:
    absolute = urljoin(BASE, str(raw_url or ""))
    parsed = urlsplit(absolute)
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            parsed.query,
            "",
        )
    )


def _internal(url: str) -> bool:
    try:
        return urlsplit(url).netloc.lower() in {"sabina.com", "www.sabina.com"}
    except Exception:
        return False


def _is_product_url(url: str) -> bool:
    if not _internal(url):
        return False
    path = urlsplit(url).path.lower()
    if not path.startswith("/fr/"):
        return False
    if any(part in path for part in NON_PRODUCT_PATH_PARTS):
        return False
    return path.endswith(".html") and path.count("/") >= 3


def _price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".replace(".", ",") + " €"

    matches = list(PRICE_RE.finditer(_clean(value)))
    for match in reversed(matches):
        try:
            amount = float(match.group(1).replace(",", "."))
        except ValueError:
            continue
        if 1 <= amount <= 5000:
            return f"{amount:.2f}".replace(".", ",") + " €"
    return None


def _query_wants_non_fragrance(query: str) -> bool:
    wanted = _tokens(query)
    return any(_tokens(value).issubset(wanted) for value in NON_FRAGRANCE)


def _valid_product_name(name: str, query: str) -> bool:
    wanted = _tokens(query)
    actual = _tokens(name)
    if not wanted or not wanted.issubset(actual):
        return False
    if _query_wants_non_fragrance(query):
        return True
    normalized = _norm(name)
    return not any(_norm(value) in normalized for value in NON_FRAGRANCE)


def _fetch(session: requests.Session, url: str):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        _log("fetch_error", url=url, error=f"{type(exc).__name__}: {exc}")
        return None, None

    try:
        content_type = (response.headers.get("content-type") or "").lower()
        payload = {
            "url": url,
            "final_url": response.url,
            "status": response.status_code,
            "content_type": content_type,
            "bytes": len(response.content or b""),
        }
        if response.status_code != 200 or "html" not in content_type:
            _log("fetch_rejected", **payload)
            return None, None
        _log("fetch_ok", **payload)
        return response.url, response.text
    finally:
        response.close()


def _product_container(anchor):
    node = anchor
    fallback = anchor.parent
    for depth in range(1, 10):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if not text or len(text) > 3000:
            continue
        attrs = " ".join(
            str(node.get(key, ""))
            for key in (
                "id",
                "class",
                "data-product-id",
                "data-product-name",
                "data-testid",
            )
        )
        marker = _norm(attrs)
        if node.name in {"article", "li"} or any(
            word in marker for word in ("product", "card", "item", "article")
        ):
            return node, depth
    return fallback or anchor, None


def _name_from_container(container, anchor) -> str:
    for selector in (
        "[itemprop='name']",
        ".product-name",
        ".product-title",
        ".product_name",
        ".name",
        "h1",
        "h2",
        "h3",
        "h4",
    ):
        for node in container.select(selector):
            value = _clean(node.get("content") or node.get_text(" ", strip=True))
            if value and _price(value) is None:
                return value

    for value in (
        anchor.get("title"),
        anchor.get("aria-label"),
        anchor.get("data-product-name"),
        anchor.get_text(" ", strip=True),
    ):
        value = _clean(value)
        if value and _price(value) is None:
            return value
    return ""


def _price_from_container(container):
    for selector in (
        "[itemprop='price']",
        ".price",
        ".product-price",
        ".current-price",
        ".discounted-price",
        "meta[property='product:price:amount']",
    ):
        for node in container.select(selector):
            value = (
                node.get("content")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )
            price = _price(value)
            if price:
                return price
    return _price(container.get_text(" ", strip=True))


def _extract_listing_rows(html: str, base_url: str, query: str):
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    seen = set()
    raw_anchor_count = 0
    html_product_like_count = 0
    rejected_product_like = []
    depths = Counter()

    for index, anchor in enumerate(soup.find_all("a", href=True), 1):
        raw_anchor_count += 1
        raw_url = _clean(anchor.get("href"))
        url = _clean_url(urljoin(base_url, raw_url))
        if ".html" in url.lower() and _internal(url):
            html_product_like_count += 1
        if not _is_product_url(url):
            if ".html" in url.lower() and _internal(url):
                rejected_product_like.append(
                    {
                        "index": index,
                        "raw_url": raw_url,
                        "normalized_url": url,
                    }
                )
            continue

        container, depth = _product_container(anchor)
        if depth is not None:
            depths[str(depth)] += 1
        name = _name_from_container(container, anchor)
        price = _price_from_container(container)
        context = _clean(container.get_text(" ", strip=True))
        slug = re.sub(r"[-_/]+", " ", urlsplit(url).path)
        row = {
            "index": index,
            "url": url,
            "name": name,
            "price": price,
            "name_score": _score(query, name),
            "slug_score": _score(query, slug),
            "context_score": _score(query, context),
            "container_tag": getattr(container, "name", ""),
            "container_depth": depth,
            "context_sample": context[:500],
        }
        if url not in seen:
            seen.add(url)
            rows.append(row)

    rows.sort(
        key=lambda row: (
            -max(row["name_score"], row["slug_score"]),
            -row["context_score"],
            row["index"],
        )
    )
    diagnostic = {
        "anchor_count": raw_anchor_count,
        "html_product_like_count": html_product_like_count,
        "rejected_product_like_count": len(rejected_product_like),
        "rejected_product_like_sample": rejected_product_like[:30],
        "unique_product_rows": len(rows),
        "exact_identity_matches"
