from fastapi import APIRouter
import json
import re
import time
from urllib.parse import urljoin, urlparse

import requests

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

router = APIRouter()

BASE = "https://bplatz.de"
LOCALIZED_BASE = "https://it.bplatz.de"

SEARCH_TIMEOUT = (3.0, 10.0)
PRODUCT_TIMEOUT = (3.0, 10.0)
PREDICTIVE_LIMIT = 50

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

PAGE_HEADERS = {
    **HEADERS,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

GENERIC_QUERY_TERMS = {
    "perfume", "parfum", "profumo", "fragrance",
    "eau", "de", "edt", "edp", "for", "him", "her",
    "men", "woman", "women", "man",
}


def norm(value):
    value = str(value or "").lower()
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def query_matches(title, query):
    title_tokens = set(norm(title).split())
    query_tokens = [
        token for token in norm(query).split()
        if token not in GENERIC_QUERY_TERMS
    ]
    return all(token in title_tokens for token in query_tokens)


def contains_non_perfume_marker(title):
    n = norm(title)
    markers = (
        "gift card", "giftcard", "candela", "candle",
        "diffusore", "diffuser", "home fragrance",
        "room spray", "body lotion", "body cream",
        "shower gel", "shampoo", "conditioner",
        "deodorant", "deo spray", "after shave",
        "aftershave", "soap", "savon", "hand cream",
        "hair", "capelli",
    )
    return any(marker in n for marker in markers)


def absolute_url(value):
    if not value:
        return ""
    value = str(value)
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return urljoin(BASE + "/", value)


def product_js_url(product_url):
    parsed = urlparse(product_url)
    path = parsed.path.rstrip("/")
    if path.endswith(".js"):
        return product_url
    return BASE + path + ".js"


def safe_price(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # Shopify product.js normally exposes cents.
    return number / 100.0 if number >= 100 else number


def get(url, params=None, headers=None, timeout=None):
    started = time.monotonic()
    try:
        response = requests.get(
            url,
            params=params,
            headers=headers or HEADERS,
            timeout=timeout or SEARCH_TIMEOUT,
            allow_redirects=True,
        )
        return response, round(time.monotonic() - started, 3), None
    except Exception as exc:
        return None, round(time.monotonic() - started, 3), (
            f"{type(exc).__name__}: {exc}"
        )


def target_info(title, url=""):
    n = norm(f"{title} {url}")
    targets = []
    if "kobra" in n:
        targets.append("KOBRA")
    if "reina" in n:
        targets.append("REINA")
    return targets


def discover_predictive(query):
    endpoint = BASE + "/search/suggest.json"
    params = {
        "q": query,
        "resources[type]": "product",
        "resources[limit]": str(PREDICTIVE_LIMIT),
        "resources[options][unavailable_products]": "show",
    }

    response, elapsed, error = get(
        endpoint, params=params, headers=HEADERS, timeout=SEARCH_TIMEOUT
    )

    report = {
        "endpoint": endpoint,
        "params": params,
        "elapsed": elapsed,
        "http_status": response.status_code if response else None,
        "final_url": str(response.url) if response else None,
        "error": error,
        "raw_product_count": 0,
        "products": [],
        "targets": {},
    }

    if error or response is None or response.status_code != 200:
        if response is not None:
            report["body_preview"] = response.text[:2000]
        return report

    try:
        payload = response.json()
    except Exception as exc:
        report["error"] = f"JSON decode error: {type(exc).__name__}: {exc}"
        report["body_preview"] = response.text[:3000]
        return report

    products = (
        payload.get("resources", {})
        .get("results", {})
        .get("products", [])
    )

    if not isinstance(products, list):
        report["error"] = "Unexpected resources.results.products type"
        return report

    report["raw_product_count"] = len(products)

    for index, item in enumerate(products, 1):
        title = str(item.get("title") or "").strip()
        url = absolute_url(item.get("url") or "")
        handle = str(item.get("handle") or "").strip()

        if not url and handle:
            url = BASE + "/products/" + handle.strip("/")

        matches = query_matches(title, query)
        marker = contains_non_perfume_marker(title)
        targets = target_info(title, url)

        product = {
            "index": index,
            "title": title,
            "url": url,
            "handle": handle,
            "query_matches": matches,
            "non_perfume_marker": marker,
            "targets": targets,
            "raw_keys": sorted(item.keys()),
        }

        report["products"].append(product)

        for target in targets:
            report["targets"].setdefault(target.lower(), []).append(product)

    return report


def inspect_product(product, query):
    title = product.get("title", "")
    url = product.get("url", "")
    js_url = product_js_url(url) if url else ""

    result = {
        "candidate_title": title,
        "candidate_url": url,
        "js_url": js_url,
        "candidate_query_matches": product.get("query_matches"),
        "candidate_non_perfume_marker": product.get("non_perfume_marker"),
        "targets": product.get("targets", []),
        "http_status": None,
        "elapsed": None,
        "error": None,
        "json_ok": False,
        "json_title": None,
        "json_query_matches": None,
        "json_non_perfume_marker": None,
        "variants_count": 0,
        "variants": [],
        "priced_variants": [],
        "available_priced_variants": [],
        "decision": "REJECT",
        "reason": "",
    }

    if not url:
        result["reason"] = "NO_PRODUCT_URL"
        return result

    response, elapsed, error = get(
        js_url,
        headers=HEADERS,
        timeout=PRODUCT_TIMEOUT,
    )

    result["elapsed"] = elapsed

    if error:
        result["error"] = error
        result["reason"] = "PRODUCT_JS_REQUEST_ERROR"
        return result

    result["http_status"] = response.status_code

    if response.status_code != 200:
        result["reason"] = f"PRODUCT_JS_HTTP_{response.status_code}"
        result["body_preview"] = response.text[:1500]
        return result

    try:
        data = response.json()
    except Exception as exc:
        result["error"] = f"JSON decode error: {type(exc).__name__}: {exc}"
        result["reason"] = "PRODUCT_JS_INVALID_JSON"
        result["body_preview"] = response.text[:1500]
        return result

    result["json_ok"] = True
    json_title = str(data.get("title") or "").strip()
    result["json_title"] = json_title
    result["json_query_matches"] = query_matches(json_title, query)
    result["json_non_perfume_marker"] = contains_non_perfume_marker(json_title)

    variants = data.get("variants") or []
    if not isinstance(variants, list):
        variants = []

    result["variants_count"] = len(variants)

    for variant in variants:
        raw_price = variant.get("price")
        price = safe_price(raw_price)
        available = variant.get("available")

        item = {
            "id": variant.get("id"),
            "title": str(variant.get("title") or "").strip(),
            "raw_price": raw_price,
            "price": price,
            "available": available,
        }
        result["variants"].append(item)

        if price is not None and price > 0:
            result["priced_variants"].append(item)
            if available is not False:
                result["available_priced_variants"].append(item)

    if not result["json_query_matches"]:
        result["reason"] = "PRODUCT_JSON_TITLE_QUERY_MISMATCH"
        return result

    if result["json_non_perfume_marker"]:
        result["reason"] = "NON_PERFUME_MARKER"
        return result

    if not result["priced_variants"]:
        result["reason"] = "NO_VALID_PRICED_VARIANT"
        return result

    result["decision"] = "ACCEPT"
    result["reason"] = "VALID_PRODUCT"
    return result


def _context_snippets(text, needle, radius=500, max_matches=5):
    text = str(text or "")
    needle = str(needle or "")
    if not needle:
        return []

    lowered = text.lower()
    target = needle.lower()
    snippets = []
    start = 0

    while len(snippets) < max_matches:
        position = lowered.find(target, start)
        if position < 0:
            break

        left = max(0, position - radius)
        right = min(len(text), position + len(needle) + radius)

        snippets.append({
            "position": position,
            "text": text[left:right],
        })

        start = position + len(needle)

    return snippets


def _extract_product_paths_near_target(text, target):
    snippets = _context_snippets(text, target, radius=1800, max_matches=10)
    results = []

    patterns = [
        r'https?://[^"\']+/products/[^"\']+',
        r'//[^"\']+/products/[^"\']+',
        r'["\']((?:\\?/)+products\\?/[^"\']+)["\']',
        r'["\']((?:/|\\/)products(?:/|\\/)[^"\']+)["\']',
        r'["\']([^"\']*rasasi[^"\']*(?:kobra|reina)[^"\']*)["\']',
    ]

    for snippet in snippets:
        local = snippet["text"]

        for pattern in patterns:
            for match in re.finditer(pattern, local, flags=re.IGNORECASE):
                value = match.group(1) if match.lastindex else match.group(0)
                value = value.replace("\\/", "/")
                results.append({
                    "target": target,
                    "value": value[:1000],
                    "context_position": snippet["position"],
                })

    # Deduplicate while preserving order.
    seen = set()
    unique = []
    for item in results:
        key = item["value"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique[:30]


def inspect_search_page(query):
    url = LOCALIZED_BASE + "/search"
    response, elapsed, error = get(
        url,
        params={"q": query},
        headers=PAGE_HEADERS,
        timeout=SEARCH_TIMEOUT,
    )

    report = {
        "url": url,
        "elapsed": elapsed,
        "http_status": response.status_code if response else None,
        "final_url": str(response.url) if response else None,
        "error": error,
        "html_length": len(response.text) if response else 0,
        "products": [],
        "targets": {},
        "raw_target_diagnostics": {},
    }

    if error or response is None or response.status_code != 200:
        if response is not None:
            report["body_preview"] = response.text[:2000]
        return report

    html = response.text

    # Diagnostic only: inspect the raw HTML for the two missing products.
    # This deliberately does not change production discovery behavior.
    for target in ("Kobra", "Reina"):
        report["raw_target_diagnostics"][target.lower()] = {
            "literal_occurrences": len(
                re.findall(re.escape(target), html, flags=re.IGNORECASE)
            ),
            "contexts": _context_snippets(
                html, target, radius=700, max_matches=5
            ),
            "product_paths_near_target": _extract_product_paths_near_target(
                html, target
            ),
        }

    # Inspect JSON/script containers because Shopify themes often embed
    # product-card data there instead of ordinary <a href="/products/..."> links.
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")

        script_report = []
        for index, script in enumerate(soup.find_all("script"), 1):
            script_type = str(script.get("type") or "").strip()
            script_text = script.string or script.get_text() or ""

            if not script_text:
                continue

            hits = []
            for target in ("Kobra", "Reina"):
                if re.search(re.escape(target), script_text, flags=re.IGNORECASE):
                    hits.append({
                        "target": target,
                        "contexts": _context_snippets(
                            script_text, target, radius=500, max_matches=3
                        ),
                        "product_paths_near_target": _extract_product_paths_near_target(
                            script_text, target
                        ),
                    })

            if hits:
                script_report.append({
                    "index": index,
                    "type": script_type,
                    "id": str(script.get("id") or ""),
                    "length": len(script_text),
                    "hits": hits,
                })

        report["raw_target_diagnostics"]["script_containers"] = script_report

    # Keep the original simple anchor parser for comparison.
    if BeautifulSoup is None:
        report["error"] = "beautifulsoup4_not_installed"
        return report

    soup = BeautifulSoup(html, "html.parser")
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if "/products/" not in href:
            continue

        absolute = absolute_url(href)
        parsed = urlparse(absolute)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        if clean_url in seen:
            continue
        seen.add(clean_url)

        text = " ".join(anchor.stripped_strings).strip()

        if not text:
            image = anchor.find("img")
            if image:
                text = (
                    image.get("alt")
                    or image.get("title")
                    or ""
                ).strip()

        targets = target_info(text, clean_url)

        product = {
            "title_or_anchor_text": text,
            "url": clean_url,
            "targets": targets,
        }

        report["products"].append(product)

        for target in targets:
            report["targets"].setdefault(target.lower(), []).append(product)

    return report


@router.get("/diagnose-bplatz")
def diagnose_bplatz(q: str = "Hawas"):
    query = str(q or "").strip()

    if not query:
        return {
            "ok": False,
            "error": "empty_query",
        }

    started = time.monotonic()

    predictive = discover_predictive(query)
    page = inspect_search_page(query)

    # Only predictive candidates that the production scraper would pass
    # before requesting the product .js endpoint.
    candidates = [
        item for item in predictive["products"]
        if item.get("query_matches")
        and not item.get("non_perfume_marker")
    ]

    product_results = []

    # Sequential on purpose: this is a diagnostic, not production scraping.
    for candidate in candidates:
        product_results.append(inspect_product(candidate, query))

    final = [
        item for item in product_results
        if item.get("decision") == "ACCEPT"
    ]

    targets = {}

    for target in ("kobra", "reina"):
        predictive_hits = predictive["targets"].get(target, [])
        page_hits = page["targets"].get(target, [])
        product_hits = [
            item for item in product_results
            if target.upper() in item.get("targets", [])
        ]

        targets[target] = {
            "in_predictive_search": bool(predictive_hits),
            "predictive_hits": predictive_hits,
            "in_localized_search_html": bool(page_hits),
            "localized_search_hits": page_hits,
            "reached_product_js": bool(product_hits),
            "product_js_results": product_hits,
        }

    return {
        "ok": True,
        "diagnostic": "bplatz",
        "query": query,
        "elapsed": round(time.monotonic() - started, 3),
        "summary": {
            "predictive_raw_count": predictive["raw_product_count"],
            "localized_search_html_count": len(page["products"]),
            "pre_product_candidates": len(candidates),
            "product_js_inspected": len(product_results),
            "final_accepted": len(final),
        },
        "predictive_search": predictive,
        "localized_search_page": page,
        "product_stage": product_results,
        "final_accepted": final,
        "targets": targets,
    }
