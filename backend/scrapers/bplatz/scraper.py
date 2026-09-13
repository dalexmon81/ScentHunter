import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

import requests

BASE = "https://bplatz.de"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept": "application/json,text/javascript,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

SEARCH_TIMEOUT = (1.5, 4.0)
PRODUCT_TIMEOUT = (1.5, 4.0)
MAX_CANDIDATES = 12

NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "discovery set", "fragrance set", "perfume set",
    "parfum set", "coffret", "bundle", "pack", "travel set", "kit", "duo",
    "trio", "mystery box", "tester", "testeur", "sample", "shampoo",
    "shower gel", "body lotion", "body cream", "deodorant", "deo spray",
    "aftershave", "after shave", "makeup", "skin care", "skincare",
    "cosmetics", "cosmetici",
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

    ignored = {
        "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
        "spray", "ml", "for", "by", "the",
    }
    query_tokens = [
        token for token in norm(query).split()
        if token not in ignored
    ]
    name_tokens = set(norm(name).split())
    return bool(query_tokens) and all(
        token in name_tokens for token in query_tokens
    )


def parse_price(value):
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        # Shopify JSON normally exposes cents as an integer.
        if number >= 1000:
            number /= 100.0
        return number

    text = str(value).strip().replace("\xa0", " ")
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        if len(text.rsplit(",", 1)[-1]) <= 2:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(".") > 1:
        text = text.replace(".", "")

    try:
        return float(text)
    except ValueError:
        return None


def money(value):
    price = parse_price(value)
    return "" if price is None else f"{price:.2f}".replace(".", ",") + " €"


def request_get(session, url, timeout, params=None):
    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        if response.ok and response.content:
            return response
    except requests.RequestException:
        return None
    return None


def predictive_products(session, query):
    endpoint = BASE + "/search/suggest.json"
    params = {
        "q": query,
        "resources[type]": "product",
        "resources[limit]": "20",
        "resources[options][unavailable_products]": "show",
    }

    response = request_get(
        session,
        endpoint,
        SEARCH_TIMEOUT,
        params=params,
    )
    if not response:
        return []

    try:
        data = response.json()
    except (ValueError, TypeError):
        return []

    products = (
        (((data or {}).get("resources") or {}).get("results") or {}).get("products")
        or []
    )

    candidates = []
    seen = set()

    for product in products:
        if not isinstance(product, dict):
            continue

        title = str(
            product.get("title")
            or product.get("name")
            or ""
        ).strip()

        if not title or not query_matches(title, query):
            continue

        raw_url = (
            product.get("url")
            or product.get("product_url")
            or ""
        )

        if not raw_url:
            continue

        absolute = urljoin(BASE, str(raw_url)).split("?")[0].rstrip("/")
        path = urlparse(absolute).path.rstrip("/")

        if "/products/" not in path or path in seen:
            continue

        seen.add(path)
        candidates.append({
            "url": absolute,
            "title": title,
            "available_hint": product.get("available"),
        })

        if len(candidates) >= MAX_CANDIDATES:
            break

    return candidates


def product_json(session, url):
    clean_url = url.split("?")[0].rstrip("/")
    js_url = clean_url + ".js"

    response = request_get(
        session,
        js_url,
        PRODUCT_TIMEOUT,
    )
    if not response:
        return None

    try:
        data = response.json()
    except (ValueError, TypeError):
        return None

    return data if isinstance(data, dict) else None


def extract_size_ml_from_variant(variant):
    parts = [
        variant.get("title"),
        variant.get("option1"),
        variant.get("option2"),
        variant.get("option3"),
    ]

    text = " ".join(
        str(value)
        for value in parts
        if value not in (None, "")
    )

    matches = re.findall(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        text,
        flags=re.I,
    )

    if not matches:
        return None

    values = []
    for number, unit in matches:
        try:
            value = float(number.replace(",", "."))
            if unit.lower() == "cl":
                value *= 10
            values.append(value)
        except ValueError:
            continue

    return min(values) if values else None


