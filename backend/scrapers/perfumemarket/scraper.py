"""ScentHunter - PerfumeMarket generic Shopify adapter.

Only store-specific technical knowledge lives here. Canonical product identity,
family and variant decisions belong to ProductMatcher.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "PerfumeMarket"
BASE_URL = "https://www.perfumemarket.nl"
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 7.0
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)
PRODUCT_WORKERS = 8
MAX_CANDIDATES = 30
MAX_RESULTS = 80

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.8",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}


class StoreRequestError(RuntimeError):
    def __init__(self, status, message, url=None, http_status=None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.http_status = http_status


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def tokens(value: Any) -> List[str]:
    return re.findall(r"[a-z0-9]+", clean(value).lower())


def query_matches(text: Any, query: Any) -> bool:
    wanted = [x for x in tokens(query) if len(x) > 1]
    if not wanted:
        return False
    hay = set(tokens(text))
    if all(x in hay for x in wanted):
        return True
    compact_q = re.sub(r"[^a-z0-9]+", "", clean(query).lower())
    compact_t = re.sub(r"[^a-z0-9]+", "", clean(text).lower())
    return bool(compact_q and compact_q in compact_t)


def parse_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        return n if 0 < n < 1000000 else None

    text = clean(value)
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text:
        return None

    if "," in text and "." in text and text.rfind(",") > text.rfind("."):
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        parts = text.split(".")
        text = "".join(parts[:-1]) + "." + parts[-1]

    try:
        n = float(text)
    except ValueError:
        return None
    return n if 0 < n < 1000000 else None


def format_price(value: Any) -> Optional[str]:
    n = parse_float(value)
    return f"{n:.2f}".replace(".", ",") + " €" if n is not None else None


def resolve_price(raw_price: Any, search_price: Any = None):
    raw = parse_float(raw_price)
    displayed = parse_float(search_price)

    if raw is None and displayed is None:
        return None, None

    # PerfumeMarket Shopify product JSON uses integer cents for large
    # integer-looking values; customer-facing search cards use euros.
    if displayed is not None:
        return format_price(displayed), displayed

    if raw is not None and raw >= 1000 and raw.is_integer():
        raw = raw / 100.0

    return format_price(raw), raw


def parse_price_text(text: Any) -> Optional[str]:
    text = clean(text)
    for pattern in (
        r"€\s*(\d{1,5}(?:[.,]\d{2})?)",
        r"(\d{1,5}(?:[.,]\d{2})?)\s*€",
    ):
        match = re.search(pattern, text)
        if match:
            return format_price(match.group(1))
    return None


def parse_size_ml(value: Any) -> Optional[float]:
    text = clean(value).lower().replace(",", ".")
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(ml|cl)\b", text)
    if not match:
        return None
    n = float(match.group(1))
    if match.group(2) == "cl":
        n *= 10
    return int(n) if n.is_integer() else n


def size_label(value: Any, size_ml: Optional[float]) -> Optional[str]:
    explicit = clean(value)
    if explicit and re.search(r"\b(?:ml|cl)\b", explicit, re.I):
        return explicit
    if size_ml is None:
        return None
    return f"{int(size_ml)} ml" if float(size_ml).is_integer() else f"{size_ml:g} ml"


def normalize_url(value: Any) -> str:
    url = urljoin(BASE_URL, clean(value))
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if "perfumemarket" not in parsed.netloc.lower():
        return ""
    return parsed._replace(query="", fragment="").geturl().rstrip("/")


def normalize_image_url(value: Any) -> str:
    url = urljoin(BASE_URL, clean(value))
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    host = parsed.netloc.lower()
    if (
        "perfumemarket" not in host
        and host != "cdn.shopify.com"
        and not host.endswith(".myshopify.com")
    ):
        return ""
    return url.split("?", 1)[0]


def extract_image(node):
    if node is None:
        return None
    for image in node.select("img"):
        for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-image"):
            value = normalize_image_url(image.get(attr))
            if value:
                return value
        for attr in ("srcset", "data-srcset"):
            raw = clean(image.get(attr))
            if raw:
                value = normalize_image_url(raw.split(",", 1)[0].split()[0])
                if value:
                    return value
    return None


def request(session, url, *, json_mode=False):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.Timeout as exc:
        raise StoreRequestError("timeout", "PerfumeMarket request timed out", url=url) from exc
    except requests.ConnectionError as exc:
        raise StoreRequestError("unavailable", "PerfumeMarket connection failed", url=url) from exc
    except requests.RequestException as exc:
        raise StoreRequestError(
            "error",
            f"PerfumeMarket request failed: {type(exc).__name__}",
            url=url,
        ) from exc

    status = response.status_code
    if status in (401, 403, 429):
        response.close()
        raise StoreRequestError(
            "blocked",
            f"PerfumeMarket returned HTTP {status}",
            url=url,
            http_status=status,
        )
    if status >= 500:
        response.close()
        raise StoreRequestError(
            "unavailable",
            f"PerfumeMarket returned HTTP {status}",
            url=url,
            http_status=status,
        )
    if status >= 400:
        response.close()
        raise StoreRequestError(
            "error",
            f"PerfumeMarket returned HTTP {status}",
            url=url,
            http_status=status,
        )

    try:
        return response.json() if json_mode else response.text
    except (ValueError, TypeError) as exc:
        raise StoreRequestError(
            "error",
            "PerfumeMarket returned invalid JSON",
            url=url,
        ) from exc
    finally:
        response.close()


def parse_predictive(payload, query):
    if not isinstance(payload, dict):
        return []
    resources = payload.get("resources")
    if not isinstance(resources, dict):
        return []
    nested = resources.get("results")
    if not isinstance(nested, dict):
        return []
    products = nested.get("products")
    if not isinstance(products, list):
        return []

    output = []
    for product in products:
        if not isinstance(product, dict):
            continue
        name = clean(product.get("title") or product.get("name"))
        url = normalize_url(product.get("url"))
        if not name or not url or "/products/" not in url.lower():
            continue
        if not query_matches(f"{name} {url}", query):
            continue
        output.append({
            "url": url,
            "name": name,
            "source": "predictive",
        })
    return output


def parse_search_html(html, query):
    soup = BeautifulSoup(html or "", "html.parser")
    output = []
    seen = set()

    links = soup.select("a[href*='/products/']")
    if not links:
        links = soup.find_all("a", href=True)

    for link in links:
        url = normalize_url(link.get("href"))
        if not url or "/products/" not in url.lower():
            continue
        if url.lower() in seen:
            continue

        card = link
        for _ in range(7):
            text = clean(card.get_text(" ", strip=True))
            if len(text) <= 2200 and (parse_price_text(text) or query_matches(text, query)):
                break
            card = getattr(card, "parent", None)
            if card is None:
                card = link
                break

        card_text = clean(card.get_text(" ", strip=True))
        title = ""

        for selector in (
            "h1", "h2", "h3", "h4",
            ".product-title", ".product__title",
            ".product-name", ".card__heading",
            "[class*='product-title']", "[class*='product-name']",
        ):
            element = card.select_one(selector) if card else None
            if element:
                title = clean(element.get_text(" ", strip=True))
                if title:
                    break

        if not title:
            title = clean(link.get("title") or link.get("aria-label") or link.get_text(" ", strip=True))
        if not title:
            title = url.rsplit("/products/", 1)[-1].replace("-", " ")

        if not query_matches(f"{title} {card_text} {url}", query):
            continue

        seen.add(url.lower())
        output.append({
            "url": url,
            "name": title,
            "price": parse_price_text(card_text),
            "image": extract_image(card),
            "source": "search_html",
        })

        if len(output) >= MAX_CANDIDATES:
            break

    return output


def discover(session, query):
    encoded = quote(query)
    endpoints = (
        (
            BASE_URL
            + "/search/suggest.json?q="
            + encoded
            + "&resources[type]=product"
            + "&resources[limit]=20"
            + "&resources[options][unavailable_products]=last",
            True,
        ),
        (
            BASE_URL
            + "/search?q="
            + encoded
            + "&type=product"
            + "&options%5Bprefix%5D=last"
            + "&options%5Bunavailable_products%5D=last",
            False,
        ),
        (
            BASE_URL + "/search?q=" + encoded + "&type=product",
            False,
        ),
        (
            BASE_URL + "/search?q=" + encoded,
            False,
        ),
    )

    found = []
    seen = set()
    failures = []

    for url, json_mode in endpoints:
        try:
            payload = request(session, url, json_mode=json_mode)
            items = (
                parse_predictive(payload, query)
                if json_mode
                else parse_search_html(payload, query)
            )
        except StoreRequestError as exc:
            failures.append({
                "status": exc.status,
                "url": exc.url,
                "http_status": exc.http_status,
                "message": str(exc),
            })
            continue

        for item in items:
            product_url = normalize_url(item.get("url"))
            if not product_url or product_url.lower() in seen:
                continue
            seen.add(product_url.lower())
            item["url"] = product_url
            found.append(item)
            if len(found) >= MAX_CANDIDATES:
                break

        if found or len(found) >= MAX_CANDIDATES:
            break

    return found[:MAX_CANDIDATES], failures


def product_json_url(product_url):
    return product_url.rstrip("/") + ".js"


def concentration(text):
    text = clean(text).lower()
    for pattern, value in (
        (r"\bextrait(?:\s+de)?\s+parfum\b", "Extrait de Parfum"),
        (r"\beau\s+de\s+parfum\b|\bedp\b", "EDP"),
        (r"\beau\s+de\s+toilette\b|\bedt\b", "EDT"),
        (r"\beau\s+de\s+cologne\b|\bedc\b", "EDC"),
        (r"\bparfum\b", "Parfum"),
    ):
        if re.search(pattern, text):
            return value
    return None


def product_brand(product):
    vendor = clean(product.get("vendor"))
    return vendor or None


def availability(variant):
    if isinstance(variant.get("available"), bool):
        return "in_stock" if variant["available"] else "out_of_stock"
    quantity = variant.get("inventory_quantity")
    if isinstance(quantity, (int, float)):
        return "in_stock" if quantity > 0 else "out_of_stock"
    return "unknown"


def option_text(variant):
    values = []
    for key in ("option1", "option2", "option3"):
        value = clean(variant.get(key))
        if value:
            values.append(value)
    options = variant.get("options")
    if isinstance(options, list):
        values.extend(clean(x) for x in options if clean(x))
    return " ".join(dict.fromkeys(values))


def product_image(product, variant):
    image = variant.get("featured_image")
    if isinstance(image, dict):
        image = image.get("src") or image.get("url")
    if image:
        return normalize_image_url(image)

    images = product.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            first = first.get("src") or first.get("url")
        return normalize_image_url(first)
    return None


def make_result(product, variant, url, search_item):
    title = clean(product.get("title") or search_item.get("name"))
    if not title or not query_matches(f"{title} {url}", search_item.get("_query")):
        return None

    options = option_text(variant)
    full_text = clean(f"{title} {options}")
    size_ml = parse_size_ml(options) or parse_size_ml(title)
    price, price_num = resolve_price(
        variant.get("price"),
        search_item.get("price"),
    )

    state = availability(variant)
    if state == "unknown" and price is None:
        return None

    sku = clean(variant.get("sku")) or None
    barcode = clean(variant.get("barcode")) or None
    variant_id = clean(variant.get("id")) or None
    product_id = clean(product.get("id")) or None
    brand = product_brand(product)
    image = product_image(product, variant)

    return {
        "store": STORE,
        "shop": STORE,
        "name": title,
        "brand": brand,
        "price": price or "",
        "price_num": price_num,
        "url": url,
        "available": (
            True if state == "in_stock"
            else False if state == "out_of_stock"
            else None
        ),
        "in_stock": (
            True if state == "in_stock"
            else False if state == "out_of_stock"
            else None
        ),
        "availability": state,
        "size": size_label(options, size_ml),
        "size_ml": size_ml,
        "concentration": concentration(full_text),
        "image": image,
        "sku": sku,
        "gtin": barcode,
        "mpn": sku,
        "store_product_id": product_id,
        "store_variant_id": variant_id,
        "source": {
            "store": STORE,
            "method": "shopify_product_js",
            "product_url": url,
        },
        "identity": {
            "brand": brand,
            "name": title,
            "sku": sku,
            "gtin": barcode,
            "mpn": sku,
            "store_product_id": product_id,
            "store_variant_id": variant_id,
        },
        "attributes": {
            "size": size_label(options, size_ml),
            "size_ml": size_ml,
            "concentration": concentration(full_text),
            "option_text": options or None,
        },
        "offer": {
            "price": price or "",
            "price_num": price_num,
            "available": (
                True if state == "in_stock"
                else False if state == "out_of_stock"
                else None
            ),
            "availability": state,
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


def parse_product_json(payload, url, search_item, query):
    if not isinstance(payload, dict):
        return []

    title = clean(payload.get("title") or search_item.get("name"))
    if not title or not query_matches(f"{title} {url}", query):
        return []

    variants = payload.get("variants")
    if not isinstance(variants, list) or not variants:
        variants = [{
            "price": payload.get("price"),
            "available": payload.get("available"),
        }]

    item = dict(search_item)
    item["_query"] = query
    results = []

    for variant in variants:
        if not isinstance(variant, dict):
            continue
        row = make_result(payload, variant, url, item)
        if row:
            results.append(row)

    return results


def parse_product_html(html, url, search_item, query):
    soup = BeautifulSoup(html or "", "html.parser")
    title = ""

    for selector in ("h1", "meta[property='og:title']", "title"):
        node = soup.select_one(selector)
        if not node:
            continue
        title = clean(
            node.get("content")
            if node.name == "meta"
            else node.get_text(" ", strip=True)
        )
        if title:
            break

    if not title or not query_matches(f"{title} {url}", query):
        return []

    price = search_item.get("price")
    if not price:
        price = parse_price_text(soup.get_text(" ", strip=True))

    page = soup.get_text(" ", strip=True).lower()
    state = "unknown"
    if any(x in page for x in ("out of stock", "sold out", "ausverkauft", "rupture de stock")):
        state = "out_of_stock"
    elif any(x in page for x in ("add to cart", "add to bag", "in den warenkorb", "ajouter au panier")):
        state = "in_stock"

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
                    state = "in_stock"
                elif stock.endswith("outofstock"):
                    state = "out_of_stock"

    if not price and state == "unknown":
        return []

    image = None
    node = soup.select_one(
        "meta[property='og:image'], meta[property='og:image:url'], meta[name='twitter:image']"
    )
    if node:
        image = normalize_image_url(node.get("content"))

    brand = None
    size_ml = parse_size_ml(title)
    size = size_label(title, size_ml)

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

    available = True if state == "in_stock" else False if state == "out_of_stock" else None
    price_num = parse_float(price)

    return [{
        "store": STORE,
        "shop": STORE,
        "name": title,
        "brand": brand,
        "price": price or "",
        "price_num": price_num,
        "url": url,
        "available": available,
        "in_stock": available,
        "availability": state,
        "size": size,
        "size_ml": size_ml,
        "concentration": concentration(title),
        "image": image,
        "sku": None,
        "gtin": None,
        "mpn": None,
        "store_product_id": None,
        "store_variant_id": None,
        "source": {
            "store": STORE,
            "method": "shopify_product_html_fallback",
            "product_url": url,
        },
        "identity": {"brand": brand, "name": title},
        "attributes": {
            "size": size,
            "size_ml": size_ml,
            "concentration": concentration(title),
        },
        "offer": {
            "price": price or "",
            "price_num": price_num,
            "available": available,
            "availability": state,
        },
        "provenance": {
            "discovery": "shopify_search",
            "enrichment": "shopify_product_html_fallback",
        },
        "raw_data": {},
    }]


def enrich(candidate, query):
    url = normalize_url(candidate.get("url"))
    if not url:
        return [], {"status": "partial", "reason": "invalid_url"}

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        try:
            payload = request(session, product_json_url(url), json_mode=True)
            results = parse_product_json(payload, url, candidate, query)
            if results:
                return results, {"status": "success", "url": url}
        except StoreRequestError as exc:
            json_error = {
                "status": exc.status,
                "url": exc.url,
                "http_status": exc.http_status,
                "message": str(exc),
            }
        else:
            json_error = None

        try:
            html = request(session, url)
            results = parse_product_html(html, url, candidate, query)
            if results:
                return results, {"status": "success", "url": url}
        except StoreRequestError as exc:
            html_error = {
                "status": exc.status,
                "url": exc.url,
                "http_status": exc.http_status,
                "message": str(exc),
            }
        else:
            html_error = None

        # A verified search card is still a real discovery result. Preserve
        # it with unknown availability rather than converting an enrichment
        # failure into NOT_FOUND.
        name = clean(candidate.get("name"))
        if name and query_matches(f"{name} {url}", query):
            size_ml = parse_size_ml(name)
            price = candidate.get("price")
            return [{
                "store": STORE,
                "shop": STORE,
                "name": name,
                "brand": None,
                "price": price or "",
                "price_num": parse_float(price),
                "url": url,
                "available": None,
                "in_stock": None,
                "availability": "unknown",
                "size": size_label(name, size_ml),
                "size_ml": size_ml,
                "concentration": concentration(name),
                "image": candidate.get("image"),
                "sku": None,
                "gtin": None,
                "mpn": None,
                "store_product_id": None,
                "store_variant_id": None,
                "source": {
                    "store": STORE,
                    "method": "shopify_search_candidate",
                    "product_url": url,
                },
                "identity": {"name": name},
                "attributes": {
                    "size": size_label(name, size_ml),
                    "size_ml": size_ml,
                    "concentration": concentration(name),
                },
                "offer": {
                    "price": price or "",
                    "price_num": parse_float(price),
                    "available": None,
                    "availability": "unknown",
                },
                "provenance": {
                    "discovery": "shopify_search",
                    "enrichment": "search_candidate_fallback",
                },
                "raw_data": {},
            }], {
                "status": "partial",
                "url": url,
                "errors": [json_error, html_error],
            }

        return [], {
            "status": "partial",
            "url": url,
            "errors": [json_error, html_error],
        }
    except Exception as exc:
        return [], {
            "status": "error",
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        session.close()


def dedupe(rows):
    out = []
    seen = set()
    for row in rows:
        key = (
            row.get("url"),
            row.get("store_variant_id"),
            row.get("size_ml"),
            row.get("price_num"),
            row.get("availability"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out[:MAX_RESULTS]


def search_stream(query):
    query = clean(query)
    started = time.perf_counter()

    if not query:
        yield {
            "status": "success",
            "verified": True,
            "results": [],
            "error": None,
            "details": {"reason": "empty_query"},
        }
        return

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        try:
            candidates, discovery_failures = discover(session, query)
        except Exception as exc:
            candidates = []
            discovery_failures = [{
                "status": "error",
                "message": f"{type(exc).__name__}: {exc}",
            }]
    finally:
        session.close()

    if not candidates:
        verified = not discovery_failures
        yield {
            "status": "success" if verified else discovery_failures[0]["status"],
            "verified": verified,
            "results": [],
            "error": None if verified else discovery_failures,
            "details": {
                "stage": "discovery",
                "candidate_count": 0,
                "elapsed": round(time.perf_counter() - started, 3),
            },
        }
        return

    results = []
    errors = []

    with ThreadPoolExecutor(
        max_workers=min(PRODUCT_WORKERS, len(candidates))
    ) as pool:
        futures = {
            pool.submit(enrich, candidate, query): candidate
            for candidate in candidates
        }

        for future in as_completed(futures):
            try:
                rows, meta = future.result()
            except Exception as exc:
                rows, meta = [], {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            results.extend(rows)
            if meta.get("status") not in {"success", "partial"}:
                errors.append(meta)

    results = dedupe(results)

    if results and (errors or discovery_failures):
        status, verified = "partial", True
    elif results:
        status, verified = "success", True
    elif errors:
        status, verified = "partial", False
    else:
        status, verified = "success", True

    yield {
        "status": status,
        "verified": verified,
        "results": results,
        "error": errors or discovery_failures or None,
        "details": {
            "stage": "product_fetch",
            "candidate_count": len(candidates),
            "result_count": len(results),
            "error_count": len(errors),
            "elapsed": round(time.perf_counter() - started, 3),
        },
    }


def search(query):
    return next(search_stream(query)).get("results", [])


def scrape(query):
    return search(query)


def search_perfumemarket(query):
    return search(query)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generic PerfumeMarket scraper")
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(next(search_stream(args.query)), ensure_ascii=False, indent=2))
