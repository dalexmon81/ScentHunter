#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bplatz diagnostic for ScentHunter.

PURPOSE
-------
This file DOES NOT modify the production Bplatz scraper.
It traces the complete Hawas discovery pipeline and shows exactly where
"Hawas Kobra" and "Hawas Reina" disappear.

It checks:
1. Shopify predictive search (/search/suggest.json)
2. Product links found on the visible localized search page
3. query_matches() filtering
4. Product .js endpoint status / JSON
5. Product title and variants
6. Whether a valid priced/available variant can be produced
7. Final diagnostic result set

Run:
    python bplatz_diagnostic.py

Optional:
    python bplatz_diagnostic.py "Hawas"
"""

from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse, parse_qs

import requests

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None


# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

QUERY = sys.argv[1] if len(sys.argv) > 1 else "Hawas"

# Production scraper uses bplatz.de. Keep that for the Shopify API.
BASE = "https://bplatz.de"

# User-reported page. Diagnostic only.
LOCALIZED_SEARCH_BASE = "https://it.bplatz.de"

SEARCH_TIMEOUT = (3.0, 10.0)
PRODUCT_TIMEOUT = (3.0, 10.0)

PREDICTIVE_LIMIT = 50
MAX_WORKERS = 8

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


# ---------------------------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------------------------

GENERIC_QUERY_TERMS = {
    "perfume",
    "parfum",
    "profumo",
    "fragrance",
    "eau",
    "de",
    "edt",
    "edp",
    "for",
    "him",
    "her",
    "men",
    "woman",
    "women",
    "man",
}


def norm(value: str) -> str:
    value = value or ""
    value = value.lower()
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def query_matches(title: str, query: str) -> bool:
    title_tokens = set(norm(title).split())
    query_tokens = [
        token for token in norm(query).split()
        if token not in GENERIC_QUERY_TERMS
    ]
    return all(token in title_tokens for token in query_tokens)


def contains_non_perfume_marker(title: str) -> bool:
    """
    Same broad class of exclusion used by the production scraper.
    This is intentionally diagnostic: if a target product is rejected here,
    the output will show the reason.
    """
    n = norm(title)

    markers = (
        "gift card",
        "giftcard",
        "candela",
        "candle",
        "diffusore",
        "diffuser",
        "home fragrance",
        "room spray",
        "body lotion",
        "body cream",
        "shower gel",
        "shampoo",
        "conditioner",
        "deodorant",
        "deo spray",
        "after shave",
        "aftershave",
        "soap",
        "savon",
        "hand cream",
        "hair",
        "capelli",
    )
    return any(marker in n for marker in markers)


def request_get(url: str, *, params=None, headers=None, timeout=None):
    started = time.perf_counter()
    try:
        response = requests.get(
            url,
            params=params,
            headers=headers or HEADERS,
            timeout=timeout or SEARCH_TIMEOUT,
            allow_redirects=True,
        )
        elapsed = time.perf_counter() - started
        return response, elapsed, None
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return None, elapsed, repr(exc)


def absolute_product_url(value: str) -> str:
    if not value:
        return ""
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return urljoin(BASE + "/", value)


def product_js_url(product_url: str) -> str:
    parsed = urlparse(product_url)
    path = parsed.path.rstrip("/")
    if path.endswith(".js"):
        return product_url

    if path.endswith(".json"):
        return product_url

    return BASE + path + ".js"


def extract_price(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        # Shopify .js commonly exposes prices in cents.
        return number / 100.0 if number >= 100 else number

    text = str(value).strip()
    if not text:
        return None

    text = text.replace("\xa0", " ")
    text = re.sub(r"[^\d,.\-]", "", text)

    if not text:
        return None

    # Handle 49,90 / 49.90 / 1.299,90 reasonably.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts[-1]) == 2:
            text = "".join(parts[:-1]) + "." + parts[-1]
        else:
            text = text.replace(",", "")
    else:
        # Plain Shopify cents can arrive as "4990".
        pass

    try:
        number = float(text)
    except Exception:
        return None

    return number


def variant_price(variant):
    for key in ("price", "price_min", "price_max"):
        if key in variant and variant.get(key) not in (None, ""):
            price = extract_price(variant.get(key))
            if price is not None:
                return price

    return None


def normalize_shopify_price(price):
    """
    Diagnostic display only.
    Shopify product .js normally returns price in cents.
    """
    if price is None:
        return None
    try:
        value = float(price)
    except Exception:
        return None

    if value >= 100:
        return value / 100.0
    return value


# ---------------------------------------------------------------------------
# PREDICTIVE SEARCH DIAGNOSTIC
# ---------------------------------------------------------------------------

def predictive_products(query: str):
    endpoint = BASE + "/search/suggest.json"
    params = {
        "q": query,
        "resources[type]": "product",
        "resources[limit]": str(PREDICTIVE_LIMIT),
        "resources[options][unavailable_products]": "show",
    }

    print("\n" + "=" * 90)
    print("1) SHOPIFY PREDICTIVE SEARCH")
    print("=" * 90)
    print("URL:", endpoint)
    print("params:", params)

    response, elapsed, error = request_get(
        endpoint,
        params=params,
        headers=HEADERS,
        timeout=SEARCH_TIMEOUT,
    )

    if error:
        print(f"ERROR after {elapsed:.2f}s: {error}")
        return []

    print(
        f"HTTP {response.status_code} | {elapsed:.2f}s | "
        f"final_url={response.url}"
    )

    if response.status_code != 200:
        print("BODY PREVIEW:")
        print(response.text[:2000])
        return []

    try:
        payload = response.json()
    except Exception as exc:
        print("JSON ERROR:", repr(exc))
        print("BODY PREVIEW:")
        print(response.text[:3000])
        return []

    resources = payload.get("resources", {})
    results = resources.get("results", {})
    products = results.get("products", [])

    if not isinstance(products, list):
        print("Unexpected products type:", type(products).__name__)
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:5000])
        return []

    print(f"Products returned by Shopify predictive search: {len(products)}")

    candidates = []

    for index, item in enumerate(products, 1):
        title = str(item.get("title") or "").strip()
        url = absolute_product_url(
            item.get("url")
            or item.get("handle")
            or ""
        )

        # Shopify predictive search can expose handle instead of URL.
        if url and "/products/" not in url:
            handle = item.get("handle")
            if handle:
                url = BASE + "/products/" + str(handle).strip("/") 

        matches = query_matches(title, query)
        excluded = contains_non_perfume_marker(title)

        marker = ""
        lower_title = norm(title)
        if "kobra" in lower_title:
            marker = "  <<< KOBRA"
        elif "reina" in lower_title:
            marker = "  <<< REINA"

        print(
            f"[{index:02d}] {title!r}{marker}\n"
            f"      url={url}\n"
            f"      query_matches={matches} | non_perfume_marker={excluded}"
        )

        candidates.append({
            "source": "predictive",
            "index": index,
            "title": title,
            "url": url,
            "raw": item,
            "query_matches": matches,
            "non_perfume_marker": excluded,
        })

    return candidates


# ---------------------------------------------------------------------------
# NORMAL SEARCH PAGE DIAGNOSTIC
# ---------------------------------------------------------------------------

def normal_search_page(query: str):
    url = LOCALIZED_SEARCH_BASE + "/search"
    params = {"q": query}

    print("\n" + "=" * 90)
    print("2) LOCALIZED SEARCH PAGE")
    print("=" * 90)
    print("URL:", url)
    print("params:", params)

    response, elapsed, error = request_get(
        url,
        params=params,
        headers=PAGE_HEADERS,
        timeout=SEARCH_TIMEOUT,
    )

    if error:
        print(f"ERROR after {elapsed:.2f}s: {error}")
        return []

    print(
        f"HTTP {response.status_code} | {elapsed:.2f}s | "
        f"final_url={response.url}"
    )

    if response.status_code != 200:
        print("BODY PREVIEW:")
        print(response.text[:2000])
        return []

    html = response.text
    print(f"HTML bytes/chars: {len(html)}")

    if BeautifulSoup is None:
        print("BeautifulSoup not installed; skipping HTML link extraction.")
        return []

    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    # Look for product links. This is intentionally broad because themes
    # differ and we want the diagnostic to reveal what the page actually has.
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if "/products/" not in href:
            continue

        absolute = absolute_product_url(href)
        parsed = urlparse(absolute)
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        if clean in seen:
            continue
        seen.add(clean)

        text = " ".join(anchor.stripped_strings).strip()

        # Sometimes the product title is in an image alt or nearby heading.
        if not text:
            image = anchor.find("img")
            if image:
                text = (
                    image.get("alt")
                    or image.get("title")
                    or ""
                ).strip()

        found.append({
            "url": clean,
            "anchor_text": text,
        })

    print(f"Unique /products/ links found in HTML: {len(found)}")

    if not found:
        print(
            "No product links found in server HTML. "
            "The page may be rendered client-side."
        )
        return []

    for index, item in enumerate(found, 1):
        text = item["anchor_text"]
        lower = norm(text)

        marker = ""
        if "kobra" in lower:
            marker = "  <<< KOBRA"
        elif "reina" in lower:
            marker = "  <<< REINA"

        print(
            f"[{index:02d}] text={text!r}{marker}\n"
            f"      url={item['url']}"
        )

    return found


# ---------------------------------------------------------------------------
# PRODUCT .JS DIAGNOSTIC
# ---------------------------------------------------------------------------

def inspect_product(candidate, query):
    title = candidate.get("title", "")
    url = candidate.get("url", "")

    result = {
        "candidate_title": title,
        "url": url,
        "http_status": None,
        "elapsed": None,
        "request_error": None,
        "json_ok": False,
        "json_title": None,
        "json_query_matches": None,
        "variants_count": 0,
        "variants": [],
        "valid_variants": [],
        "decision": "NOT_TESTED",
        "reason": "",
    }

    if not url:
        result["decision"] = "REJECT"
        result["reason"] = "NO_PRODUCT_URL"
        return result

    js_url = product_js_url(url)
    result["js_url"] = js_url

    response, elapsed, error = request_get(
        js_url,
        headers={
            **HEADERS,
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=PRODUCT_TIMEOUT,
    )

    result["elapsed"] = elapsed

    if error:
        result["request_error"] = error
        result["decision"] = "REJECT"
        result["reason"] = "PRODUCT_JS_REQUEST_ERROR"
        return result

    result["http_status"] = response.status_code

    if response.status_code != 200:
        result["decision"] = "REJECT"
        result["reason"] = f"PRODUCT_JS_HTTP_{response.status_code}"
        result["body_preview"] = response.text[:1000]
        return result

    try:
        product = response.json()
    except Exception as exc:
        result["decision"] = "REJECT"
        result["reason"] = "PRODUCT_JS_INVALID_JSON"
        result["body_preview"] = response.text[:1000]
        result["json_error"] = repr(exc)
        return result

    result["json_ok"] = True

    json_title = str(product.get("title") or "").strip()
    result["json_title"] = json_title
    result["json_query_matches"] = query_matches(json_title, query)

    variants = product.get("variants") or []
    if not isinstance(variants, list):
        variants = []

    result["variants_count"] = len(variants)

    for variant in variants:
        vtitle = str(variant.get("title") or "").strip()
        raw_price = variant.get("price")
        price = normalize_shopify_price(raw_price)
        available = variant.get("available")

        v = {
            "id": variant.get("id"),
            "title": vtitle,
            "raw_price": raw_price,
            "display_price": price,
            "available": available,
        }
        result["variants"].append(v)

        # Diagnostic approximation of a usable offer.
        if price is not None and price > 0:
            result["valid_variants"].append(v)

    if not result["json_query_matches"]:
        result["decision"] = "REJECT"
        result["reason"] = "PRODUCT_JSON_TITLE_QUERY_MISMATCH"
        return result

    if contains_non_perfume_marker(json_title):
        result["decision"] = "REJECT"
        result["reason"] = "NON_PERFUME_MARKER"
        return result

    if not result["valid_variants"]:
        result["decision"] = "REJECT"
        result["reason"] = "NO_VALID_PRICED_VARIANT"
        return result

    result["decision"] = "ACCEPT"
    result["reason"] = "VALID_PRODUCT_WITH_PRICED_VARIANT"
    return result


def print_product_diagnostic(result):
    title = result["candidate_title"]
    json_title = result.get("json_title") or ""
    lower = norm(title + " " + json_title)

    marker = ""
    if "kobra" in lower:
        marker = " <<< KOBRA"
    elif "reina" in lower:
        marker = " <<< REINA"

    print("\n" + "-" * 90)
    print(f"PRODUCT: {title!r}{marker}")
    print("URL:", result.get("url"))
    print("JS:", result.get("js_url"))
    print(
        "HTTP:",
        result.get("http_status"),
        "| elapsed:",
        f"{result.get('elapsed', 0):.2f}s",
        "| JSON:",
        result.get("json_ok"),
    )

    if result.get("request_error"):
        print("REQUEST ERROR:", result["request_error"])

    if result.get("json_error"):
        print("JSON ERROR:", result["json_error"])

    print("JSON title:", repr(json_title))
    print("query_matches(JSON title):", result.get("json_query_matches"))
    print("variants:", result.get("variants_count"))

    for v in result.get("variants", []):
        print(
            "  - variant:",
            repr(v.get("title")),
            "| id=",
            v.get("id"),
            "| raw_price=",
            repr(v.get("raw_price")),
            "| display_price=",
            repr(v.get("display_price")),
            "| available=",
            repr(v.get("available")),
        )

    print(
        "DECISION:",
        result.get("decision"),
        "| REASON:",
        result.get("reason"),
    )

    if result.get("body_preview"):
        print("BODY PREVIEW:", result["body_preview"])


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    started = time.perf_counter()

    print("\n" + "#" * 90)
    print("# BPLATZ DIAGNOSTIC — SCENTHUNTER")
    print("# Query:", QUERY)
    print("# This file is diagnostic only; it does NOT modify the scraper.")
    print("#" * 90)

    predictive = predictive_products(QUERY)
    normal_page = normal_search_page(QUERY)

    print("\n" + "=" * 90)
    print("3) TARGET PRESENCE SUMMARY")
    print("=" * 90)

    def find_named(items, field_names):
        hits = []
        for item in items:
            text = " ".join(
                str(item.get(name) or "")
                for name in field_names
            )
            n = norm(text)
            if any(term in n for term in ("kobra", "reina")):
                hits.append(item)
        return hits

    predictive_targets = find_named(
        predictive,
        ["title", "url"],
    )
    page_targets = find_named(
        normal_page,
        ["anchor_text", "url"],
    )

    print(
        "Predictive search contains Kobra/Reina:",
        len(predictive_targets),
    )
    for item in predictive_targets:
        print(
            "  ->",
            item.get("title") or item.get("anchor_text"),
            "|",
            item.get("url"),
        )

    print(
        "Localized search HTML contains Kobra/Reina:",
        len(page_targets),
    )
    for item in page_targets:
        print(
            "  ->",
            item.get("anchor_text"),
            "|",
            item.get("url"),
        )

    # Build product candidates from predictive search only, matching the
    # production pipeline as closely as possible.
    accepted = []
    rejected_before_product = []

    for item in predictive:
        if not item.get("query_matches"):
            rejected_before_product.append(
                (item, "QUERY_MATCHES_FALSE")
            )
            continue

        if item.get("non_perfume_marker"):
            rejected_before_product.append(
                (item, "NON_PERFUME_MARKER")
            )
            continue

        accepted.append(item)

    print("\n" + "=" * 90)
    print("4) CANDIDATE FILTERING BEFORE PRODUCT .JS")
    print("=" * 90)
    print("Predictive products:", len(predictive))
    print("Accepted into product stage:", len(accepted))
    print("Rejected before product stage:", len(rejected_before_product))

    for item, reason in rejected_before_product:
        print(
            f"REJECT {reason}:",
            item.get("title"),
            "|",
            item.get("url"),
        )

    # Inspect every predictive candidate that passes the pre-filter.
    print("\n" + "=" * 90)
    print("5) PRODUCT .JS + VARIANT DIAGNOSTIC")
    print("=" * 90)
    print(f"Inspecting {len(accepted)} candidates with {MAX_WORKERS} workers...")

    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(inspect_product, item, QUERY): item
            for item in accepted
        }

        for future in as_completed(future_map):
            item = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "candidate_title": item.get("title"),
                    "url": item.get("url"),
                    "decision": "REJECT",
                    "reason": "DIAGNOSTIC_EXCEPTION",
                    "exception": repr(exc),
                }
            results.append(result)

    results.sort(key=lambda x: norm(x.get("candidate_title", "")))

    for result in results:
        print_product_diagnostic(result)

    # Final result list approximating what should survive.
    final = [
        result for result in results
        if result.get("decision") == "ACCEPT"
    ]

    print("\n" + "=" * 90)
    print("6) FINAL DIAGNOSTIC RESULT")
    print("=" * 90)
    print("Products accepted after product/variant inspection:", len(final))

    for index, result in enumerate(final, 1):
        print(
            f"[{index:02d}]",
            result.get("json_title") or result.get("candidate_title"),
            "|",
            result.get("url"),
        )

    print("\n" + "=" * 90)
    print("7) KOBRA / REINA VERDICT")
    print("=" * 90)

    for target in ("kobra", "reina"):
        related = []

        for result in results:
            text = norm(
                " ".join(
                    str(result.get(key) or "")
                    for key in ("candidate_title", "json_title", "url")
                )
            )
            if target in text:
                related.append(result)

        # Also include pre-product rejects.
        for item, reason in rejected_before_product:
            text = norm(
                " ".join(
                    str(item.get(key) or "")
                    for key in ("title", "url")
                )
            )
            if target in text:
                related.append({
                    "candidate_title": item.get("title"),
                    "url": item.get("url"),
                    "decision": "REJECT",
                    "reason": reason,
                })

        print(f"\nTARGET: Hawas {target.title()}")

        if not related:
            print(
                "  NOT FOUND in predictive candidates. "
                "This means the loss occurs at Shopify predictive discovery "
                "or before the candidate list reaches the scraper."
            )
            if target == "kobra" and any(
                target in norm(
                    str(x.get("anchor_text") or "") + " " + str(x.get("url") or "")
                )
                for x in normal_page
            ):
                print(
                    "  IMPORTANT: Kobra IS present in the localized search HTML. "
                    "Therefore predictive search and normal search are returning "
                    "different product sets."
                )
            if target == "reina" and any(
                target in norm(
                    str(x.get("anchor_text") or "") + " " + str(x.get("url") or "")
                )
                for x in normal_page
            ):
                print(
                    "  IMPORTANT: Reina IS present in the localized search HTML. "
                    "Therefore predictive search and normal search are returning "
                    "different product sets."
                )
            continue

        for result in related:
            print(
                "  title:",
                result.get("json_title") or result.get("candidate_title"),
            )
            print("  url:", result.get("url"))
            print("  decision:", result.get("decision"))
            print("  reason:", result.get("reason"))

    print("\n" + "=" * 90)
    print("8) MACHINE-READABLE SUMMARY")
    print("=" * 90)

    summary = {
        "query": QUERY,
        "predictive_count": len(predictive),
        "localized_search_html_count": len(normal_page),
        "pre_product_accepted": len(accepted),
        "pre_product_rejected": len(rejected_before_product),
        "product_stage_count": len(results),
        "final_accepted_count": len(final),
        "targets": {},
    }

    for target in ("kobra", "reina"):
        entries = []

        for result in results:
            text = norm(
                " ".join(
                    str(result.get(key) or "")
                    for key in ("candidate_title", "json_title", "url")
                )
            )
            if target in text:
                entries.append({
                    "title": result.get("json_title") or result.get("candidate_title"),
                    "url": result.get("url"),
                    "decision": result.get("decision"),
                    "reason": result.get("reason"),
                    "http_status": result.get("http_status"),
                    "variants_count": result.get("variants_count"),
                    "valid_variants": len(result.get("valid_variants", [])),
                })

        summary["targets"][target] = entries

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    elapsed = time.perf_counter() - started

    print("\n" + "#" * 90)
    print(f"# DIAGNOSTIC FINISHED IN {elapsed:.2f}s")
    print("#" * 90)
    print(
        "\nSend me the COMPLETE terminal output from this diagnostic. "
        "Do not change the production Bplatz scraper yet."
    )


if __name__ == "__main__":
    main()
