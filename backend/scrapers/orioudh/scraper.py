import json
import re
import html
from typing import List, Dict, Optional, Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
    "spray", "ml", "for", "by", "pour",
}


def _clean(value) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _norm(value) -> str:
    value = _clean(value).lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _query_tokens(query: str) -> List[str]:
    return [
        token for token in _norm(query).split()
        if token and token not in IGNORED_QUERY_WORDS
    ]


def _matches(text: str, query: str) -> bool:
    haystack = _norm(text)
    tokens = _query_tokens(query)
    return bool(tokens) and all(token in haystack for token in tokens)


def _price(value) -> Optional[float]:
    if value in (None, ""):
        return None

    # Orioudh is Shopify. In the product JSON (`/products/...js`) Shopify
    # returns variant prices as integer cents: 3185 = 31.85 €.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        amount = float(value) / 100.0
        return round(amount, 2) if amount > 0 else None

    raw = _clean(value).replace("€", "").strip()
    match = re.search(r"\d+(?:[.,]\d{1,2})?", raw)
    if not match:
        return None
    try:
        amount = float(match.group(0).replace(",", "."))
    except ValueError:
        return None
    return round(amount, 2) if amount > 0 else None


def _format_price(value) -> str:
    amount = _price(value)
    return f"{amount:.2f}".replace(".", ",") + " €" if amount is not None else ""


def _gtin(value) -> Optional[str]:
    if value in (None, ""):
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def _size_ml(*values) -> Optional[float]:
    text = " ".join(_clean(value) for value in values)
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:ml|cl)\b", text, re.I)
    if not match:
        return None
    amount = float(match.group(1).replace(",", "."))
    if match.group(0).lower().endswith("cl"):
        amount *= 10
    return int(amount) if amount.is_integer() else amount


def _concentration(*values) -> Optional[str]:
    text = _norm(" ".join(_clean(value) for value in values))
    rules = (
        ("Extrait de Parfum", r"\bextrait(?: de)? parfum\b"),
        ("Eau de Parfum", r"\beau de parfum\b|\bedp\b"),
        ("Eau de Toilette", r"\beau de toilette\b|\bedt\b"),
        ("Eau de Cologne", r"\beau de cologne\b|\bedc\b"),
        ("Parfum", r"\bparfum\b"),
    )
    for label, pattern in rules:
        if re.search(pattern, text, re.I):
            return label
    return None


def _gender(*values) -> str:
    text = _norm(" ".join(_clean(value) for value in values))
    if re.search(r"\b(?:for men|men|male|herren|homme|hommes)\b", text):
        return "men"
    if re.search(r"\b(?:for women|women|female|damen|femme|femmes)\b", text):
        return "women"
    if re.search(r"\b(?:unisex|unisexe)\b", text):
        return "unisex"
    return "unknown"


def _availability(value) -> str:
    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    text = _norm(value)
    if any(x in text for x in (
        "out of stock", "sold out", "unavailable", "ausverkauft",
        "nicht auf lager", "rupture de stock",
    )):
        return "out_of_stock"
    if any(x in text for x in (
        "in stock", "available", "disponible", "auf lager",
    )):
        return "in_stock"
    return "unknown"


def _image(data: Dict[str, Any]) -> Optional[str]:
    image = data.get("featured_image")
    if isinstance(image, dict):
        image = image.get("src") or image.get("url")
    if not image:
        images = data.get("images") or []
        if images:
            image = images[0]
    return urljoin(BASE_URL, str(image)) if image else None


class StoreRequestError(RuntimeError):
    def __init__(self, status, message, *, http_status=None):
        super().__init__(message)
        self.status = status
        self.http_status = http_status


def _request_json(session: requests.Session, url: str, params=None):
    try:
        response = session.get(
            url, params=params, headers=HEADERS, timeout=TIMEOUT
        )
    except requests.Timeout as exc:
        raise StoreRequestError("timeout", str(exc)) from exc
    except requests.ConnectionError as exc:
        raise StoreRequestError("unavailable", str(exc)) from exc
    except requests.RequestException as exc:
        raise StoreRequestError("error", str(exc)) from exc

    if response.status_code in (403, 429):
        status = "blocked"
    elif 500 <= response.status_code <= 599:
        status = "unavailable"
    elif 400 <= response.status_code <= 499:
        status = "error"
    else:
        status = None

    if status:
        code = response.status_code
        response.close()
        raise StoreRequestError(status, f"HTTP {code}", http_status=code)

    try:
        data = response.json()
    except (ValueError, TypeError) as exc:
        response.close()
        raise StoreRequestError("error", "Invalid JSON response") from exc

    response.close()
    return data

def _product_json(session: requests.Session, url: str) -> Optional[Dict[str, Any]]:
    clean_url = url.split("?")[0].rstrip("/")
    data = _request_json(session, clean_url + ".js")
    return data if isinstance(data, dict) else None

