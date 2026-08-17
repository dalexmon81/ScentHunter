"""Sabina diagnostic scraper.

This version is intended to be deployed temporarily as
scrapers/sabina/scraper.py. It keeps the normal scraper API but emits a
complete report for every discovery stage so the real failure can be located.

Use:
    /search?q=Liquid%20Brun

Or locally:
    python scraper.py "Liquid Brun" --diagnose

Optional local fixture:
    SABINA_FIXTURE_PATH="sabina html.html" python scraper.py "Liquid Brun" --diagnose
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
MAX_PAGES = 140
MAX_CANDIDATES = 60

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

NON_PRODUCT_PATH_PARTS = (
    "/content/", "/search", "/recherche", "/login", "/mon-compte",
    "/panier", "/cart", "/contact", "/faq", "/magasins",
    "/ordre-final", "/etat-de-la-commande",
)

PRICE_RE = re.compile(r"(?:€\s*)?(\d{1,4}(?:[.,]\d{1,2})?)(?:\s*€)?")


def _log(stage: str, **data):
    if not DEBUG:
        return
    payload = {"stage": stage, **data}
    print("SABINA_DIAGNOSTIC " + json.dumps(payload, ensure_ascii=False, default=str), flush=True)


def _clean(value) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


def _norm(value) -> str:
    value = unicodedata.normalize("NFKD", _clean(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().lower()


def _tokens(value) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", _norm(value)) if len(token) > 1}


def _score(query, text) -> float:
    wanted = _tokens(query)
    if not wanted:
        return 0.0
    return len(wanted & _tokens(text)) / len(wanted)


def _clean_url(raw) -> str:
    absolute = urljoin(BASE, str(raw or ""))
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
    # Diagnostic version deliberately does not assume a numeric product ID.
    return path.endswith(".html") and path.count("/") >= 3


def _price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".replace(".", ",") + " €"
    matches = list(PRICE_RE.finditer(_clean(value)))
    for match in reversed(matches):
        try:
            number = float(match.group(1).replace(",", "."))
        except ValueError:
            continue
        if 1 <= number <= 5000:
            return f"{number:.2f}".replace(".", ",") + " €"
    return None


def _container_for(anchor):
    node = anchor
    fallback = anchor.parent
    for depth in range(1, 10):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        attrs = " ".join(str(node.get(key, "")) for key in ("id", "class", "data-product-id", "data-product-name", "data-testid"))
        marker = _norm(attrs)
        if not text or len(text) > 3000:
            continue
        if node.name in {"article", "li"} or any(word in marker for word in ("product", "card", "item", "article")):
            return node, depth
    return fallback or anchor, None


def _name_from_container(container, anchor) -> str:
    selectors = (
        "[itemprop='name']", ".product-name", ".product-title", ".product_name",
        ".name", "h1", "h2", "h3", "h4",
    )
    for selector in selectors:
        try:
            nodes = container.select(selector)
        except Exception:
            nodes = []
        for node in nodes:
            value = _clean(node.get("content") or node.get_text(" ", strip=True))
            if value and not _price(value):
                return value
    for value in (anchor.get("title"), anchor.get("aria-label"), anchor.get("data-product-name"), anchor.get_text(" ", strip=True)):
        value = _clean(value)
        if value and not _price(value):
            return value
    return ""


def _price_from_container(container) -> str | None:
    for selector in ("[itemprop='price']", ".price", ".product-price", ".current-price", ".discounted-price", "meta[property='product:price:amount']"):
        try:
            nodes = container.select(selector)
        except Exception:
            nodes = []
        for node in nodes:
            value = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
            price = _price(value)
            if price:
                return price
    return _price(container.get_text(" ", strip=True))


def inspect_html(html: str, base_url: str, query: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    raw_hrefs = []
    product_hrefs = []
    rejected_hrefs = []
    rows = []
    seen = set()
    container_depths = Counter()

    for index, anchor in enumerate(soup.find_all("a", href=True), 1):
        raw = _clean(anchor.get("href"))
        raw_hrefs.append(raw)
        url = _clean_url(urljoin(base_url, raw))
        if not _is_product_url(url):
            if ".html" in url.lower() and _internal(url):
                rejected_hrefs.append({"index": index, "raw": raw, "normalized": url, "reason": "is_product_url_false"})
            continue

        product_hrefs.append(url)
        container, depth = _container_for(anchor)
        if depth is not None:
            container_depths[str(depth)] += 1
        name = _name_from_container(container, anchor)
        price = _price_from_container(container)
        slug_text = re.sub(r"[-_/]+", " ", urlsplit(url).path)
        name_score = _score(query, name)
        slug_score = _score(query, slug_text)
        context = _clean(container.get_text(" ", strip=True))
        context_score = _score(query, context)
        key = url
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "index": index,
            "url": url,
            "name": name,
            "price": price,
            "name_score": name_score,
            "slug_score": slug_score,
            "context_score": context_score,
            "container_depth": depth,
            "container_tag": getattr(container, "name", ""),
            "container_classes": container.get("class", []) if hasattr(container, "get") else [],
            "context_sample": context[:500],
        })

    rows.sort(key=lambda row: (-max(row["name_score"], row["slug_score"]), -row["context_score"], row["index"]))
    report = {
        "query": query,
        "base_url": base_url,
        "html_bytes": len((html or "").encode("utf-8", errors="ignore")),
        "anchor_count": len(raw_hrefs),
        "product_href_count": len(product_hrefs),
        "unique_product_href_count": len(set(product_hrefs)),
        "rejected_html_href_count": len(rejected_hrefs),
        "rejected_html_href_sample": rejected_hrefs[:50],
        "container_depths": dict(container_depths),
        "row_count": len(rows),
        "matching_row_count": sum(1 for row in rows if max(row["name_score"], row["slug_score"]) >= 1.0),
        "row_sample": rows[:50],
    }
    _log("fixture_inspection", **report)
    return report


def _fetch(session, url):
    try:
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        _log("fetch_error", url=url, error=f"{type(exc).__name__}: {exc}")
        return None, None
    try:
        content_type = (response.headers.get("content-type") or "").lower()
        data = {
            "url": url,
            "final_url": response.url,
            "status": response.status_code,
            "content_type": content_type,
            "bytes": len(response.content or b""),
        }
        if response.status_code != 200 or "html" not in content_type:
            _log("fetch_rejected", **data)
            return None, None
        _log("fetch_ok", **data)
        return response.url, response.text
    finally:
        response.close()


def _extract_pagination(soup, base_url):
    pages = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        url = _clean_url(urljoin(base_url, anchor.get("href")))
        if not _internal(url) or url in seen:
            continue
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        label = _norm(anchor.get_text(" ", strip=True))
        numbered = any(key in {"p", "page"} and any(value.isdigit() for value in values) for key, values in params.items())
        navigation = any(word in label for word in ("suivant", "next", "siguiente", "prochaine", "precedent"))
        if numbered or navigation:
            seen.add(url)
            pages.append(url)
    return pages


def _load_jsonld_rows
