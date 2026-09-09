import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
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

LAST_TRACE = {}
_TRACE_LOCK = Lock()

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


def predictive_products(session, query, trace=None, stage="predictive"):
    endpoint = BASE + "/search/suggest.json"
    params = {
        "q": query,
        "resources[type]": "product",
        "resources[limit]": "20",
        "resources[options][unavailable_products]": "show",
    }
    started = time.monotonic()
    response = _request_json(session, endpoint, params=params, headers=HEADERS, timeout=TIMEOUT)
    if trace is not None:
        trace.append({"stage": stage, "query": query, "seconds": round(time.monotonic() - started, 4), "ok": bool(response)})
    if not response:
        return []
    try:
        data = response.json()
        return (((data or {}).get("resources") or {}).get("results") or {}).get("products") or []
    except (ValueError, TypeError):
        return []


def product_json(session, url, trace=None):
    clean = url.split("?")[0].rstrip("/")
    started = time.monotonic()
    response = _request_json(session, clean + ".js", headers=HEADERS, timeout=TIMEOUT)
    if trace is not None:
        trace.append({"stage": "product_json", "url": clean + ".js", "seconds": round(time.monotonic() - started, 4), "ok": bool(response)})
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


def _predictive_search_worker(search_query):
    worker_session = requests.Session()
    try:
        trace = []
        started = time.monotonic()
        products = predictive_products(worker_session, search_query, trace=trace, stage="predictive_fallback")
        return products, round(time.monotonic() - started, 4), trace
    finally:
        worker_session.close()


def _product_json_worker(url):
    worker_session = requests.Session()
    try:
        trace = []
        started = time.monotonic()
        data = product_json(worker_session, url, trace=trace)
        return data, round(time.monotonic() - started, 4), trace
    finally:
        worker_session.close()


def candidate_urls(session, query):
    searches = [query]
    normalized = norm(query)
    compact = re.sub(r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)", "", normalized)
    if compact and compact != normalized:
        searches.append(compact)

    for token in normalized.split():
        if len(token) >= 3 and token not in searches:
            searches.append(token)

    def collect(products, urls, seen):
        for product in products:
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

    urls = []
    seen = set()

    # First try the exact user query alone. This is the fast path and avoids
    # adding concurrent requests when the primary predictive search already
    # returns usable products.
    primary_trace = []
    primary_started = time.monotonic()
    primary = predictive_products(session, searches[0], trace=primary_trace, stage="predictive_primary")
    primary_seconds = round(time.monotonic() - primary_started, 4)
    collect(primary, urls, seen)
    if urls:
        return urls, {"primary_seconds": primary_seconds, "fallback_seconds": 0.0, "html_seconds": 0.0, "trace": primary_trace, "discovery_path": "primary_predictive"}

    # Only if the exact query produced no usable URLs, try the normalized
    # variants concurrently. Keep deterministic search order when collecting.
    fallback_searches = searches[1:]
    fallback_seconds = 0.0
    trace = list(primary_trace)
    if fallback_searches:
        fallback_started = time.monotonic()
        with ThreadPoolExecutor(max_workers=len(fallback_searches)) as executor:
            predictive_results = list(executor.map(_predictive_search_worker, fallback_searches))
        fallback_seconds = round(time.monotonic() - fallback_started, 4)
        for products, _elapsed, worker_trace in predictive_results:
            trace.extend(worker_trace)
            collect(products, urls, seen)

    html_seconds = 0.0
    if not urls:
        html_started = time.monotonic()
        for url in search_html_urls(session, query):
            if url not in urls:
                urls.append(url)
        html_seconds = round(time.monotonic() - html_started, 4)
        discovery_path = "html_fallback"
    else:
        discovery_path = "fallback_predictive"

    return urls, {"primary_seconds": primary_seconds, "fallback_seconds": fallback_seconds, "html_seconds": html_seconds, "trace": trace, "discovery_path": discovery_path}


def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    session = requests.Session()
    results = []
    seen = set()

    try:
        search_started = time.monotonic()
        candidate_result = candidate_urls(session, query)
        if isinstance(candidate_result, tuple):
            urls, discovery_trace = candidate_result
        else:
            urls, discovery_trace = candidate_result, {}
        discovery_seconds = round(time.monotonic() - search_started, 4)
        product_stage_started = time.monotonic()
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(urls)))) as executor:
            product_data = list(executor.map(_product_json_worker, urls)) if urls else []
        product_stage_seconds = round(time.monotonic() - product_stage_started, 4)
        product_trace = []
        normalized_product_data = []
        for entry in product_data:
            data, _elapsed, worker_trace = entry
            normalized_product_data.append(data)
            product_trace.extend(worker_trace)
        product_data = normalized_product_data
        trace_payload = {
            "query": query,
            "discovery_seconds": discovery_seconds,
            "discovery": discovery_trace,
            "product_json_stage_seconds": product_stage_seconds,
            "product_json": product_trace,
            "total_search_seconds": round(time.monotonic() - search_started, 4),
            "url_count": len(urls),
        }
        with _TRACE_LOCK:
            global LAST_TRACE
            LAST_TRACE = trace_payload
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
