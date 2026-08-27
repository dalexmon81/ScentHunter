import json
import re
import time
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://bplatz.de"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1",
    "Accept": "application/json,text/html,application/xhtml+xml",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
TIMEOUT = 20
RETRIES = 3
RETRY_SLEEP = 0.6

NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "discovery set", "fragrance set", "perfume set",
    "parfum set", "coffret", "bundle", "pack", "travel set", "kit", "duo",
    "trio", "mystery box", "tester", "testeur", "sample", "shampoo",
    "shower gel", "body lotion", "body cream", "deodorant", "deo spray",
    "aftershave", "after shave", "makeup", "skin care", "skincare", "cosmetics",
    "cosmetici", "set",
}


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def contains_non_perfume_marker(name):
    text = norm(name)
    tokens = set(text.split())
    for marker in NON_PERFUME_MARKERS:
        marker_tokens = set(norm(marker).split())
        if marker_tokens and marker_tokens.issubset(tokens):
            return True
    return False


def query_matches(name, query):
    if contains_non_perfume_marker(name):
        return False
    ignored = {"eau", "de", "parfum", "perfume", "edp", "edt", "extrait", "spray", "ml", "for", "by"}
    query_tokens = [token for token in norm(query).split() if token not in ignored]
    name_tokens = set(norm(name).split())
    return bool(query_tokens) and all(token in name_tokens for token in query_tokens)


def money(value):
    if value in (None, ""):
        return ""
    try:
        return f"{float(str(value).replace(',', '.')):.2f}".replace(".", ",") + " €"
    except (ValueError, TypeError):
        return ""


def _request_json(session, url, **kwargs):
    for attempt in range(RETRIES):
        try:
            response = session.get(url, **kwargs)
            if response.ok:
                return response
        except requests.RequestException:
            pass
        if attempt + 1 < RETRIES:
            time.sleep(RETRY_SLEEP)
    return None


def _request_html(session, url, **kwargs):
    for attempt in range(RETRIES):
        try:
            response = session.get(url, **kwargs)
            if response.ok:
                return response
        except requests.RequestException:
            pass
        if attempt + 1 < RETRIES:
            time.sleep(RETRY_SLEEP)
    return None


def predictive_products(session, query):
    endpoint = BASE + "/search/suggest.json"
    params = {
        "q": query,
        "resources[type]": "product",
        "resources[limit]": "20",
        "resources[options][unavailable_products]": "show",
    }
    response = _request_json(session, endpoint, params=params, headers=HEADERS, timeout=TIMEOUT)
    if not response:
        return []
    try:
        data = response.json()
        return (((data or {}).get("resources") or {}).get("results") or {}).get("products") or []
    except (ValueError, TypeError):
        return []


def product_json(session, url):
    clean = url.split("?")[0].rstrip("/")
    response = _request_json(session, clean + ".js", headers=HEADERS, timeout=TIMEOUT)
    if not response:
        return None
    try:
        return response.json()
    except (ValueError, TypeError):
        return None


def product_from_json(data, url):
    if not isinstance(data, dict):
        return None
    title = data.get("title") or ""
    if contains_non_perfume_marker(title):
        return None

    variants = data.get("variants") or []
    available = [variant for variant in variants if variant.get("available") is True]
    is_available = bool(available)
    prices = []
    for variant in available:
        price = variant.get("price")
        try:
            price = float(price)
            if price >= 100:
                price /= 100
            prices.append(price)
        except (ValueError, TypeError):
            continue

    return {
        "store": "Bplatz",
        "name": title,
        "price": f"{min(prices):.2f}".replace(".", ",") + " €" if is_available and prices else "",
        "url": url,
        "available": is_available,
    }


def _anchor_candidate(anchor, query):
    href = anchor.get("href") or ""
    absolute = urljoin(BASE, href).split("?")[0]
    path = urlparse(absolute).path.rstrip("/")
    if not path or "/products/" not in path:
        return None

    texts = [
        anchor.get("title") or "",
        anchor.get("aria-label") or "",
        anchor.get_text(" ", strip=True) or "",
        path.replace("/products/", " ").replace("-", " "),
    ]

    card = anchor
    for _ in range(6):
        if not card.parent:
            break
        card = card.parent
        candidate = card.get_text(" ", strip=True)
        if candidate:
            texts.append(candidate)

    if not any(query_matches(text, query) for text in texts):
        return None
    return absolute


def search_html_urls(session, query):
    url = BASE + "/search?q=" + quote_plus(query) + "&type=product"
    response = _request_html(session, url, headers=HEADERS, timeout=TIMEOUT)
    if not response:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    urls = []
    seen = set()
    for anchor in soup.select('a[href*="/products/"]'):
        absolute = _anchor_candidate(anchor, query)
        if not absolute:
            continue
        path = urlparse(absolute).path.rstrip("/")
        if path in seen:
            continue
        seen.add(path)
        urls.append(absolute)
    return urls


def candidate_urls(session, query):
    searches = [query]
    normalized = norm(query)
    compact = re.sub(r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)", "", normalized)
    if compact and compact != normalized:
        searches.append(compact)

    for token in normalized.split():
        if len(token) >= 3 and token not in searches:
            searches.append(token)

    urls = []
    seen = set()

    for search_query in searches:
        for product in predictive_products(session, search_query):
            product_title = product.get("title") or product.get("name") or ""
            if not query_matches(product_title, query):
                continue
            product_url = product.get("url")
            if not product_url:
                continue
            absolute = urljoin(BASE, product_url).split("?")[0]
            path = urlparse(absolute).path.rstrip("/")
            if "/products/" not in path or path in seen:
                continue
            seen.add(path)
            urls.append(absolute)

    # Always run the normal search page as a second independent discovery
    # channel. A temporary predictive-search failure must never hide products.
    for url in search_html_urls(session, query):
        if url not in urls:
            urls.append(url)

    return urls


def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    session = requests.Session()
    results = []
    seen = set()

    try:
        urls = candidate_urls(session, query)
        for url in urls:
            item = product_from_json(product_json(session, url), url)
            if not item or not query_matches(item["name"], query):
                continue
            key = urlparse(item["url"]).path.rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
        return results
    finally:
        session.close()


if __name__ == "__main__":
    for query in ("9 PM", "Rayhaan Aquatica", "Turathi Blue"):
        print("\nQUERY:", query)
        for result in search(query):
            print(result)
