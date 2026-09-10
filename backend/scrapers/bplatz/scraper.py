import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
import unicodedata
from urllib.parse import urlparse

import requests

from scrapers.common.discovery import discover_shopify_product_urls

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


def _anchor_contexts(anchor, absolute):
    texts = [
        anchor.get("title") or "",
        anchor.get("aria-label") or "",
        anchor.get_text(" ", strip=True) or "",
        urlparse(absolute).path.replace("/products/", " ").replace("-", " "),
    ]

    card = anchor
    for _ in range(6):
        if not card.parent:
            break
        card = card.parent
        candidate = card.get_text(" ", strip=True)
        if candidate:
            texts.append(candidate)
    return texts


def _predictive_search_worker(search_query):
    # One independent session per worker avoids sharing a requests.Session
    # across concurrent threads.
    worker_session = requests.Session()
    try:
        return discover_shopify_product_urls(
            worker_session,
            base_url=BASE,
            request_query=search_query,
            match_query=CURRENT_QUERY,
            query_matcher=query_matches,
            headers=HEADERS,
            timeout=TIMEOUT,
            limit=20,
            suggest_limit=20,
            search_json_limit=12,
            search_paths=("/search",),
            anchor_context_builder=_anchor_contexts,
        )
    finally:
        worker_session.close()


def _product_json_worker(url):
    # One independent session per worker avoids sharing a requests.Session
    # across concurrent threads.
    worker_session = requests.Session()
    try:
        return product_json(worker_session, url)
    finally:
        worker_session.close()


CURRENT_QUERY = ""


def candidate_urls(session, query):
    searches = [query]
    normalized = norm(query)
    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )
    if compact and compact != normalized:
        searches.append(compact)

    for token in normalized.split():
        if len(token) >= 3 and token not in searches:
            searches.append(token)

    urls = []
    seen = set()
    global CURRENT_QUERY
    CURRENT_QUERY = query

    # All independent predictive requests run concurrently. This restores
    # the fast discovery path: a slow token must not delay the exact query.
    with ThreadPoolExecutor(max_workers=len(searches)) as executor:
        predictive_results = list(
            executor.map(_predictive_search_worker, searches)
        )

    for discovered_urls in predictive_results:
        for absolute in discovered_urls:
            path = urlparse(absolute).path.rstrip("/")
            if "/products/" not in path or path in seen:
                continue

            seen.add(path)
            urls.append(absolute)

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

        # Product JSON requests are independent, so fetch them concurrently.
        # Keep the original URL order when building the final result list.
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(urls)))) as executor:
            product_data = list(executor.map(_product_json_worker, urls))
        for url, data in zip(urls, product_data):
            item = product_from_json(data, url)
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