def extract_size_ml_from_title(title):
    matches = re.findall(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        title or "",
        flags=re.I,
    )

    if not matches:
        return None

    values = []
    for number, unit in matches:
        try:
            value = float(number.replace(",", "."))
            if unit.lower() == "cl":
                value *= 10
            values.append(value)
        except ValueError:
            continue

    return min(values) if values else None


def variant_to_result(data, variant, url, brand, title):
    if not isinstance(variant, dict):
        return None

    variant_title = str(variant.get("title") or "").strip()
    full_name = title

    if variant_title and variant_title.lower() != "default title":
        full_name = f"{title} {variant_title}".strip()

    # Variant names are validated by the parent product title/query in build_results.

    price = parse_price(variant.get("price"))
    available = variant.get("available")

    if available is not True and available is not False:
        available = None

    size_ml = (
        extract_size_ml_from_variant(variant)
        or extract_size_ml_from_title(full_name)
    )

    result = {
        "store": "Bplatz",
        "brand": brand,
        "name": full_name,
        "price": money(price) if price is not None and available is not False else "",
        "price_num": price if price is not None and available is not False else None,
        "size_ml": size_ml,
        "url": url,
        "available": available,
        "availability": (
            "in_stock"
            if available is True
            else "out_of_stock"
            if available is False
            else "unknown"
        ),
        "sku": str(variant.get("sku") or "").strip(),
        "store_product_id": str(variant.get("id") or "").strip(),
    }

    return result



def build_results(data, url, query, available_hint=None):
    if not isinstance(data, dict):
        return []

    title = str(data.get("title") or "").strip()
    brand = str(data.get("vendor") or "").strip()

    if not title or contains_non_perfume_marker(title):
        return []

    if not query_matches(title, query):
        return []

    variants = data.get("variants") or []
    if not isinstance(variants, list):
        variants = []

    results = []

    for variant in variants:
        item = variant_to_result(data, variant, url, brand, title)
        if item:
            results.append(item)

    # Shopify normally provides at least one variant. If a theme returns no
    # variants, preserve a useful unknown-stock product rather than inventing
    # availability.
    if not results:
        inferred_available = (
            available_hint
            if available_hint is True or available_hint is False
            else None
        )

        results.append({
            "store": "Bplatz",
            "brand": brand,
            "name": title,
            "price": "",
            "price_num": None,
            "size_ml": extract_size_ml_from_title(title),
            "url": url,
            "available": inferred_available,
            "availability": (
                "in_stock"
                if inferred_available is True
                else "out_of_stock"
                if inferred_available is False
                else "unknown"
            ),
            "sku": "",
            "store_product_id": "",
        })

    return results


def product_worker(candidate, query):
    session = requests.Session()
    try:
        data = product_json(session, candidate["url"])
        if not data:
            return []

        return build_results(
            data,
            candidate["url"],
            query,
            candidate.get("available_hint"),
        )
    finally:
        session.close()


def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    session = requests.Session()
    try:
        candidates = predictive_products(session, query)
    finally:
        session.close()

    if not candidates:
        return []

    results = []

    # The product endpoint is independent for every candidate, so one slow
    # product cannot block the others.
    with ThreadPoolExecutor(
        max_workers=min(6, len(candidates))
    ) as executor:
        futures = [
            executor.submit(product_worker, candidate, query)
            for candidate in candidates
        ]

        for future in as_completed(futures):
            try:
                results.extend(future.result())
            except Exception:
                continue

    # Conservative deduplication. Different variants remain separate.
    seen = set()
    final = []

    for item in results:
        key = (
            urlparse(str(item.get("url") or "")).path.rstrip("/"),
            str(item.get("size_ml") or ""),
            str(item.get("price_num") or ""),
            str(item.get("available")),
        )

        if key in seen:
            continue

        seen.add(key)
        final.append(item)

    final.sort(
        key=lambda item: (
            item.get("available") is not True,
            item.get("price_num") is None,
            item.get("price_num") if item.get("price_num") is not None else 999999,
        )
    )

    return final


if __name__ == "__main__":
    for test_query in ("Liquid Brun", "9 PM", "Turathi Blue"):
        print("\nQUERY:", test_query)
        for result in search(test_query):
            print(result)
