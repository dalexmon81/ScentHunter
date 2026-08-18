import json
import re
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://bplatz.de"
STORE = "Bplatz"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Safari/604.1"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
TIMEOUT = 20

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
    "spray", "ml", "for", "by"
}

PACKAGING_RULES = (
    ("gift_set", ("gift set", "giftset", "geschenkset", "coffret", "gift box")),
    ("discovery_set", ("discovery set", "discoveryset", "sample set", "discovery")),
    ("bundle", ("bundle", "set", "duo", "trio", "pack")),
    ("tester", ("tester",)),
    ("sample", ("sample", "probe")),
    ("decant", ("decant",)),
)


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def query_matches(name, query):
    q = [t for t in norm(query).split() if t not in IGNORED_QUERY_WORDS]
    n = norm(name)
    return bool(q) and all(t in n for t in q)


def money(value):
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", "."))
        # Shopify product JSON exposes variant prices in cents.
        return round(number / 100.0, 2)
    except (ValueError, TypeError):
        return None


def normalize_gtin(value):
    if value in (None, ""):
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def extract_size_ml(*texts):
    combined = " ".join(str(x or "") for x in texts)
    patterns = (
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:ml|milliliter|milliliters)\b",
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*ml\b",
    )
    values = []
    for pattern in patterns:
        for match in re.finditer(pattern, combined, flags=re.I):
            try:
                values.append(float(match.group(1).replace(",", ".")))
            except ValueError:
                pass
    if not values:
        return None
    value = values[0]
    return int(value) if value.is_integer() else value


def extract_concentration(*texts):
    combined = " ".join(str(x or "") for x in texts)
    rules = (
        ("Extrait de Parfum", (r"\bextrait(?:\s+de)?\s+parfum\b",)),
        ("Eau de Parfum", (r"\beau\s+de\s+parfum\b", r"\bedp\b")),
        ("Eau de Toilette", (r"\beau\s+de\s+toilette\b", r"\bedt\b")),
        ("Eau de Cologne", (r"\beau\s+de\s+cologne\b", r"\bedc\b")),
        ("Parfum", (r"\bparfum\b",)),
    )
    normalized = norm(combined)
    for label, patterns in rules:
        for pattern in patterns:
            if re.search(pattern, normalized, flags=re.I):
                return label, "product_title"
    return None, None


def extract_gender(*texts):
    normalized = norm(" ".join(str(x or "") for x in texts))
    if re.search(r"\b(?:pour homme|for men|men|male|herren|heren)\b", normalized):
        return "men", "product_title"
    if re.search(r"\b(?:pour femme|for women|women|female|damen|dames)\b", normalized):
        return "women", "product_title"
    if re.search(r"\b(?:unisex|unisexe|unisexes)\b", normalized):
        return "unisex", "product_title"
    return "unknown", None


def extract_packaging_type(*texts):
    normalized = norm(" ".join(str(x or "") for x in texts))
    for packaging_type, terms in PACKAGING_RULES:
        for term in terms:
            if re.search(r"\b" + re.escape(norm(term)) + r"\b", normalized):
                return packaging_type, "product_title"
    return "product", "default"


def predictive_products(session, query):
    endpoint = BASE + "/search/suggest.json"
    params = {
        "q": query,
        "resources[type]": "product",
        "resources[limit]": "10",
        "resources[options][unavailable_products]": "show",
    }
    try:
        response = session.get(
            endpoint, params=params, headers=HEADERS, timeout=TIMEOUT
        )
        if not response.ok:
            return []
        data = response.json()
        return (
            ((data or {}).get("resources") or {})
            .get("results", {})
            .get("products", [])
        ) or []
    except (requests.RequestException, ValueError, TypeError):
        return []


def product_json(session, url):
    clean = url.split("?")[0].rstrip("/")
    js_url = clean + ".js"
    try:
        response = session.get(js_url, headers=HEADERS, timeout=TIMEOUT)
        if not response.ok:
            return None
        return response.json()
    except (requests.RequestException, ValueError):
        return None


def _shopify_image(data):
    image = data.get("featured_image")
    if isinstance(image, dict):
        image = image.get("src") or image.get("url")
    if not image:
        images = data.get("images") or []
        if images:
            image = images[0]
    if not image:
        return None
    return urljoin(BASE, str(image))


def _source_value(value, source):
    if value in (None, ""):
        return None
    return {"value": value, "source": source}


