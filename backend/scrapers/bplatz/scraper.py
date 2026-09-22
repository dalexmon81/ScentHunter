from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Bplatz"
BASE_URL = "https://en.bplatz.de"
TIMEOUT = (2.5, 6.0)
MAX_CANDIDATES = 40
MAX_CATALOG_PAGES = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

STOPWORDS = {"eau", "de", "parfum", "perfume", "edp", "edt", "extrait", "spray", "for", "by", "pour", "ml", "cl", "men", "man", "women", "woman", "unisex", "herren", "damen"}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    text = clean(value).lower()
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(value):
    return [t for t in norm(value).split() if t not in STOPWORDS and len(t) > 1]


def matches(text, query):
    q = tokens(query)
    if not q:
        return False
    hay = set(norm(text).split())
    if all(token in hay for token in q):
        return True
    compact_query = "".join(q)
    compact_text = "".join(tokens(text))
    return bool(compact_query and compact_query in compact_text)


def size_ml(*values):
    text = " ".join(clean(v) for v in values)
    m = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl|dl|l)\b", text, re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    if unit == "cl": n *= 10
    elif unit == "dl": n *= 100
    elif unit == "l": n *= 1000
    return int(n) if n.is_integer() else n


def parse_price(value):
    if value is None or value == "":
        return None
    text = clean(value).replace("€", "").replace("EUR", "").strip()
    m = re.search(r"\d{1,3}(?:[.,]\d{3})*,\d{2}|\d+(?:[.,]\d{1,2})?", text)
    if not m:
        return None
    raw = m.group(0)
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
    try:
        n = float(raw)
    except ValueError:
        return None
    return round(n, 2) if 0 < n < 10000 else None


def concentration(*values):
    text = norm(" ".join(clean(v) for v in values))
    if "extrait de parfum" in text or re.search(r"\bextrait\b", text):
        return "Extrait de Parfum"
    if "eau de toilette" in text or re.search(r"\bedt\b", text):
        return "Eau de Toilette"
    if "eau de parfum" in text or re.search(r"\bedp\b", text):
        return "Eau de Parfum"
    if re.search(r"\bparfum\b", text):
        return "Parfum"
    return None


def availability_from_text(text):
    n = norm(text)
    if any(x in n for x in ("add to cart", "in den warenkorb", "auf lager", "in stock", "available")):
        return "in_stock"
    if any(x in n for x in ("sold out", "ausverkauft", "out of stock", "unavailable", "nicht verfugbar", "nicht vorratig")):
        return "out_of_stock"
    return "unknown"


def request_json(session, url, params=None):
    try:
        response = session.get(url, params=params, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except requests.Timeout as exc:
        raise RuntimeError(f"timeout: {url}") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"unavailable: {url}: {type(exc).__name__}: {exc}") from exc

    if response.status_code >= 400:
        status = "blocked" if response.status_code in (401, 403, 429) else "unavailable" if response.status_code >= 500 else "error"
        response.close()
        raise RuntimeError(f"{status}: HTTP {response.status_code}: {url}")

    try:
        return response.json()
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"error: invalid JSON: {url}") from exc
    finally:
        response.close()


def add_candidate(url, query, candidates, seen):
    if not url:
        return
    absolute = urljoin(BASE_URL, str(url)).split("#", 1)[0].rstrip("/")
    if "/products/" not in absolute.lower():
        return
    if not matches(absolute, query):
        return
    if absolute in seen:
        return
    seen.add(absolute)
    candidates.append(absolute)


def _discover_products_json(session, query, candidates, seen):
    """Generic Shopify catalog fallback.

    This is store catalog discovery only: it does not know any perfume name
    or variant. The final product page remains authoritative for price/stock.
    """
    for page in range(1, MAX_CATALOG_PAGES + 1):
        data = request_json(
            session,
            BASE_URL + "/products.json",
            {"limit": 250, "page": page},
        )
        if not isinstance(data, dict):
            return
        products = data.get("products")
        if not isinstance(products, list) or not products:
            return

        for product in products:
            if not isinstance(product, dict):
                continue
            title = clean(product.get("title"))
            vendor = clean(product.get("vendor"))
            handle = clean(product.get("handle"))
            url = product.get("url") or ("/products/" + handle if handle else "")
            if matches(f"{title} {vendor} {handle} {url}", query):
                add_candidate(url, query, candidates, seen)
                if len(candidates) >= MAX_CANDIDATES:
                    return

        if len(products) < 250:
            return