def _discovery(session: requests.Session, query: str):
    tokens = _query_tokens(query)
    queries = [query]

    if len(tokens) >= 2:
        broader = " ".join(tokens[:2])
        if broader and _norm(broader) != _norm(query):
            queries.append(broader)
        for token in reversed(tokens):
            if token and _norm(token) not in {_norm(q) for q in queries}:
                queries.append(token)

    urls = []
    seen = set()
    errors = []

    for search_query in queries:
        try:
            data = _request_json(
                session,
                BASE_URL + "/search/suggest.json",
                params={
                    "q": search_query,
                    "resources[type]": "product",
                    "resources[limit]": 50,
                    "resources[options][unavailable_products]": "show",
                },
            )
        except StoreRequestError as exc:
            errors.append(exc)
            continue

        products = (
            ((data or {}).get("resources") or {})
            .get("results", {})
            .get("products", [])
        )

        for product in products:
            if not isinstance(product, dict):
                continue
            title = _clean(product.get("title"))
            vendor = _clean(product.get("vendor"))
            if not _matches(title + " " + vendor, query):
                continue

            product_url = urljoin(BASE_URL, product.get("url") or "")
            if "/products/" not in product_url:
                continue
            product_url = product_url.split("?")[0]
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)

    # Rendered Shopify search remains a generic fallback.
    try:
        response = session.get(
            BASE_URL + "/search",
            params={"q": query, "type": "product"},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if response.status_code in (403, 429):
            code = response.status_code
            response.close()
            errors.append(StoreRequestError("blocked", f"HTTP {code}", http_status=code))
        elif 500 <= response.status_code <= 599:
            code = response.status_code
            response.close()
            errors.append(StoreRequestError("unavailable", f"HTTP {code}", http_status=code))
        elif 400 <= response.status_code <= 499:
            code = response.status_code
            response.close()
            errors.append(StoreRequestError("error", f"HTTP {code}", http_status=code))
        elif response.ok:
            soup = BeautifulSoup(response.text, "html.parser")
            for anchor in soup.select('a[href*="/products/"]'):
                product_url = urljoin(
                    BASE_URL, anchor.get("href") or ""
                ).split("?")[0]
                title = _clean(
                    anchor.get("title") or anchor.get_text(" ", strip=True)
                )
                candidate_text = f"{title} {product_url}"
                if (
                    "/products/" in product_url
                    and _matches(candidate_text, query)
                    and product_url not in seen
                ):
                    seen.add(product_url)
                    urls.append(product_url)
        response.close()
    except requests.Timeout as exc:
        errors.append(StoreRequestError("timeout", str(exc)))
    except requests.ConnectionError as exc:
        errors.append(StoreRequestError("unavailable", str(exc)))
    except requests.RequestException as exc:
        errors.append(StoreRequestError("error", str(exc)))

    # JSON search is another generic Shopify discovery channel.
    try:
        response = session.get(
            BASE_URL + "/search.json",
            params={"q": query, "type": "product", "limit": 50},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if response.status_code in (403, 429):
            code = response.status_code
            response.close()
            errors.append(StoreRequestError("blocked", f"HTTP {code}", http_status=code))
        elif 500 <= response.status_code <= 599:
            code = response.status_code
            response.close()
            errors.append(StoreRequestError("unavailable", f"HTTP {code}", http_status=code))
        elif 400 <= response.status_code <= 499:
            code = response.status_code
            response.close()
            errors.append(StoreRequestError("error", f"HTTP {code}", http_status=code))
        elif response.ok:
            try:
                data = response.json()
            except (ValueError, TypeError) as exc:
                errors.append(StoreRequestError("error", "Invalid JSON response"))
                data = {}
            for product in (data.get("products") or []):
                if not isinstance(product, dict):
                    continue
                title = _clean(product.get("title"))
                vendor = _clean(product.get("vendor"))
                product_url = urljoin(
                    BASE_URL, product.get("url") or ""
                ).split("?")[0]
                if (
                    "/products/" in product_url
                    and _matches(f"{title} {vendor} {product_url}", query)
                    and product_url not in seen
                ):
                    seen.add(product_url)
                    urls.append(product_url)
        response.close()
    except requests.Timeout as exc:
        errors.append(StoreRequestError("timeout", str(exc)))
    except requests.ConnectionError as exc:
        errors.append(StoreRequestError("unavailable", str(exc)))
    except requests.RequestException as exc:
        errors.append(StoreRequestError("error", str(exc)))

    return urls, errors

def _raw_offer(
    product: Dict[str, Any],
    variant: Dict[str, Any],
    url: str,
) -> Dict[str, Any]:
    product_name = _clean(product.get("title"))
    variant_name = _clean(variant.get("title"))
    if variant_name and variant_name != "Default Title":
        source_name = f"{product_name} {variant_name}".strip()
    else:
        source_name = product_name

    vendor = _clean(product.get("vendor")) or None
    product_line = _canonical_product_line(source_name, vendor or "")
    variant_id = variant.get("id")
    product_id = product.get("id")
    sku = _clean(variant.get("sku")) or None
    gtin = _gtin(variant.get("barcode"))
    size = _size_ml(variant_name, product_name)
    concentration = _concentration(variant_name, product_name)
    gender = _gender(variant_name, product_name)
    price = _price(variant.get("price"))

    return {
        "store": STORE,
        "source": {
            "source_name": source_name,
            "source_brand": vendor,
            "url": url,
            "image": _image(product),
        },
        "identity": {
            "gtin": {"value": gtin, "source": "shopify_barcode"} if gtin else None,
            "mpn": None,
            "sku": {"value": sku, "source": "shopify_variant"} if sku else None,
            "store_product_id": (
                {"value": product_id, "source": "shopify_product"}
                if product_id is not None else None
            ),
            "store_variant_id": (
                {"value": variant_id, "source": "shopify_variant"}
                if variant_id is not None else None
            ),
        },
        "attributes": {
            "size_ml": {"value": size, "source": "product_source"}
            if size is not None else None,
            "concentration": (
                {"value": concentration, "source": "product_source"}
                if concentration else None
            ),
            "gender": {"value": gender, "source": "product_source"},
            "product_line": {"value": product_line, "source": "canonical_name"},
            "packaging_type": {"value": "product", "source": "default"},
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": _availability(variant.get("available")),
        },
        "provenance": {
            "source_page": url,
            "product_source": "shopify_product_json",
            "variant_source": "shopify_product_json",
        },
        "raw_data": {
            "product": product,
            "variant": variant,
        },
        # Compatibility fields for the current API during migration.
        "name": source_name,
        "price": (f"{price:.2f}".replace(".", ",") + " €") if price is not None else "",
        "url": url,
        "available": variant.get("available") is True,
    }


def _extract_product(
    session: requests.Session,
    url: str,
    query: str,
) -> List[Dict[str, Any]]:
    product = _product_json(session, url)
    if not product:
        return []

    product_name = _clean(product.get("title"))
    vendor = _clean(product.get("vendor"))

    if not _matches(product_name + " " + vendor, query):
        return []

    variants = product.get("variants") or []
    if not isinstance(variants, list):
        return []

    results = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        item = _raw_offer(product, variant, url)
        if item["offer"]["price"] is None:
            continue
        results.append(item)

    return results


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    try:
        urls, discovery_errors = _discovery(session, query)
        results = []
        seen = set()

        for url in urls:
            try:
                items = _extract_product(session, url, query)
            except StoreRequestError:
                continue

            for item in items:
                key = (
                    item.get("store"),
                    (item.get("identity", {}).get("store_variant_id") or {}).get("value"),
                    item.get("url"),
                )
                if key in seen:
                    continue
                seen.add(key)
                results.append(item)

        # Keep transport information available to search_stream without
        # changing the commercial offer rows themselves.
        search._last_discovery_errors = discovery_errors
        return results
    finally:
        session.close()


def search_stream(query: str, emit=None):
    """Return the common ScentHunter scraper report."""
    query = _clean(query)
    if not query:
        return {
            "status": "success", "verified": True, "results": [],
            "error": None, "details": {"reason": "empty_query"},
        }

    try:
        rows = search(query)
        errors = getattr(search, "_last_discovery_errors", [])
    except StoreRequestError as exc:
        return {
            "status": exc.status, "verified": False, "results": [],
            "error": str(exc), "details": {"http_status": exc.http_status},
        }
    except requests.Timeout as exc:
        return {"status": "timeout", "verified": False, "results": [],
                "error": str(exc), "details": {}}
    except requests.ConnectionError as exc:
        return {"status": "unavailable", "verified": False, "results": [],
                "error": str(exc), "details": {}}
    except requests.RequestException as exc:
        return {"status": "error", "verified": False, "results": [],
                "error": str(exc), "details": {}}
    except Exception as exc:
        return {
            "status": "error", "verified": False, "results": [],
            "error": str(exc),
            "details": {"exception": type(exc).__name__},
        }

    rows = rows if isinstance(rows, list) else []
    if emit is not None:
        for row in rows:
            emit(row)

    if rows:
        return {
            "status": "success", "verified": True, "results": rows,
            "error": None, "details": {"count": len(rows)},
        }

    if errors:
        first = errors[0]
        return {
            "status": first.status,
            "verified": False,
            "results": [],
            "error": str(first),
            "details": {
                "error_count": len(errors),
                "http_status": first.http_status,
            },
        }

    return {
        "status": "partial",
        "verified": False,
        "results": [],
        "error": None,
        "details": {
            "count": 0,
            "reason": "no_results_without_authoritative_empty_verification",
        },
    }


def scrape(query: str):
    return search_stream(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generic Orioudh store adapter")
    parser.add_argument("query")
    args = parser.parse_args()

    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
