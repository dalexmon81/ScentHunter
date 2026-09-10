"""
ScentHunter - PerfumeMarket scraper
Fast Shopify adapter.

Design goals:
- first-party Shopify search only on the live path
- predictive search + normal search in parallel
- no live sitemap crawl
- bounded candidate count
- concurrent product JSON enrichment
- variant-level size/price/stock extraction
- out-of-stock offers are retained
- no perfume-specific hardcoded rules
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.perfumemarket.nl"
STORE = "PerfumeMarket"

CONNECT_TIMEOUT = 2.5
READ_TIMEOUT = 5.0
SEARCH_WORKERS = 4
PRODUCT_WORKERS = 8
MAX_CANDIDATES = 20
MAX_RESULTS = 60

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.8",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}

PRICE_RE = re.compile(
    r"(?:€\s*)?(\d{1,5}(?:[.,]\d{2})?)(?:\s*€)?"
)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def tokens(text: Any) -> List[str]:
    return [
        x.lower()
        for x in re.findall(r"[a-z0-9]+", clean(text), re.I)
        if x
    ]


def compact(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean(text).lower())


def query_matches(text: Any, query: Any) -> bool:
    q = tokens(query)
    if not q:
        return False

    t = set(tokens(text))
    if all(x in t for x in q):
        return True

    cq = compact(query)
    ct = compact(text)
    return bool(cq and cq in ct)


def parse_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None

    text = clean(value)
    text = re.sub(r"[^\d,.\-]", "", text)

    if not text:
        return None

    # European format: 1.234,56
    if "," in text and "." in text and text.rfind(",") > text.rfind("."):
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        parts = text.split(".")
        text = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return float(text)
    except ValueError:
        return None


def format_price(value: Any) -> Optional[str]:
    number = parse_float(value)
    if number is None:
        return None
    return f"{number:.2f}".replace(".", ",") + " €"


def resolve_product_price(raw_price: Any, search_price: Optional[str] = None) -> tuple[Optional[str], Optional[float]]:
    """Normalize PerfumeMarket Shopify variant prices to euros.

    The live PerfumeMarket Shopify product payload currently exposes variant
    prices as integer cents (for example 3099 and 4299), while the storefront
    displays 30.99 EUR and 42.99 EUR. The scraper must normalize that store
    representation before returning the offer.

    If a customer-facing search price is available, it is preferred. Otherwise
    an integer-looking Shopify value is treated as cents. Decimal euro values
    such as 42.99 are left unchanged. This rule is store-wide and is not tied
    to any particular perfume.
    """
    raw_num = parse_float(raw_price)
    search_num = parse_float(search_price) if search_price else None

    if raw_num is None and search_num is None:
        return None, None

    if search_num is not None:
        # Search/collection cards are already customer-facing euro values.
        # Use them as the authoritative display price.
        if raw_num is None:
            return format_price(search_num), search_num

        # If the product payload is in cents, verify that it agrees with the
        # search value before accepting the search value.
        if raw_num >= 1000 and abs((raw_num / 100.0) - search_num) < 0.011:
            return format_price(search_num), search_num

        # If the product payload already uses euros, keep it.
        if abs(raw_num - search_num) < 0.011:
            return format_price(search_num), search_num

        # Conflicting sources: prefer the customer-facing storefront value.
        return format_price(search_num), search_num

    if raw_num is None:
        return None, None

    # PerfumeMarket's Shopify product JSON uses integer cents for prices.
    # Values such as 3099 and 4299 therefore mean 30.99 and 42.99 EUR.
    # Decimal euro values (42.99) remain untouched.
    if raw_num >= 1000 and float(raw_num).is_integer():
        euro_num = raw_num / 100.0
        return format_price(euro_num), euro_num

    return format_price(raw_num), raw_num


def parse_price_text(text: Any) -> Optional[str]:
    text = clean(text)
    if not text:
        return None

    # Prefer values adjacent to the euro symbol.
    euro_patterns = (
        r"€\s*(\d{1,5}(?:[.,]\d{2})?)",
        r"(\d{1,5}(?:[.,]\d{2})?)\s*€",
    )
    for pattern in euro_patterns:
        match = re.search(pattern, text)
        if match:
            return format_price(match.group(1))

    return None


def parse_size_ml(value: Any) -> Optional[float]:
    text = clean(value).lower().replace(",", ".")
    if not text:
        return None

    # Explicit ml/cl only. Never infer a size from a bare number.
    match = re.search(r"(\d+(?:\.\d+)?)\s*ml\b", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None

    match = re.search(r"(\d+(?:\.\d+)?)\s*cl\b", text)
    if match:
        try:
            return float(match.group(1)) * 10.0
        except ValueError:
            return None

    return None


def size_label(value: Any, size_ml: Optional[float]) -> Optional[str]:
    text = clean(value)
    if text and re.search(r"\b(?:ml|cl)\b", text, re.I):
        return text

    if size_ml is None:
        return None

    if float(size_ml).is_integer():
        return f"{int(size_ml)} ml"
    return f"{size_ml:g} ml"


def normalize_url(url: Any) -> str:
    value = urljoin(BASE_URL, clean(url))
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        return ""
    if parsed.netloc and "perfumemarket" not in parsed.netloc.lower():
        return ""
    return value.split("?", 1)[0].rstrip("/")


def request_json(session: requests.Session, url: str) -> Optional[Any]:
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        if not response.ok:
            return None
        return response.json()
    except (requests.RequestException, ValueError, TypeError):
        return None


def request_text(session: requests.Session, url: str) -> Optional[str]:
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        if not response.ok:
            return None
        return response.text
    except requests.RequestException:
        return None


# ---------------------------------------------------------------------------
# Shopify discovery
# ---------------------------------------------------------------------------

def parse_predictive(payload: Any, query: str) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    resources = payload.get("resources") or {}
    if not isinstance(resources, dict):
        return []

    nested = resources.get("results") or {}
    if not isinstance(nested, dict):
        return []

    products = nested.get("products") or []
    if not isinstance(products, list):
        return []

    results: List[Dict[str, Any]] = []

    for product in products:
        if not isinstance(product, dict):
            continue

        name = clean(product.get("title") or product.get("name"))
        url = normalize_url(product.get("url"))

        if not name or not url or "/products/" not in url.lower():
            continue

        if not query_matches(name + " " + url, query):
            continue

        results.append(
            {
                "url": url,
                "name": name,
                "source": "predictive",
            }
        )

    return results


def parse_search_html(html: str, query: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    results: List[Dict[str, Any]] = []
    seen = set()

    selectors = [
        "a[href*='/products/']",
        "[data-product-handle] a[href]",
        ".card a[href]",
        ".product-card a[href]",
    ]

    links = []
    for selector in selectors:
        links.extend(soup.select(selector))

    if not links:
        links = soup.find_all("a", href=True)

    for link in links:
        url = normalize_url(link.get("href"))
        if not url or "/products/" not in url.lower():
            continue

        key = url.lower()
        if key in seen:
            continue

        node = link
        card = None

        for _ in range(7):
            if node is None:
                break
            text = clean(node.get_text(" ", strip=True))
            if len(text) <= 2200 and (
                parse_price_text(text)
                or query_matches(text, query)
            ):
                card = node
                break
            node = getattr(node, "parent", None)

        if card is None:
            card = link.parent

        card_text = clean(card.get_text(" ", strip=True)) if card else ""
        title = ""

        for selector in (
            "h1", "h2", "h3", "h4",
            ".product-title", ".product__title",
            ".product-name", ".card__heading",
            "[class*='product-title']", "[class*='product-name']",
        ):
            try:
                element = card.select_one(selector) if card else None
            except Exception:
                element = None

            if element:
                title = clean(element.get_text(" ", strip=True))
                if title:
                    break

        if not title:
            title = clean(
                link.get("title")
                or link.get("aria-label")
                or link.get_text(" ", strip=True)
            )

        if not title:
            title = url.rsplit("/products/", 1)[-1].replace("-", " ")

        if not query_matches(f"{title} {card_text} {url}", query):
            continue

        seen.add(key)
        results.append(
            {
                "url": url,
                "name": title,
                "price": parse_price_text(card_text),
                "source": "search_html",
            }
        )

        if len(results) >= MAX_CANDIDATES:
            break

    return results


def discovery_request(session: requests.Session, url: str, kind: str, query: str):
    if kind == "predictive":
        payload = request_json(session, url)
        return parse_predictive(payload, query)

    html = request_text(session, url)
    return parse_search_html(html or "", query)


def discover(session: requests.Session, query: str) -> List[Dict[str, Any]]:
    encoded = quote(query)

    urls = [
        (
            BASE_URL
            + "/search/suggest.json?q="
            + encoded
            + "&resources[type]=product"
            + "&resources[limit]=20"
            + "&resources[options][unavailable_products]=last",
            "predictive",
        ),
        (
            BASE_URL
            + "/search?q="
            + encoded
            + "&type=product"
            + "&options%5Bprefix%5D=last"
            + "&options%5Bunavailable_products%5D=last",
            "html",
        ),
        (
            BASE_URL
            + "/search?q="
            + encoded
            + "&type=product",
            "html",
        ),
        (
            BASE_URL + "/search?q=" + encoded,
            "html",
        ),
    ]

    found: List[Dict[str, Any]] = []
    seen = set()

    # These are independent HTTP requests, so do not serialize them.
    with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as executor:
        futures = [
            executor.submit(discovery_request, session, url, kind, query)
            for url, kind in urls
        ]

        for future in as_completed(futures):
            try:
                items = future.result() or []
            except Exception:
                items = []

            for item in items:
                url = normalize_url(item.get("url"))
                if not url:
                    continue

                key = url.lower()
                if key in seen:
                    continue

                seen.add(key)
                found.append(item)

                if len(found) >= MAX_CANDIDATES:
                    break

            if len(found) >= MAX_CANDIDATES:
                break

    return found[:MAX_CANDIDATES]


# ---------------------------------------------------------------------------
# Product JSON / HTML enrichment
# ---------------------------------------------------------------------------

def product_json_url(product_url: str) -> str:
    return product_url.rstrip("/") + ".js"


def brand_from_product(product: Dict[str, Any], title: str) -> Optional[str]:
    vendor = clean(product.get("vendor"))
    if vendor:
        return vendor

    # Shopify titles frequently start with the brand, but only use this as a
    # conservative fallback; never manufacture a brand from arbitrary text.
    parts = clean(title).split()
    if parts:
        return parts[0]
    return None


def concentration_from_text(text: Any) -> Optional[str]:
    value = clean(text)
    if not value:
        return None

    patterns = (
        (r"\bextrait(?:\s+de)?\s+parfum\b", "Extrait de Parfum"),
        (r"\bparfum\b", "Parfum"),
        (r"\beau\s+de\s+parfum\b", "EDP"),
        (r"\bedp\b", "EDP"),
        (r"\beau\s+de\s+toilette\b", "EDT"),
        (r"\bedt\b", "EDT"),
        (r"\beau\s+de\s+cologne\b", "EDC"),
        (r"\bedc\b", "EDC"),
    )

    lower = value.lower()
    for pattern, label in patterns:
        if re.search(pattern, lower):
            return label

    return None


def availability_from_variant(variant: Dict[str, Any]) -> Optional[bool]:
    if "available" in variant:
        value = variant.get("available")
        if isinstance(value, bool):
            return value

    inventory = variant.get("inventory_quantity")
    if isinstance(inventory, (int, float)):
        return inventory > 0

    return None


def variant_option_text(variant: Dict[str, Any]) -> str:
    values = []

    for key in ("option1", "option2", "option3"):
        value = clean(variant.get(key))
        if value:
            values.append(value)

    options = variant.get("options")
    if isinstance(options, list):
        values.extend(clean(x) for x in options if clean(x))

    return " ".join(dict.fromkeys(values))


def extract_image(product: Dict[str, Any], variant: Dict[str, Any]) -> Optional[str]:
    image = variant.get("featured_image")
    if isinstance(image, dict):
        image = image.get("src") or image.get("url")

    if image:
        return normalize_url(image)

    images = product.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            return normalize_url(first.get("src") or first.get("url"))
        return normalize_url(first)

    return None


def variant_result(
    product: Dict[str, Any],
    variant: Dict[str, Any],
    product_url: str,
    fallback_name: str,
    search_price: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    title = clean(product.get("title") or fallback_name)
    option_text = variant_option_text(variant)

    full_name = clean(f"{title} {option_text}")

    size_ml = parse_size_ml(option_text) or parse_size_ml(title)
    size = size_label(option_text, size_ml)

    raw_price = variant.get("price")
    price, price_num = resolve_product_price(raw_price, search_price)

    available = availability_from_variant(variant)

    variant_id = clean(variant.get("id"))
    sku = clean(variant.get("sku"))
    barcode = clean(variant.get("barcode"))

    concentration = concentration_from_text(full_name)
    brand = brand_from_product(product, title)
    image = extract_image(product, variant)

    # Keep an offer even when price is absent: this is important for OOS.
    if available is None and price is None:
        # Unknown product state with no price is not useful to the comparison
        # engine unless the product itself is explicitly represented.
        return None

    availability = (
        "in_stock"
        if available is True
        else "out_of_stock"
        if available is False
        else "unknown"
    )

    result = {
        "store": STORE,
        "shop": STORE,
        "name": title,
        "brand": brand,
        "price": price or "",
        "price_num": price_num,
        "url": product_url,
        "available": available,
        "in_stock": available,
        "availability": availability,
        "size": size,
        "size_ml": size_ml,
        "concentration": concentration,
        "image": image,
        "sku": sku or None,
        "gtin": barcode or None,
        "mpn": sku or None,
        "store_product_id": clean(product.get("id")) or None,
        "store_variant_id": variant_id or None,
        "source": {
            "store": STORE,
            "method": "shopify_product_js",
            "product_url": product_url,
        },
        "identity": {
            "brand": brand,
            "name": title,
            "sku": sku or None,
            "gtin": barcode or None,
            "mpn": sku or None,
            "store_product_id": clean(product.get("id")) or None,
            "store_variant_id": variant_id or None,
        },
        "attributes": {
            "size": size,
            "size_ml": size_ml,
            "concentration": concentration,
            "option_text": option_text or None,
        },
        "offer": {
            "price": price or "",
            "price_num": price_num,
            "available": available,
            "availability": availability,
        },
        "provenance": {
            "discovery": "shopify_search",
            "enrichment": "shopify_product_js",
        },
        "raw_data": {
            "product_id": product.get("id"),
            "variant_id": variant.get("id"),
            "variant_title": variant.get("title"),
        },
    }

    return result


def parse_product_json(
    payload: Any,
    product_url: str,
    query: str,
    search_item: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    title = clean(payload.get("title") or search_item.get("name"))
    if not title:
        return []

    if not query_matches(title + " " + product_url, query):
        return []

    variants = payload.get("variants")
    if not isinstance(variants, list):
        variants = []

    results: List[Dict[str, Any]] = []

    if variants:
        for variant in variants:
            if not isinstance(variant, dict):
                continue

            item = variant_result(
                payload,
                variant,
                product_url,
                title,
                search_price=search_item.get("price"),
            )
            if item:
                results.append(item)
    else:
        # Some Shopify themes expose a product object without a variants array.
        # Preserve the product rather than silently losing it.
        fake_variant = {
            "price": payload.get("price"),
            "available": payload.get("available"),
        }
        item = variant_result(
            payload,
            fake_variant,
            product_url,
            title,
            search_price=search_item.get("price"),
        )
        if item:
            results.append(item)

    return results


def parse_product_html(
    html: str,
    product_url: str,
    query: str,
    search_item: Dict[str, Any],
) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")

    title = ""
    for selector in (
        "h1",
        "meta[property='og:title']",
        "title",
    ):
        element = soup.select_one(selector)
        if not element:
            continue

        title = clean(
            element.get("content")
            if element.name == "meta"
            else element.get_text(" ", strip=True)
        )
        if title:
            break

    if not title or not query_matches(title + " " + product_url, query):
        return []

    price = search_item.get("price") or parse_price_text(
        soup.get_text(" ", strip=True)
    )

    available = None
    page_text = soup.get_text(" ", strip=True).lower()

    if any(
        marker in page_text
        for marker in (
            "out of stock",
            "sold out",
            "rupture de stock",
            "ausverkauft",
        )
    ):
        available = False

    if any(
        marker in page_text
        for marker in (
            "add to cart",
            "ajouter au panier",
            "in den warenkorb",
            "add to bag",
        )
    ):
        available = True

    # JSON-LD fallback.
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue

        objects = data if isinstance(data, list) else [data]

        for obj in objects:
            if not isinstance(obj, dict):
                continue

            offers = obj.get("offers")
            if isinstance(offers, dict):
                offers = [offers]

            if not isinstance(offers, list):
                continue

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                if not price:
                    price = format_price(offer.get("price"))

                stock = clean(offer.get("availability")).lower()
                if stock.endswith("instock"):
                    available = True
                elif stock.endswith("outofstock"):
                    available = False

    if not price and available is not False:
        return []

    brand = None
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(" ", strip=True)
        try:
            data = json.loads(raw)
        except Exception:
            continue

        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            value = obj.get("brand")
            if isinstance(value, dict):
                value = value.get("name")
            if value:
                brand = clean(value)
                break
        if brand:
            break

    size_ml = parse_size_ml(title)
    size = size_label(title, size_ml)
    concentration = concentration_from_text(title)

    item = {
        "store": STORE,
        "shop": STORE,
        "name": title,
        "brand": brand,
        "price": price or "",
        "price_num": parse_float(price),
        "url": product_url,
        "available": available,
        "in_stock": available,
        "availability": (
            "in_stock"
            if available is True
            else "out_of_stock"
            if available is False
            else "unknown"
        ),
        "size": size,
        "size_ml": size_ml,
        "concentration": concentration,
        "image": None,
        "sku": None,
        "gtin": None,
        "mpn": None,
        "store_product_id": None,
        "store_variant_id": None,
        "source": {
            "store": STORE,
            "method": "shopify_product_html_fallback",
            "product_url": product_url,
        },
        "identity": {
            "brand": brand,
            "name": title,
        },
        "attributes": {
            "size": size,
            "size_ml": size_ml,
            "concentration": concentration,
        },
        "offer": {
            "price": price or "",
            "price_num": parse_float(price),
            "available": available,
            "availability": (
                "in_stock"
                if available is True
                else "out_of_stock"
                if available is False
                else "unknown"
            ),
        },
        "provenance": {
            "discovery": "shopify_search",
            "enrichment": "shopify_product_html_fallback",
        },
        "raw_data": {},
    }

    return [item]


def enrich_candidate(
    candidate: Dict[str, Any],
    query: str,
) -> List[Dict[str, Any]]:
    url = normalize_url(candidate.get("url"))
    if not url:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        payload = request_json(session, product_json_url(url))
        if payload:
            results = parse_product_json(payload, url, query, candidate)
            if results:
                return results

        html = request_text(session, url)
        if html:
            return parse_product_html(html, url, query, candidate)

        return []
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Public scraper API
# ---------------------------------------------------------------------------

def dedupe_results(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    seen = set()

    for item in results:
        if not isinstance(item, dict):
            continue

        key = (
            clean(item.get("url")).lower(),
            clean(item.get("store_variant_id") or item.get("sku")).lower(),
            clean(item.get("size_ml")),
            clean(item.get("price_num")),
            clean(item.get("available")),
        )

        if key in seen:
            continue

        seen.add(key)
        output.append(item)

    # Available first, unknown next, out of stock last.
    def rank(item: Dict[str, Any]) -> int:
        value = item.get("available")
        if value is True:
            return 0
        if value is None:
            return 1
        return 2

    output.sort(key=rank)
    return output[:MAX_RESULTS]


def search(query: str) -> List[Dict[str, Any]]:
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        candidates = discover(session, query)
    finally:
        session.close()

    if not candidates:
        return []

    results: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=PRODUCT_WORKERS) as executor:
        future_map = {
            executor.submit(enrich_candidate, candidate, query): candidate
            for candidate in candidates[:MAX_CANDIDATES]
        }

        for future in as_completed(future_map):
            try:
                results.extend(future.result() or [])
            except Exception as exc:
                print(f"PERFUMEMARKET PRODUCT ERROR: {exc}")

    return dedupe_results(results)


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)


def search_perfumemarket(query: str) -> List[Dict[str, Any]]:
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ScentHunter PerfumeMarket scraper")
    parser.add_argument("query", nargs="+")
    args = parser.parse_args()

    query = " ".join(args.query)
    data = search(query)
    print(json.dumps(data, ensure_ascii=False, indent=2))
