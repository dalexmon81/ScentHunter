from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

STORE = "ParfumCity"
BASE_URL = "https://www.parfumcity.nl"
CATALOG_URL = BASE_URL + "/products.json"
TIMEOUT = 6
CATALOG_PAGE_SIZE = 250
MAX_CATALOG_PAGES = 40
MAX_RESULTS = 50
CATALOG_WORKERS = 8

class StoreRequestError(RuntimeError):
    def __init__(self, kind, message, url=None, status_code=None):
        super().__init__(message)
        self.kind = kind
        self.url = url
        self.status_code = status_code

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

NON_FRAGRANCE = {
    "gift card", "giftcard", "candle", "diffuser", "room spray",
    "body lotion", "body cream", "body wash", "shower gel", "shampoo",
    "conditioner", "deodorant", "after shave", "aftershave", "soap",
    "hand cream",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(value).lower())).strip()


def query_tokens(query):
    return [
        token for token in norm(query).split()
        if token not in {"eau", "de", "parfum", "perfume", "edp", "edt", "extrait", "spray", "for", "by", "pour", "ml", "cl"}
        and not re.fullmatch(r"\d+(?:[.,]\d+)?", token)
    ]


def matches(text, query):
    wanted = query_tokens(query)
    if not wanted:
        return False
    hay = set(norm(text).split())
    return all(token in hay for token in wanted)


def size_ml(*values):
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        " ".join(clean(value) for value in values), re.I,
    )
    if not match:
        return None
    number = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        number *= 10
    return int(number) if number.is_integer() else number


def concentration(*values):
    text = norm(" ".join(clean(value) for value in values))
    if re.search(r"\beau de toilette\b|\bedt\b", text):
        return "Eau de Toilette"
    if re.search(r"\bextrait(?: de parfum)?\b", text):
        return "Extrait de Parfum"
    if re.search(r"\beau de parfum\b|\bedp\b", text):
        return "Eau de Parfum"
    return None


