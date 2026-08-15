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


def _product_line_key(item: Dict[str, Any]) -> tuple:
    """
    Conservative product-line identity used only to collapse duplicate
    Shopify listings from the same store.

    It deliberately keeps meaningful name words (for example "Uomo"),
    while removing vendor, concentration, gender and format words. This
    prevents "Liquid Brun" duplicate listings from becoming two offers,
    without merging distinct names such as "Titan" and "Titan Uomo".
    """
    source = item.get("source") or {}
    name = _norm(source.get("source_name"))
    brand = _norm(source.get("source_brand"))

    removable = set(IGNORED_QUERY_WORDS) | {
        "men", "male", "homme", "hommes",
        "women", "female", "femme", "femmes",
        "unisex", "unisexe",
        "french", "avenue",
    }

    tokens = []
    for token in name.split():
        if token in removable:
            continue
        if token.isdigit():
            continue
        tokens.append(token)

    # Remove the brand from the name if it is still present.
    brand_tokens = set(brand.split())
    tokens = [token for token in tokens if token not in brand_tokens]

    return (
        brand,
        " ".join(tokens),
        (item.get("attributes") or {}).get("size_ml", {}).get("value"),
        (item.get("attributes") or {}).get("concentration", {}).get("value"),
    )


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


def _request_json(session: requests.Session, url: str, params=None):
    try:
        response = session.get(
            url, params=params, headers=HEADERS, timeout=TIMEOUT
        )
        if not response.ok:
            return None
        return response.json()
    except (requests.RequestException, ValueError, TypeError):
        return None


def _product_json(session: requests.Session, url: str) -> Optional[Dict[str, Any]]:
    clean_url = url.split("?")[0].rstrip("/")
    data = _request_json(session, clean_url + ".js")
    return data if isinstance(data, dict) else None


def _discovery(session: requests.Session, query: str) -> List[str]:
    queries = [query]
    tokens = _query_tokens(query)

    if len(tokens) >= 2:
        broader = " ".join(tokens[:2])
        if broader and _norm(broader) != _norm(query):
            queries.append(broader)

    urls = []
    seen = set()

    for search_query in queries:
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
            if not product_url or "/products/" not in product_url:
                continue

            product_url = product_url.split("?")[0]
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)

    # Server-rendered search is a discovery fallback, not an identity engine.
    html_url = BASE_URL + "/search?q=" + quote_plus(query) + "&type=product"
    try:
        response = session.get(html_url, headers=HEADERS, timeout=TIMEOUT)
        if response.ok:
            soup = BeautifulSoup(response.text, "html.parser")
            for anchor in soup.select('a[href*="/products/"]'):
                product_url = urljoin(
                    BASE_URL, anchor.get("href") or ""
                ).split("?")[0]
                title = _clean(
                    anchor.get("title")
                    or anchor.get_text(" ", strip=True)
                )
                # Some Shopify themes render the product card without putting
                # the real product name in the anchor text/title. The product
                # URL slug is still reliable and contains the searchable name.
                candidate_text = f"{title} {product_url}"
                if (
                    "/products/" in product_url
                    and _matches(candidate_text, query)
                    and product_url not in seen
                ):
                    seen.add(product_url)
                    urls.append(product_url)
    except requests.RequestException:
        pass

    # Final Shopify fallback. Some themes/search configurations expose the
    # product in the JSON search endpoint even when predictive search or the
    # rendered search page does not expose a usable product title.
    try:
        response = session.get(
            BASE_URL + "/search.json",
            params={"q": query, "type": "product", "limit": 50},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if response.ok:
            data = response.json()
            for product in (data.get("products") or []):
                if not isinstance(product, dict):
                    continue
                title = _clean(product.get("title"))
                vendor = _clean(product.get("vendor"))
                product_url = urljoin(
                    BASE_URL, product.get("url") or ""
                ).split("?")[0]
                candidate_text = f"{title} {vendor} {product_url}"
                if (
                    "/products/" in product_url
                    and _matches(candidate_text, query)
                    and product_url not in seen
                ):
                    seen.add(product_url)
                    urls.append(product_url)
    except (requests.RequestException, ValueError, TypeError):
        pass

    return urls


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
        results = []
        seen = set()

        for url in _discovery(session, query):
            for item in _extract_product(session, url, query):
                key = (
                    item["store"],
                    (item["identity"]["store_variant_id"] or {}).get("value"),
                    item["url"],
                )
                if key in seen:
                    continue
                seen.add(key)
                results.append(item)

        # Shopify can expose the same product line through more than one
        # product URL. This is especially visible on Liquid Brun: one
        # listing is available while another duplicate listing is marked
        # out of stock. Keep one offer for the same store/product line,
        # preferring a real in-stock offer.
        grouped = {}
        for item in results:
            key = (item.get("store"), _product_line_key(item))
            grouped.setdefault(key, []).append(item)

        final_results = []
        for group in grouped.values():
            in_stock = [
                item for item in group
                if item.get("offer", {}).get("availability") == "in_stock"
            ]

            if in_stock:
                candidates = in_stock
            else:
                candidates = group

            # One store offer per product line. Prefer the cheapest valid
            # offer when several available duplicate listings remain.
            candidates = sorted(
                candidates,
                key=lambda item: (
                    item.get("offer", {}).get("price")
                    if item.get("offer", {}).get("price") is not None
                    else float("inf")
                ),
            )
            final_results.append(candidates[0])

        return final_results
    finally:
        session.close()


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generic Orioudh store adapter")
    parser.add_argument("query")
    args = parser.parse_args()

    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