def variant_record(data, variant, url):
    product_title = str(data.get("title") or "").strip()
    vendor = str(data.get("vendor") or "").strip() or None
    variant_title = str(variant.get("title") or "").strip()
    source_name = " ".join(
        x for x in (product_title, variant_title)
        if x and x != "Default Title"
    )

    size_ml = extract_size_ml(variant_title, product_title)
    concentration, concentration_source = extract_concentration(
        variant_title, product_title
    )
    gender, gender_source = extract_gender(variant_title, product_title)
    packaging_type, packaging_source = extract_packaging_type(
        variant_title, product_title
    )

    price = money(variant.get("price"))
    available = variant.get("available")
    if available is True:
        availability = "in_stock"
    elif available is False:
        availability = "out_of_stock"
    else:
        availability = "unknown"

    variant_id = variant.get("id")
    product_id = data.get("id")
    sku = str(variant.get("sku") or "").strip() or None
    gtin = normalize_gtin(variant.get("barcode"))

    provenance = {
        "name": "shopify_product",
        "brand": "shopify_vendor" if vendor else None,
        "price": "shopify_variant",
        "availability": "shopify_variant",
        "image": "shopify_product",
        "store_product_id": "shopify_product" if product_id else None,
        "store_variant_id": "shopify_variant" if variant_id else None,
        "sku": "shopify_variant" if sku else None,
        "gtin": "shopify_barcode" if gtin else None,
        "size_ml": "product_title" if size_ml is not None else None,
        "concentration": concentration_source,
        "gender": gender_source,
        "packaging_type": packaging_source,
    }

    raw_data = {
        "product": {
            "id": product_id,
            "title": product_title,
            "vendor": vendor,
            "product_type": data.get("product_type"),
            "handle": data.get("handle"),
            "tags": data.get("tags") or [],
            "featured_image": data.get("featured_image"),
        },
        "variant": dict(variant),
    }

    return {
        "store": STORE,
        "source": {
            "url": url,
            "name": source_name,
            "brand": vendor,
            "image": _shopify_image(data),
        },
        "identity": {
            "gtin": _source_value(gtin, "shopify_barcode"),
            "mpn": None,
            "sku": _source_value(sku, "shopify_variant"),
            "store_product_id": _source_value(product_id, "shopify_product"),
            "store_variant_id": _source_value(variant_id, "shopify_variant"),
        },
        "attributes": {
            "size_ml": _source_value(size_ml, "product_title"),
            "concentration": _source_value(concentration, concentration_source),
            "gender": _source_value(gender, gender_source) or {
                "value": "unknown",
                "source": "default",
            },
            "packaging_type": _source_value(packaging_type, packaging_source),
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": availability,
        },
        "provenance": provenance,
        "raw_data": raw_data,

        # Backward-compatible fields for the current main.py.
        "name": source_name,
        "price": (
            f"{price:.2f}".replace(".", ",") + " €"
            if price is not None else ""
        ),
        "url": url,
        "available": available is True,
    }


def product_from_json(data, url):
    if not isinstance(data, dict):
        return []

    variants = data.get("variants") or []
    if not variants:
        return []

    return [
        variant_record(data, variant, url)
        for variant in variants
        if isinstance(variant, dict)
    ]


def search_html_urls(session, query):
    url = BASE + "/search?q=" + quote_plus(query) + "&type=product"
    try:
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        if not response.ok:
            return []
    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    urls = []
    seen = set()

    for anchor in soup.select('a[href*="/products/"]'):
        href = anchor.get("href") or ""
        absolute = urljoin(BASE, href).split("?")[0]
        path = urlparse(absolute).path.rstrip("/")

        if not path or path in seen:
            continue

        title = (
            anchor.get("title")
            or anchor.get("aria-label")
            or anchor.get_text(" ", strip=True)
            or ""
        )

        if not query_matches(title, query):
            node = anchor
            for _ in range(5):
                node = node.parent if node is not None else None
                if node is None:
                    break
                candidate = node.get_text(" ", strip=True)
                if query_matches(candidate, query):
                    title = candidate
                    break

        if not query_matches(title, query):
            continue

        seen.add(path)
        urls.append(absolute)

    return urls


def candidate_queries(query):
    normalized = norm(query)
    if not normalized:
        return []

    searches = [query.strip()]
    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )

    if compact and compact != normalized:
        searches.append(compact)

    tokens = [
        token
        for token in normalized.split()
        if token not in IGNORED_QUERY_WORDS
    ]

    for token in tokens:
        if len(token) >= 3 and token not in searches:
            searches.append(token)

    return searches


def candidate_urls(session, query):
    urls = []
    seen = set()

    for search_query in candidate_queries(query):
        for product in predictive_products(session, search_query):
            if not isinstance(product, dict):
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

    for search_query in candidate_queries(query):
        for absolute in search_html_urls(session, search_query):
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
    seen_variants = set()

    for url in candidate_urls(session, query):
        data = product_json(session, url)
        items = product_from_json(data, url)

        for item in items:
            # Query filtering is applied only to the source name.
            # Identity is deliberately left to the central Identity Engine.
            if not query_matches(item.get("name", ""), query):
                continue

            # Exclude tester variants generically.
            packaging = item.get("attributes", {}).get("packaging_type")
            packaging_value = (
                packaging.get("value")
                if isinstance(packaging, dict)
                else packaging
            )
            if packaging_value == "tester":
                continue

            variant_id = item["identity"].get("store_variant_id")
            variant_key = (
                variant_id.get("value")
                if isinstance(variant_id, dict)
                else variant_id
            )

            key = (
                item["store"],
                variant_key or item["url"],
                item.get("name", ""),
            )

            if key in seen_variants:
                continue

            seen_variants.add(key)
            results.append(item)

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generic Bplatz store adapter"
    )
    parser.add_argument("query", help="Search query supplied at runtime")
    args = parser.parse_args()

    for result in search(args.query):
        print(json.dumps(result, ensure_ascii=False, indent=2))