def price(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number >= 100:
            number /= 100.0
        return round(number, 2)
    match = re.search(r"\d+(?:[.,]\d{1,2})?", clean(value).replace("€", ""))
    if not match:
        return None
    number = float(match.group(0).replace(",", "."))
    if re.fullmatch(r"\d+", match.group(0)) and number >= 100:
        number /= 100.0
    return round(number, 2)


def _get(session, url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.Timeout as exc:
        raise StoreRequestError(
            "timeout",
            f"timeout while requesting {url}",
            url=url,
        ) from exc
    except requests.RequestException as exc:
        raise StoreRequestError(
            "unavailable",
            f"request failed for {url}: {type(exc).__name__}: {exc}",
            url=url,
        ) from exc

    if response.status_code in (403, 429):
        raise StoreRequestError(
            "blocked",
            f"HTTP {response.status_code} from {url}",
            url=url,
            status_code=response.status_code,
        )
    if response.status_code >= 500:
        raise StoreRequestError(
            "unavailable",
            f"HTTP {response.status_code} from {url}",
            url=url,
            status_code=response.status_code,
        )
    if response.status_code >= 400:
        raise StoreRequestError(
            "error",
            f"HTTP {response.status_code} from {url}",
            url=url,
            status_code=response.status_code,
        )
    return response


def _absolute_product_url(value):
    value = clean(value)
    if not value:
        return ""
    return urljoin(BASE_URL + "/", value).split("#")[0].split("?")[0].rstrip("/")


def _product_js_url(url):
    url = url.rstrip("/")
    return url if url.endswith(".js") else url + ".js"


def _catalog_candidate(product):
    if not isinstance(product, dict):
        return None
    handle = clean(product.get("handle"))
    url = _absolute_product_url(product.get("url") or (f"/products/{handle}" if handle else ""))
    title = clean(product.get("title"))
    vendor = clean(product.get("vendor"))
    if not url or not title:
        return None
    return {"url": url, "title": title, "vendor": vendor, "raw": product}


def _catalog_page(session, page):
    response = _get(
        session,
        CATALOG_URL,
        {"limit": CATALOG_PAGE_SIZE, "page": page},
    )
    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        raise StoreRequestError(
            "error",
            f"invalid Shopify catalog JSON on page {page}",
            url=CATALOG_URL,
        ) from exc

    products = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(products, list):
        raise StoreRequestError(
            "error",
            f"invalid Shopify catalog payload on page {page}",
            url=CATALOG_URL,
        )
    return products


def _discover_catalog(query, session):
    candidates = {}

    for page in range(1, MAX_CATALOG_PAGES + 1):
        products = _catalog_page(session, page)
        if not products:
            break

        for product in products:
            candidate = _catalog_candidate(product)
            if not candidate:
                continue

            haystack = " ".join(
                str(candidate.get(key) or "")
                for key in ("title", "vendor", "url")
            )

            if matches(haystack, query):
                candidates[candidate["url"]] = candidate

        if len(products) < CATALOG_PAGE_SIZE:
            break

    return list(candidates.values())


def _extract_image(product):
    image = product.get("featured_image")
    if isinstance(image, dict):
        image = image.get("src") or image.get("url")
    if image:
        return urljoin(BASE_URL, str(image))
    images = product.get("images") or []
    if images:
        first = images[0]
        if isinstance(first, dict):
            first = first.get("src") or first.get("url")
        return urljoin(BASE_URL, str(first)) if first else None
    return None


def _is_non_fragrance(title):
    value = norm(title)
    return any(term in value for term in NON_FRAGRANCE)


def _product_worker(candidate, query):
    url = candidate["url"]
    session = requests.Session()

    try:
        response = _get(session, _product_js_url(url))

        try:
            product = response.json()
        except (ValueError, TypeError) as exc:
            raise StoreRequestError(
                "error",
                f"invalid product JSON from {url}",
                url=url,
            ) from exc

        if not isinstance(product, dict):
            raise StoreRequestError(
                "error",
                f"invalid product payload from {url}",
                url=url,
            )

        name = clean(product.get("title") or candidate.get("title"))
        brand = clean(product.get("vendor") or candidate.get("vendor"))

        if not name or not matches(f"{name} {brand} {url}", query):
            return []

        if _is_non_fragrance(name):
            return []

        image = _extract_image(product)
        rows = []

        for variant in product.get("variants") or []:
            if not isinstance(variant, dict):
                continue

            amount = price(variant.get("price"))
            if amount is None:
                continue

            variant_title = clean(variant.get("title"))
            available = variant.get("available")

            rows.append({
                "store": STORE,
                "source": {
                    "source_name": (
                        name
                        if not variant_title or variant_title.lower() == "default title"
                        else f"{name} {variant_title}"
                    ),
                    "source_brand": brand or None,
                    "url": url,
                    "image": image,
                },
                "identity": {
                    "gtin": None,
                    "mpn": None,
                    "sku": (
                        {"value": str(variant.get("sku")), "source": "shopify_variant"}
                        if variant.get("sku") else None
                    ),
                    "store_product_id": (
                        {"value": product.get("id"), "source": "shopify_product"}
                        if product.get("id") is not None else None
                    ),
                    "store_variant_id": (
                        {"value": variant.get("id"), "source": "shopify_variant"}
                        if variant.get("id") is not None else None
                    ),
                },
                "attributes": {
                    "size_ml": (
                        {"value": size_ml(variant_title, name), "source": "product_variant"}
                        if size_ml(variant_title, name) is not None else None
                    ),
                    "concentration": (
                        {"value": concentration(variant_title, name), "source": "product_title"}
                        if concentration(variant_title, name) else None
                    ),
                    "gender": {"value": "unknown", "source": "not_explicit"},
                    "packaging_type": {"value": "product", "source": "default"},
                },
                "offer": {
                    "price": amount,
                    "currency": "EUR",
                    "availability": (
                        "in_stock" if available is True
                        else "out_of_stock" if available is False
                        else "unknown"
                    ),
                },
                "provenance": {
                    "source_page": url,
                    "product_source": "shopify_product_json",
                    "variant_source": "shopify_product_json",
                },
                "raw_data": {"product": product, "variant": variant},
                "name": name,
                "price": f"{amount:.2f}".replace(".", ",") + " €",
                "url": url,
                "available": available,
            })

        return rows

    finally:
        session.close()


def _report(status, results=None, error=None, details=None):
    return {
        "status": status,
        "results": results or [],
        "error": error,
        "details": details or {},
    }


def search_stream(query, emit):
    query = clean(query)
    if not query:
        return _report("error", error="empty_query")

    session = requests.Session()

    try:
        try:
            candidates = _discover_catalog(query, session)
        except StoreRequestError as exc:
            return _report(
                exc.kind,
                error=str(exc),
                details={"url": exc.url, "status_code": exc.status_code},
            )
    finally:
        session.close()

    if not candidates:
        return _report("success", results=[])

    results = []
    failures = []

    with ThreadPoolExecutor(
        max_workers=min(CATALOG_WORKERS, len(candidates))
    ) as pool:
        futures = {
            pool.submit(_product_worker, candidate, query): candidate
            for candidate in candidates
        }

        for future in as_completed(futures):
            candidate = futures[future]

            try:
                rows = future.result() or []
            except StoreRequestError as exc:
                failures.append({
                    "url": candidate.get("url"),
                    "status": exc.kind,
                    "error": str(exc),
                })
                continue
            except Exception as exc:
                failures.append({
                    "url": candidate.get("url"),
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            for row in rows:
                if isinstance(row, dict):
                    results.append(row)
                    emit(row)

    return _report(
        "partial" if failures else "success",
        results=results,
        details={
            "candidate_count": len(candidates),
            "failed_candidates": failures,
        },
    )


def search(query):
    return search_stream(query, lambda row: None)


def scrape(query):
    return search(query)


def diagnose(query):
    query = clean(query)
    if not query:
        return {
            "diagnostic": True,
            "query": query,
            "status": "error",
            "candidate_count": 0,
            "candidates": [],
        }

    session = requests.Session()
    try:
        try:
            candidates = _discover_catalog(query, session)
            return {
                "diagnostic": True,
                "query": query,
                "status": "success",
                "candidate_count": len(candidates),
                "candidates": [candidate["url"] for candidate in candidates[:100]],
            }
        except StoreRequestError as exc:
            return {
                "diagnostic": True,
                "query": query,
                "status": exc.kind,
                "error": str(exc),
                "candidate_count": 0,
                "candidates": [],
            }
    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    print(json.dumps(diagnose(args.query) if args.diagnose else search(args.query), ensure_ascii=False, indent=2))
