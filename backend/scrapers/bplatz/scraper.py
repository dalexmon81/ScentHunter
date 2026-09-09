import json
import re
import time
import threading
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

# Diagnostic tracing is opt-in and never changes normal search behavior.
_TRACE_LOCAL = threading.local()


def _trace_start(query=""):
    trace = {
        "query": query,
        "requests": [],
        "stages": [],
        "started_at": time.monotonic(),
    }
    _TRACE_LOCAL.data = trace
    return trace


def _trace_get():
    return getattr(_TRACE_LOCAL, "data", None)


def _trace_stage(name, started, **extra):
    trace = _trace_get()
    if trace is not None:
        item = {"stage": name, "elapsed_seconds": round(time.monotonic() - started, 4)}
        item.update(extra)
        trace["stages"].append(item)


def _trace_request(kind, url, started, **extra):
    trace = _trace_get()
    if trace is not None:
        item = {"kind": kind, "url": url, "elapsed_seconds": round(time.monotonic() - started, 4)}
        item.update(extra)
        trace["requests"].append(item)

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
        started = time.monotonic()
        status_code = None
        error = None
        try:
            response = session.get(url, **kwargs)
            status_code = response.status_code
            _trace_request("json", response.url if hasattr(response, "url") else url, started,
                           attempt=attempt + 1, status_code=status_code, ok=bool(response.ok))
            if response.ok:
                return response
        except requests.RequestException as exc:
            error = f"{type(exc).__name__}: {exc}"
            _trace_request("json", url, started, attempt=attempt + 1,
                           status_code=status_code, ok=False, error=error)
        if attempt + 1 < RETRIES:
            time.sleep(RETRY_SLEEP)
    return None


def _request_html(session, url, **kwargs):
    for attempt in range(RETRIES):
        started = time.monotonic()
        status_code = None
        try:
            response = session.get(url, **kwargs)
            status_code = response.status_code
            _trace_request("html", response.url if hasattr(response, "url") else url, started,
                           attempt=attempt + 1, status_code=status_code, ok=bool(response.ok))
            if response.ok:
                return response
        except requests.RequestException as exc:
            _trace_request("html", url, started, attempt=attempt + 1,
                           status_code=status_code, ok=False,
                           error=f"{type(exc).__name__}: {exc}")
        if attempt + 1 < RETRIES:
            time.sleep(RETRY_SLEEP)
    return None


def predictive_products(session, query):
    started = time.monotonic()
    endpoint = BASE + "/search/suggest.json"
    params = {
        "q": query,
        "resources[type]": "product",
        "resources[limit]": "20",
        "resources[options][unavailable_products]": "show",
    }
    response = _request_json(session, endpoint, params=params, headers=HEADERS, timeout=TIMEOUT)
    if not response:
        _trace_stage("predictive_products", started, query=query, returned_count=0, response=False)
        return []
    try:
        data = response.json()
        products = (((data or {}).get("resources") or {}).get("results") or {}).get("products") or []
        _trace_stage("predictive_products", started, query=query, returned_count=len(products), response=True)
        return products
    except (ValueError, TypeError):
        _trace_stage("predictive_products_parse", started, query=query, returned_count=0, response=True)
        return []


def product_json(session, url):
    started = time.monotonic()
    clean = url.split("?")[0].rstrip("/")
    response = _request_json(session, clean + ".js", headers=HEADERS, timeout=TIMEOUT)
    if not response:
        _trace_stage("product_json", started, url=url, response=False)
        return None
    try:
        data = response.json()
        _trace_stage("product_json", started, url=url, response=True, parsed=True)
        return data
    except (ValueError, TypeError):
        _trace_stage("product_json", started, url=url, response=True, parsed=False)
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
    started = time.monotonic()
    url = BASE + "/search?q=" + quote_plus(query) + "&type=product"
    response = _request_html(session, url, headers=HEADERS, timeout=TIMEOUT)
    if not response:
        _trace_stage("search_html_urls", started, query=query, returned_count=0, response=False)
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
    _trace_stage("search_html_urls", started, query=query, returned_count=len(urls), response=True)
    return urls


def candidate_urls(session, query):
    started = time.monotonic()
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
        stage_started = time.monotonic()
        predictive = predictive_products(session, search_query)
        _trace_stage("candidate_predictive_query", stage_started, query=search_query, returned_count=len(predictive))
        for product in predictive:
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
    html_urls = search_html_urls(session, query)
    for url in html_urls:
        if url not in urls:
            urls.append(url)

    _trace_stage("candidate_urls", started, query=query, search_variants=searches, returned_count=len(urls))
    return urls


def _search_internal(query, trace=False):
    query = str(query or "").strip()
    if not query:
        return []

    if trace:
        _trace_start(query)
    total_started = time.monotonic()
    session = requests.Session()
    results = []
    seen = set()

    try:
        t0 = time.monotonic()
        urls = candidate_urls(session, query)
        _trace_stage("candidate_discovery_total", t0, returned_count=len(urls))
        for url in urls:
            t0 = time.monotonic()
            data = product_json(session, url)
            item = product_from_json(data, url)
            accepted = bool(item and query_matches(item["name"], query))
            if not accepted:
                _trace_stage("product_candidate", t0, url=url, accepted=False)
                continue
            key = urlparse(item["url"]).path.rstrip("/")
            if key in seen:
                _trace_stage("product_candidate", t0, url=url, accepted=False, duplicate=True)
                continue
            seen.add(key)
            results.append(item)
            _trace_stage("product_candidate", t0, url=url, accepted=True)
        _trace_stage("search_total", total_started, returned_count=len(results))
        return results
    finally:
        session.close()


def search(query):
    return _search_internal(query, trace=False)


def diagnostic_search(query):
    """Run the real Bplatz search while recording every network request/stage."""
    started = time.monotonic()
    trace = _trace_start(str(query or "").strip())
    try:
        results = _search_internal(query, trace=True)
        trace["total_seconds"] = round(time.monotonic() - started, 4)
        trace.pop("started_at", None)
        return {"results": results, "trace": trace}
    except Exception as exc:
        trace["total_seconds"] = round(time.monotonic() - started, 4)
        trace.pop("started_at", None)
        trace["error"] = f"{type(exc).__name__}: {exc}"
        return {"results": [], "trace": trace}


if __name__ == "__main__":
    for query in ("9 PM", "Rayhaan Aquatica", "Turathi Blue"):
        print("\nQUERY:", query)
        for result in search(query):
            print(result)
