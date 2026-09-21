"""ScentHunter - Sabina generic store adapter.

Store-specific knowledge only:
- Sabina URL structure and search endpoints;
- HTML/JSON-LD extraction;
- product-page commercial fields;
- explicit variant blocks.

Canonical product identity remains the responsibility of ProductMatcher.
No perfume-specific URL, product id, price, family, alias or fallback exists here.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = (3.0, 7.0)
MAX_CANDIDATES = 40
MAX_RESULTS = 80
PRODUCT_WORKERS = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/json;"
        "q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": BASE + "/es/",
}

OUT_MARKERS = (
    "out of stock", "sold out", "unavailable",
    "not available", "producto no disponible",
    "producto agotado", "sin stock", "agotado",
    "no disponible", "nicht verfügbar", "ausverkauft",
)
IN_MARKERS = (
    "in stock", "available", "available now", "add to cart",
    "añadir al carrito", "en stock", "disponible",
    "disponibilidad inmediata", "auf lager",
)
NON_PRODUCT_TERMS = (
    "gift set", "giftset", "geschenkset", "coffret",
    "duo", "trio", "tester", "sample", "muestra",
    "miniature", "travel size", "travel-size",
    "after shave", "aftershave", "deodorant", "shampoo",
    "body lotion", "body cream", "cream", "crema",
    "serum", "makeup", "make up",
)


class StoreRequestError(RuntimeError):
    def __init__(self, status, message, url=None, http_status=None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.http_status = http_status


def _clean(value):
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


def _norm(value):
    text = _clean(value).casefold()
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9à-ÿäöüß]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value):
    return re.findall(r"[a-z0-9à-ÿäöüß]+", _norm(value))


def _query_tokens(query):
    return [x for x in _tokens(query) if len(x) > 1]


def _price_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        return round(n, 2) if 0 < n < 100000 else None
    raw = _clean(value)
    m = re.search(
        r"(?<!\d)(\d{1,3}(?:\.\d{3})*,\d{2}|\d+(?:[.,]\d{2})|\d+(?:\.\d{2}))(?!\d)",
        raw,
    )
    if not m:
        return None
    n = m.group(1)
    if "," in n:
        n = n.replace(".", "").replace(",", ".")
    try:
        n = float(n)
    except ValueError:
        return None
    return round(n, 2) if 0 < n < 100000 else None


def _price_text(value):
    n = _price_number(value)
    return f"{n:.2f}".replace(".", ",") + " €" if n is not None else None


def _size_ml(value):
    m = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl|dl|l)\b",
        _clean(value), re.I,
    )
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    unit = m.group(2).lower()
    if unit == "cl":
        n *= 10
    elif unit == "dl":
        n *= 100
    elif unit == "l":
        n *= 1000
    return int(n) if n.is_integer() else n


def _concentration(value):
    text = _norm(value)
    if "eau de toilette" in text or re.search(r"\bedt\b", text):
        return "Eau de Toilette"
    if "eau de parfum" in text or re.search(r"\bedp\b", text):
        return "Eau de Parfum"
    if "extrait de parfum" in text or re.search(r"\bextrait\b", text):
        return "Extrait de Parfum"
    if re.search(r"\bparfum\b", text):
        return "Parfum"
    return ""


def _availability(value):
    text = _norm(value)
    if any(x in text for x in OUT_MARKERS):
        return "out_of_stock"
    if any(x in text for x in IN_MARKERS):
        return "in_stock"
    compact = text.replace(" ", "")
    if "outofstock" in compact or "soldout" in compact:
        return "out_of_stock"
    if "instock" in compact or "limitedavailability" in compact:
        return "in_stock"
    return "unknown"


def _product_url(raw):
    raw = _clean(raw)
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = urljoin(BASE, raw)
    elif not re.match(r"^https?://", raw, re.I):
        raw = urljoin(BASE + "/", raw)
    parsed = urlparse(raw)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host not in {"sabina.com", "www.sabina.com"}:
        return ""
    path = parsed.path
    if not re.search(r"/(?:it|fr|en|es|de|pt)/", path, re.I):
        return ""
    if any(
        x in path.casefold()
        for x in (
            "/buscar", "/search", "/ricerca", "/content",
            "/marchi", "/negozi", "/contatto", "/faq",
            "/carrello", "/ordine", "/module", "/modules",
        )
    ):
        return ""
    return parsed._replace(
        netloc="www.sabina.com", query="", fragment=""
    ).geturl()


def _matches_query(name, url, query):
    wanted = _query_tokens(query)
    if not wanted:
        return False
    hay = _norm(f"{name} {url.replace('-', ' ')}")
    return all(token in hay for token in wanted)


def _is_non_product(name, url=""):
    hay = _norm(f"{name} {url.replace('-', ' ')}")
    return any(_norm(term) in hay for term in NON_PRODUCT_TERMS)


def _request(session, url, method="GET", params=None, data=None, ajax=False):
    headers = dict(HEADERS)
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
    try:
        response = session.request(
            method, url, params=params, data=data, headers=headers,
            timeout=TIMEOUT, allow_redirects=True,
        )
    except requests.Timeout as exc:
        raise StoreRequestError("timeout", "Sabina request timed out", url=url) from exc
    except requests.ConnectionError as exc:
        raise StoreRequestError("unavailable", "Sabina connection failed", url=url) from exc
    except requests.RequestException as exc:
        raise StoreRequestError(
            "error", f"Sabina request failed: {type(exc).__name__}", url=url
        ) from exc

    if response.status_code in (401, 403):
        response.close()
        raise StoreRequestError("blocked", f"Sabina returned HTTP {response.status_code}",
                                url=url, http_status=response.status_code)
    if response.status_code == 429:
        response.close()
        raise StoreRequestError("blocked", "Sabina rate-limited the request",
                                url=url, http_status=429)
    if response.status_code >= 500:
        response.close()
        raise StoreRequestError("unavailable", f"Sabina returned HTTP {response.status_code}",
                                url=url, http_status=response.status_code)
    if response.status_code >= 400:
        response.close()
        raise StoreRequestError("error", f"Sabina returned HTTP {response.status_code}",
                                url=url, http_status=response.status_code)
    return response


def _jsonld_objects(soup):
    out = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        queue = [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
            elif isinstance(item, dict):
                out.append(item)
                graph = item.get("@graph")
                if isinstance(graph, list):
                    queue.extend(graph)
    return out


def _jsonld_products(soup):
    out = []
    for item in _jsonld_objects(soup):
        typ = item.get("@type")
        types = typ if isinstance(typ, list) else [typ]
        if "Product" in types or "ProductGroup" in types:
            out.append(item)
    return out


def _jsonld_product(soup):
    products = _jsonld_products(soup)
    return products[0] if products else {}


def _value(data, *keys):
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("value") or value.get("content")
        if isinstance(value, list):
            value = value[0] if value else None
            if isinstance(value, dict):
                value = value.get("name") or value.get("value")
        if value is not None and str(value).strip():
            return _clean(value)
    return None


def _offers(product):
    offers = product.get("offers") if isinstance(product, dict) else None
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [x for x in offers if isinstance(x, dict)]
    return []


def _offer_price(offer):
    for key in ("price", "lowPrice", "salePrice", "finalPrice"):
        n = _price_number(offer.get(key))
        if n is not None:
            return n
    spec = offer.get("priceSpecification")
    if isinstance(spec, dict):
        return _price_number(spec.get("price"))
    if isinstance(spec, list):
        for item in spec:
            if isinstance(item, dict):
                n = _price_number(item.get("price"))
                if n is not None:
                    return n
    return None


def _offer_availability(offer):
    return _availability(
        offer.get("availability")
        or offer.get("itemAvailability")
        or offer.get("availabilityStatus")
        or ""
    )


def _extract_name(product, soup):
    name = _value(product, "name", "productName", "title")
    if name:
        return name
    h1 = soup.find("h1")
    if h1:
        return _clean(h1.get_text(" ", strip=True))
    title = soup.find("title")
    return _clean(title.get_text(" ", strip=True)) if title else ""


def _extract_brand(product, soup):
    brand = _value(product, "brand", "manufacturer")
    if brand:
        return brand
    node = soup.select_one('meta[property="product:brand"], meta[name="brand"]')
    return _clean(node.get("content")) if node and node.get("content") else None


def _extract_image(product, soup):
    image = product.get("image") if isinstance(product, dict) else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    if isinstance(image, list):
        image = image[0] if image else None
    if image:
        return urljoin(BASE, str(image))
    node = soup.select_one('meta[property="og:image"], meta[name="twitter:image"]')
    return urljoin(BASE, node.get("content")) if node and node.get("content") else None


def _extract_size(product, title):
    for key in ("size", "volume", "netContent", "capacity", "contentVolume"):
        size = _size_ml(_value(product, key))
        if size is not None:
            return size, f"jsonld_{key}"
    size = _size_ml(title)
    return (size, "product_title") if size is not None else (None, None)


def _extract_price(product, soup):
    for offer in _offers(product):
        n = _offer_price(offer)
        if n is not None:
            return n, str(offer.get("priceCurrency") or "EUR").upper(), "jsonld_offer"

    for selector in (
        'meta[property="product:price:amount"]',
        'meta[itemprop="price"]',
        'meta[name="price"]',
    ):
        node = soup.select_one(selector)
        if node:
            n = _price_number(node.get("content") or node.get_text(" ", strip=True))
            if n is not None:
                currency = soup.select_one(
                    'meta[property="product:price:currency"], meta[itemprop="priceCurrency"]'
                )
                return n, (
                    currency.get("content").upper()
                    if currency and currency.get("content")
                    else "EUR"
                ), "meta"

    candidates = []
    for selector in (
        '[itemprop="price"]', '[data-price]', '[data-product-price]',
        ".product-price", ".current-price", ".current_price",
        ".sale-price", ".final-price",
    ):
        for node in soup.select(selector):
            marker = (
                " ".join(node.get("class", [])).lower()
                + " " + str(node.get("id", "")).lower()
            )
            parent = node.parent.get_text(" ", strip=True).lower() if node.parent else ""
            if any(x in marker for x in ("old-price", "regular-price", "compare", "coupon", "discount")):
                continue
            if any(x in parent for x in ("old price", "was ", "before ", "per liter", "€/l")):
                continue
            n = _price_number(
                node.get("content")
                or node.get("data-price")
                or node.get("data-product-price")
                or node.get_text(" ", strip=True)
            )
            if n is not None:
                score = (
                    20 if any(x in marker for x in ("current", "final", "sale")) else 0
                ) + (10 if "product" in marker else 0)
                candidates.append((score, n))
    if candidates:
        candidates.sort(key=lambda x: (-x[0], x[1]))
        return candidates[0][1], "EUR", "semantic_html"
    return None, "EUR", None


def _extract_availability(product, soup):
    states = [_offer_availability(o) for o in _offers(product)]
    if "in_stock" in states:
        return "in_stock", "jsonld"
    if "out_of_stock" in states:
        return "out_of_stock", "jsonld"
    state = _availability(soup.get_text(" ", strip=True))
    return state, "page_text" if state != "unknown" else "not_explicit"


def _extract_gtin(product):
    return _value(product, "gtin13", "gtin12", "gtin14", "gtin", "ean")


def _variant_rows(soup, product, base_name, base_url):
    rows = []
    variants = product.get("hasVariant") if isinstance(product, dict) else None
    if isinstance(variants, dict):
        variants = [variants]
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            name = _value(variant, "name") or base_name
            size, size_source = _extract_size(variant, name)
            price = None
            currency = "EUR"
            for offer in _offers(variant):
                price = _offer_price(offer)
                if price is not None:
                    currency = str(offer.get("priceCurrency") or "EUR").upper()
                    break
            state = "unknown"
            for offer in _offers(variant):
                state = _offer_availability(offer) or state
            if size is not None or price is not None or state != "unknown":
                rows.append({
                    "name": name, "size_ml": size, "size_source": size_source,
                    "price": price, "currency": currency,
                    "availability": state,
                    "url": _product_url(_value(variant, "url")) or base_url,
                    "sku": _value(variant, "sku"),
                })

    for selector in (
        "[data-product-attribute]", "[data-product-variant]",
        "[data-variant]", ".product-variants-item",
        ".product-variant", ".variant-item", ".variant",
    ):
        for block in soup.select(selector):
            text = _clean(block.get_text(" ", strip=True))
            size = _size_ml(text)
            if size is None:
                continue
            price = None
            for node in block.select(
                '[itemprop="price"], [data-price], [data-product-price], '
                ".price, .product-price, .current-price, .sale-price"
            ):
                price = _price_number(
                    node.get("content")
                    or node.get("data-price")
                    or node.get_text(" ", strip=True)
                )
                if price is not None:
                    break
            state = _availability(text)
            if price is not None or state != "unknown":
                rows.append({
                    "name": base_name, "size_ml": size,
                    "size_source": "variant_block", "price": price,
                    "currency": "EUR", "availability": state,
                    "url": base_url, "sku": None,
                })

    output = []
    seen = set()
    for row in rows:
        key = (
            row["size_ml"], row["price"], row["availability"],
            row["url"], row["sku"],
        )
        if key not in seen:
            seen.add(key)
            output.append(row)
    return output[:80]


def _build_result(
    title, brand, price, currency, availability, availability_source,
    size_ml, size_source, concentration, image, gtin, mpn, sku,
    product_id, url, price_source,
):
    return {
        "store": STORE,
        "source": {
            "source_name": title,
            "source_brand": brand,
            "url": url,
            "image": image,
        },
        "identity": {
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
            "mpn": {"value": mpn, "source": "jsonld"} if mpn else None,
            "sku": {"value": sku, "source": "jsonld"} if sku else None,
            "store_product_id": (
                {"value": product_id, "source": "jsonld_or_url"}
                if product_id else None
            ),
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": (
                {"value": size_ml, "source": size_source}
                if size_ml is not None else None
            ),
            "concentration": (
                {"value": concentration, "source": "product_title"}
                if concentration else None
            ),
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
        },
        "offer": {
            "price": price,
            "currency": str(currency or "EUR").upper(),
            "availability": availability,
        },
        "provenance": {
            "name": "sabina_jsonld_or_h1",
            "price": price_source,
            "availability": availability_source,
            "image": "sabina_jsonld_or_og" if image else None,
            "size_ml": size_source,
            "concentration": "product_title" if concentration else None,
        },
        "raw_data": {"product_url": url},
        "name": title,
        "brand": brand,
        "price": _price_text(price),
        "price_num": price,
        "url": url,
        "available": (
            True if availability == "in_stock"
            else False if availability == "out_of_stock"
            else None
        ),
        "availability": availability,
        "size_ml": size_ml,
        "size": (
            f"{int(size_ml)} ml" if size_ml is not None and float(size_ml).is_integer()
            else f"{size_ml} ml" if size_ml is not None else None
        ),
        "concentration": concentration,
        "image": image,
        "image_url": image,
        "gtin": gtin,
        "mpn": mpn,
        "sku": sku,
        "store_product_id": product_id,
    }


def _extract_product_page(url, query):
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        try:
            response = _request(session, url)
        except StoreRequestError as exc:
            return [], {"status": exc.status, "url": url, "error": str(exc)}
        try:
            html = response.text or ""
            final_url = _product_url(response.url) or url
        finally:
            response.close()

        soup = BeautifulSoup(html, "html.parser")
        product = _jsonld_product(soup)
        title = _extract_name(product, soup)

        if not title or not _matches_query(title, final_url, query):
            return [], {"status": "partial", "url": url, "reason": "query_mismatch"}
        if _is_non_product(title, final_url):
            return [], {"status": "partial", "url": url, "reason": "non_product"}

        brand = _extract_brand(product, soup)
        price, currency, price_source = _extract_price(product, soup)
        availability, availability_source = _extract_availability(product, soup)
        size, size_source = _extract_size(product, title)
        concentration = _concentration(title)
        image = _extract_image(product, soup)
        gtin = _extract_gtin(product)
        mpn = _value(product, "mpn")
        sku = _value(product, "sku")
        product_id = _value(product, "productID", "productId") or sku

        variants = _variant_rows(soup, product, title, final_url)
        rows = []

        if variants:
            for variant in variants:
                vprice = variant.get("price")
                vstate = variant.get("availability") or availability
                if vprice is None and vstate == "unknown":
                    continue
                rows.append(
                    _build_result(
                        variant.get("name") or title, brand,
                        vprice if vprice is not None else price,
                        variant.get("currency") or currency,
                        vstate, (
                            availability_source
                            if vstate == availability
                            else "variant"
                        ),
                        variant.get("size_ml") if variant.get("size_ml") is not None else size,
                        variant.get("size_source") or size_source,
                        concentration, image, gtin, mpn,
                        variant.get("sku") or sku, product_id,
                        _product_url(variant.get("url")) or final_url,
                        price_source if vprice == price else "variant",
                    )
                )
            return rows

        if price is None and availability == "unknown":
            return [], {"status": "partial", "url": url, "reason": "missing_offer_data"}

        return [_build_result(
            title, brand, price, currency, availability, availability_source,
            size, size_source, concentration, image, gtin, mpn, sku,
            product_id, final_url, price_source,
        )], {"status": "success", "url": final_url}

    except Exception as exc:
        return [], {
            "status": "error", "url": url,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        session.close()


def _extract_product_links(html, query):
    soup = BeautifulSoup(html or "", "html.parser")
    wanted = _query_tokens(query)
    scored = {}

    def add(raw, context=""):
        url = _product_url(raw)
        if not url:
            return
        hay = _norm(f"{context} {url.replace('-', ' ')}")
        hits = sum(token in hay for token in wanted)
        if wanted and hits == 0:
            return
        if url not in scored or hits > scored[url]:
            scored[url] = hits

    for anchor in soup.find_all("a", href=True):
        add(anchor.get("href"), anchor.get_text(" ", strip=True))

    ordered = sorted(
        scored.items(),
        key=lambda item: (-item[1], len(item[0]), item[0]),
    )
    return [url for url, _ in ordered[:MAX_CANDIDATES]]


def _search_page_state(html, query):
    soup = BeautifulSoup(html or "", "html.parser")
    text = _norm(soup.get_text(" ", strip=True))
    q = _norm(query)
    if not q or q not in text:
        return "unknown"
    if re.search(r"(?:0\s+(?:result|resultados|productos|products)|no\s+(?:hay|se\s+han\s+encontrado)|sin\s+resultados|no\s+results)", text, re.I):
        return "zero"
    return "results" if _extract_product_links(html, query) else "unknown"


def _discover(session, query):
    q = quote_plus(query)
    endpoints = (
        BASE + "/es/buscar?s=" + q,
        BASE + "/es/buscar?controller=search&s=" + q,
        BASE + "/es/buscar?search_query=" + q,
        BASE + "/es/search?s=" + q,
    )
    candidates = []
    seen = set()
    failures = []
    verified_zero = False

    for endpoint in endpoints:
        try:
            response = _request(session, endpoint)
        except StoreRequestError as exc:
            failures.append({
                "status": exc.status,
                "url": exc.url,
                "http_status": exc.http_status,
                "message": str(exc),
            })
            continue
        try:
            html = response.text or ""
            for url in _extract_product_links(html, query):
                if url not in seen:
                    seen.add(url)
                    candidates.append(url)
            if _search_page_state(html, query) == "zero":
                verified_zero = True
        finally:
            response.close()
        if len(candidates) >= MAX_CANDIDATES:
            break

    if candidates:
        return candidates[:MAX_CANDIDATES], {
            "status": "partial" if failures else "success",
            "verified": True,
            "discovery": "live_search",
            "failures": failures,
        }

    if verified_zero and not failures:
        return [], {
            "status": "success",
            "verified": True,
            "discovery": "verified_empty",
            "failures": [],
        }

    return [], {
        "status": failures[0]["status"] if failures else "success",
        "verified": False if failures else True,
        "discovery": "search_unverified" if failures else "verified_empty",
        "failures": failures,
    }


def search_stream(query):
    query = _clean(query)
    started = time.perf_counter()

    if not query:
        yield {
            "status": "success", "verified": True, "results": [],
            "error": None, "details": {"reason": "empty_query"},
        }
        return

    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        try:
            warm = _request(session, BASE + "/es/")
            warm.close()
        except StoreRequestError:
            pass
        candidates, discovery = _discover(session, query)
    finally:
        session.close()

    if not candidates:
        yield {
            "status": discovery.get("status", "error"),
            "verified": bool(discovery.get("verified")),
            "results": [],
            "error": None if discovery.get("verified") else discovery.get("failures"),
            "details": {
                "stage": "discovery",
                "candidate_count": 0,
                "discovery": discovery,
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
            pool.submit(_extract_product_page, url, query): url
            for url in candidates
        }
        for future in as_completed(futures):
            try:
                rows, meta = future.result()
            except Exception as exc:
                rows, meta = [], {
                    "status": "error",
                    "url": futures[future],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            results.extend(rows)
            if meta.get("status") not in {"success", "partial"}:
                errors.append(meta)

    seen = set()
    deduped = []
    for row in results:
        key = (
            row.get("url"), row.get("size_ml"),
            row.get("price_num"), row.get("availability"),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    deduped.sort(key=lambda x: (
        2 if x.get("availability") == "out_of_stock" else 0,
        x.get("price_num") if x.get("price_num") is not None else 999999,
        x.get("size_ml") if x.get("size_ml") is not None else 999999,
    ))
    deduped = deduped[:MAX_RESULTS]

    if deduped and errors:
        status, verified = "partial", True
    elif deduped:
        status, verified = "success", True
    elif errors:
        status, verified = "partial", False
    else:
        status, verified = "success", True

    yield {
        "status": status,
        "verified": verified,
        "results": deduped,
        "error": errors or None,
        "details": {
            "stage": "product_fetch",
            "candidate_count": len(candidates),
            "result_count": len(deduped),
            "error_count": len(errors),
            "elapsed": round(time.perf_counter() - started, 3),
            "discovery": discovery,
        },
    }


def search(query):
    return next(search_stream(query)).get("results", [])


def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generic Sabina scraper")
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(next(search_stream(args.query)), ensure_ascii=False, indent=2))