def _discover_from_sitemap(session, query, candidates, seen):
    """Generic Shopify sitemap fallback, including nested sitemap indexes."""
    pending = [BASE_URL + "/sitemap.xml"]
    visited = set()

    while pending and len(visited) < 20 and len(candidates) < MAX_CANDIDATES:
        sitemap_url = pending.pop(0)
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)

        try:
            response = session.get(
                sitemap_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True
            )
            if response.status_code >= 400:
                response.close()
                continue
            text = response.text or ""
            response.close()
        except requests.RequestException:
            continue

        for raw_url in re.findall(r"<loc>\s*([^<]+)\s*</loc>", text, re.I):
            url = urljoin(BASE_URL, clean(raw_url)).split("#", 1)[0]
            low = url.lower()
            if low.endswith(".xml") or "sitemap" in low:
                if url not in visited:
                    pending.append(url)
                continue
            add_candidate(url, query, candidates, seen)
            if len(candidates) >= MAX_CANDIDATES:
                return


def discover(session, query):
    candidates, seen = [], set()

    # Shopify predictive search is the primary store-native discovery API.
    for params in (
        {"q": query, "resources[type]": "product", "resources[limit]": 50, "resources[options][unavailable_products]": "show"},
        {"q": query, "resources[type]": "product", "resources[limit]": 50},
    ):
        data = request_json(session, BASE_URL + "/search/suggest.json", params)
        products = (((data or {}).get("resources") or {}).get("results") or {}).get("products") or []
        for product in products:
            if not isinstance(product, dict):
                continue
            title = product.get("title") or ""
            vendor = product.get("vendor") or ""
            url = product.get("url") or product.get("product_url")
            if matches(f"{title} {vendor}", query):
                add_candidate(url, query, candidates, seen)
        if candidates:
            return candidates[:MAX_CANDIDATES]

    # Shopify JSON search fallback.
    data = request_json(session, BASE_URL + "/search.json", {"q": query, "type": "product", "limit": 50})
    for product in (data or {}).get("products") or []:
        if not isinstance(product, dict):
            continue
        url = product.get("url") or product.get("handle")
        if url and not str(url).startswith("/") and product.get("handle"):
            url = "/products/" + str(product["handle"])
        elif url and not str(url).startswith("/products/") and product.get("handle"):
            url = "/products/" + str(product["handle"])
        if matches(f"{product.get('title','')} {product.get('vendor','')} {url or ''}", query):
            add_candidate(url, query, candidates, seen)
    if candidates:
        return candidates[:MAX_CANDIDATES]

    # Generic Shopify product catalog fallback.
    _discover_products_json(session, query, candidates, seen)
    if candidates:
        return candidates[:MAX_CANDIDATES]

    # Generic Shopify sitemap fallback.
    _discover_from_sitemap(session, query, candidates, seen)
    if candidates:
        return candidates[:MAX_CANDIDATES]

    # HTML search fallback.
    try:
        response = session.get(BASE_URL + "/search", params={"q": query, "type": "product"}, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code < 400:
            soup = BeautifulSoup(response.text, "html.parser")
            for anchor in soup.select('a[href*="/products/"]'):
                text = clean(f"{anchor.get('title','')} {anchor.get_text(' ', strip=True)} {anchor.get('href','')}")
                if matches(text, query):
                    add_candidate(anchor.get("href"), query, candidates, seen)
        response.close()
    except requests.RequestException:
        pass

    return candidates[:MAX_CANDIDATES]


def jsonld_product(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        queue = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
            elif isinstance(item, dict):
                typ = item.get("@type")
                types = typ if isinstance(typ, list) else [typ]
                if any(str(t).lower() in {"product", "productgroup"} for t in types):
                    return item
                graph = item.get("@graph")
                if isinstance(graph, list):
                    queue.extend(graph)
    return {}


def offer_list(product):
    offers = product.get("offers") if isinstance(product, dict) else None
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [x for x in offers if isinstance(x, dict)]
    return []


def product_from_page(session, url, query):
    try:
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if response.status_code >= 400:
            response.close()
            return None
        html = response.text
        final_url = response.url
        response.close()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(html, "html.parser")
    data = jsonld_product(soup)
    h1 = soup.find("h1")
    name = clean((data or {}).get("name") or (h1.get_text(" ", strip=True) if h1 else ""))
    if not name or not matches(f"{name} {(data.get('brand') or {}).get('name','') if isinstance(data.get('brand'),dict) else data.get('brand','')}", query):
        return None

    brand = data.get("brand")
    brand = clean(brand.get("name")) if isinstance(brand, dict) else clean(brand)
    size = size_ml(name, soup.get_text(" ", strip=True))
    offers = offer_list(data)
    price = None
    availability = None
    for offer in offers:
        p = parse_price(offer.get("price") or offer.get("lowPrice"))
        if p is not None:
            price = p
            break
    for offer in offers:
        a = norm(offer.get("availability") or "")
        if "outofstock" in a or "soldout" in a:
            availability = "out_of_stock"
        elif "instock" in a or "available" in a:
            availability = "in_stock"
    page_text = soup.get_text(" ", strip=True)
    if availability is None:
        availability = availability_from_text(page_text)

    if price is None:
        price_patterns = [
            r"retail\s+price\s*€\s*([0-9]+(?:[.,][0-9]{1,2})?)",
            r"price\s*€\s*([0-9]+(?:[.,][0-9]{1,2})?)",
            r"€\s*([0-9]+(?:[.,][0-9]{1,2})?)",
        ]
        for pattern in price_patterns:
            m = re.search(pattern, page_text, re.I)
            if m:
                price = parse_price(m.group(1))
                if price is not None:
                    break

    image = data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    if not image:
        meta = soup.select_one('meta[property="og:image"]')
        image = meta.get("content") if meta else None
    if image:
        image = urljoin(BASE_URL, str(image))

    return {
        "store": STORE,
        "source": {"source_name": name, "source_brand": brand or None, "url": final_url, "image": image},
        "identity": {"gtin": None, "mpn": None, "sku": None, "store_product_id": {"value": final_url, "source": "product_url"}, "store_variant_id": None},
        "attributes": {"size_ml": {"value": size, "source": "product_page"} if size is not None else None, "concentration": {"value": concentration(name), "source": "product_title"} if concentration(name) else None, "gender": {"value": "unknown", "source": "not_explicit"}, "packaging_type": {"value": "product", "source": "default"}},
        "offer": {"price": price, "currency": "EUR", "availability": availability},
        "provenance": {"source_page": final_url, "product_source": "shopify_product_page"},
        "raw_data": {"jsonld": data},
        "name": name,
        "brand": brand,
        "price": f"{price:.2f} €" if price is not None else None,
        "price_num": price,
        "url": final_url,
        "available": True if availability == "in_stock" else False if availability == "out_of_stock" else None,
        "availability": availability,
        "size_ml": size,
        "size": f"{int(size)} ml" if size is not None and float(size).is_integer() else (f"{size} ml" if size is not None else None),
        "concentration": concentration(name),
        "image": image,
    }


def _search_report(query):
    query = clean(query)
    if not query:
        return {"status": "success", "verified": True, "results": [], "error": None, "details": {"verified_empty": True}}

    session = requests.Session()
    results, seen = [], set()
    try:
        try:
            candidates = discover(session, query)
        except RuntimeError as exc:
            text = str(exc)
            status = next((x for x in ("timeout", "blocked", "unavailable", "error") if text.startswith(x + ":")), "error")
            return {"status": status, "verified": False, "results": [], "error": text, "details": {"verified_empty": False}}

        for url in candidates:
            try:
                item = product_from_page(session, url, query)
            except Exception:
                item = None
            if not item:
                continue
            key = (item.get("url"), item.get("size_ml"))
            if key in seen:
                continue
            seen.add(key)
            results.append(item)

        results.sort(key=lambda x: (x.get("available") is not True, x.get("price_num") is None, x.get("price_num") or 999999))
        return {"status": "success", "verified": True, "results": results, "error": None, "details": {"verified_empty": not bool(results), "candidate_count": len(candidates)}}
    finally:
        session.close()


def search(query):
    return _search_report(query).get("results", [])


def search_stream(query, emit=None):
    report = _search_report(query)
    if callable(emit):
        for row in report.get("results", []):
            emit(row)
    return report


def scrape(query):
    return search(query)
