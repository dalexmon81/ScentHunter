import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

STORE = "ParfumCity"
BASE_URL = "https://www.parfumcity.nl"
TIMEOUT = (2.5, 6.0)
MAX_CANDIDATES = 40
MAX_CATALOG_PAGES = 12
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}
STOPWORDS = {"eau", "de", "parfum", "perfume", "edp", "edt", "extrait", "spray", "for", "by", "pour", "ml", "cl", "men", "man", "women", "woman", "male", "female", "homme", "femme", "herren", "damen"}


def clean(v): return re.sub(r"\s+", " ", str(v or "")).strip()
def norm(v): return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(v).lower())).strip()
def tokens(q): return [x for x in norm(q).split() if x not in STOPWORDS and len(x) > 1]
def matches(text, q):
    hay = set(norm(text).split()); wanted = tokens(q)
    return bool(wanted) and all(x in hay for x in wanted)


def size_ml(*values):
    m = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl|dl|l)\b", " ".join(clean(x) for x in values), re.I)
    if not m: return None
    n = float(m.group(1).replace(",", ".")); u = m.group(2).lower()
    if u == "cl": n *= 10
    elif u == "dl": n *= 100
    elif u == "l": n *= 1000
    return int(n) if n.is_integer() else n


def concentration(*values):
    t = norm(" ".join(clean(x) for x in values))
    if "extrait de parfum" in t or re.search(r"\bextrait\b", t): return "Extrait de Parfum"
    if "eau de toilette" in t or re.search(r"\bedt\b", t): return "Eau de Toilette"
    if "eau de parfum" in t or re.search(r"\bedp\b", t): return "Eau de Parfum"
    return "Parfum" if re.search(r"\bparfum\b", t) else None


def parse_price(v):
    if v in (None, ""): return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = float(v)
        if n.is_integer() and abs(n) >= 100: n /= 100
        return round(n, 2) if n > 0 else None
    s = clean(v).replace("€", "").replace("EUR", "").strip()
    m = re.search(r"\d{1,3}(?:[.,]\d{3})*,\d{2}|\d+(?:[.,]\d{1,2})?", s)
    if not m: return None
    raw = m.group(0)
    raw = raw.replace(".", "") if "," in raw and "." in raw else raw
    raw = raw.replace(",", ".")
    try: n = float(raw)
    except ValueError: return None
    return round(n / 100 if re.fullmatch(r"\d+", m.group(0)) and n >= 100 else n, 2) if n > 0 else None


def _get(session, url, params=None):
    try:
        r = session.get(url, params=params, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        return r if r.status_code < 400 else None
    except requests.RequestException:
        return None


def _canonical_product_url(url):
    """Collapse Shopify locale prefixes to one canonical product URL.

    ParfumCity exposes the same Shopify product under /de, /en, /fr and /es
    paths. Those are translations of the same product, not separate offers.
    Keep the canonical root product path so discovery and fetch cannot create
    duplicate store offers.
    """
    absolute = urljoin(BASE_URL, str(url)).split("?", 1)[0].split("#", 1)[0].rstrip("/")
    base = BASE_URL.rstrip("/")
    if absolute.lower().startswith(base.lower() + "/"):
        path = absolute[len(base):]
        path = re.sub(r"^/[a-z]{2}(?:-[a-z]{2})?/products/", "/products/", path, flags=re.I)
        absolute = base + path
    return absolute


def _add_candidate(url, urls, seen):
    if not url:
        return False
    absolute = _canonical_product_url(url)
    if "/products/" not in absolute or absolute in seen:
        return False
    seen.add(absolute)
    urls.append(absolute)
    return True


def _discover_products_json(session, query, urls, seen):
    """Generic Shopify catalog fallback; no product-specific knowledge."""
    for page in range(1, MAX_CATALOG_PAGES + 1):
        r = _get(
            session,
            BASE_URL + "/products.json",
            {"limit": 250, "page": page},
        )
        if not r:
            return
        try:
            data = r.json()
            products = data.get("products") if isinstance(data, dict) else None
        except (ValueError, TypeError):
            products = None
        finally:
            r.close()

        if not isinstance(products, list) or not products:
            return

        for p in products:
            if not isinstance(p, dict):
                continue
            title = clean(p.get("title")); vendor = clean(p.get("vendor")); handle = clean(p.get("handle"))
            u = p.get("url") or ("/products/" + handle if handle else "")
            if matches(f"{title} {vendor} {handle} {u}", query):
                _add_candidate(u, urls, seen)
                if len(urls) >= MAX_CANDIDATES:
                    return

        if len(products) < 250:
            return


def _discover_from_sitemap(session, query, urls, seen):
    """Generic Shopify sitemap fallback, including nested indexes."""
    pending = [BASE_URL + "/sitemap.xml"]
    visited = set()
    while pending and len(visited) < 20 and len(urls) < MAX_CANDIDATES:
        sitemap_url = pending.pop(0)
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)
        r = _get(session, sitemap_url)
        if not r:
            continue
        try:
            text = r.text or ""
        finally:
            r.close()
        for raw_url in re.findall(r"<loc>\s*([^<]+)\s*</loc>", text, re.I):
            u = urljoin(BASE_URL, clean(raw_url)).split("#",1)[0]
            low = u.lower()
            if low.endswith(".xml") or ".xml?" in low or "sitemap" in low:
                if u not in visited:
                    pending.append(u)
                continue
            if "/products/" in low and matches(u, query):
                _add_candidate(u, urls, seen)
                if len(urls) >= MAX_CANDIDATES:
                    return


def discover(session, query):
    urls, seen = [], set()

    # Shopify predictive search; unavailable products are explicitly requested.
    for params in (
        {"q": query, "resources[type]": "product", "resources[limit]": 50, "resources[options][unavailable_products]": "show"},
        {"q": query, "resources[type]": "product", "resources[limit]": 50},
    ):
        r = _get(session, BASE_URL + "/search/suggest.json", params)
        if r:
            try:
                data = r.json()
                products = (((data.get("resources") or {}).get("results") or {}).get("products") or [])
                for p in products:
                    if isinstance(p, dict) and matches(f"{p.get('title','')} {p.get('vendor','')} {p.get('url','')}", query): _add_candidate(p.get("url") or p.get("product_url"), urls, seen)
            except (ValueError, TypeError): pass
            finally: r.close()
        # Continue with the remaining generic discovery sources even when one
    # Shopify endpoint already returned candidates. A partial endpoint response
    # must not hide products omitted from that endpoint.

    # Shopify search JSON fallback.
    r = _get(session, BASE_URL + "/search.json", {"q": query, "type": "product", "limit": 50})
    if r:
        try:
            for p in r.json().get("products") or []:
                if not isinstance(p, dict): continue
                u = p.get("url") or p.get("handle")
                if p.get("handle") and (not u or not str(u).startswith("/products/")): u = "/products/" + str(p["handle"])
                if matches(f"{p.get('title','')} {p.get('vendor','')} {u or ''}", query): _add_candidate(u, urls, seen)
        except (ValueError, TypeError): pass
        finally: r.close()
    # Continue to catalog discovery as a supplementary source.

    # Generic Shopify product catalog fallback.
    _discover_products_json(session, query, urls, seen)
    # Continue to sitemap discovery as a supplementary source.

    # Generic Shopify sitemap fallback.
    _discover_from_sitemap(session, query, urls, seen)
    # Continue to HTML search as a final generic source.

    # HTML search fallback.
    r = _get(session, BASE_URL + "/search", {"q": query, "type": "product"})
    if r:
        try:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select('a[href*="/products/"]'):
                if matches(f"{a.get('title','')} {a.get_text(' ', strip=True)} {a.get('href','')}", query): _add_candidate(a.get("href"), urls, seen)
        finally: r.close()
    return urls[:MAX_CANDIDATES]


def product_json(session, url):
    r = _get(session, url.rstrip("/") + ".js")
    if not r: return None
    try:
        data = r.json(); return data if isinstance(data, dict) else None
    except (ValueError, TypeError): return None
    finally: r.close()


def make_item(product, variant, url, query):
    name = clean(product.get("title")); variant_name = clean(variant.get("title"))
    if not matches(f"{name} {product.get('vendor','')} {url}", query): return None
    source_name = name if not variant_name or variant_name.lower() == "default title" else f"{name} {variant_name}"
    p = parse_price(variant.get("price"))
    size = size_ml(variant_name, name)
    conc = concentration(variant_name, name)
    available = variant.get("available")
    stock = "in_stock" if available is True else "out_of_stock" if available is False else "unknown"
    image = product.get("featured_image")
    if isinstance(image, dict): image = image.get("src") or image.get("url")
    if not image and product.get("images"): image = product["images"][0]
    image = urljoin(BASE_URL, str(image)) if image else None
    return {
        "store": STORE,
        "source": {"source_name": source_name, "source_brand": clean(product.get("vendor")) or None, "url": url, "image": image},
        "identity": {"gtin": None, "mpn": None, "sku": {"value": str(variant.get("sku")), "source": "shopify_variant"} if variant.get("sku") else None, "store_product_id": {"value": product.get("id"), "source": "shopify_product"} if product.get("id") is not None else None, "store_variant_id": {"value": variant.get("id"), "source": "shopify_variant"} if variant.get("id") is not None else None},
        "attributes": {"size_ml": {"value": size, "source": "product_variant"} if size is not None else None, "concentration": {"value": conc, "source": "product_title"} if conc else None, "gender": {"value": "unknown", "source": "not_explicit"}, "packaging_type": {"value": "product", "source": "default"}},
        "offer": {"price": p, "currency": "EUR", "availability": stock},
        "provenance": {"source_page": url, "product_source": "shopify_product_json", "variant_source": "shopify_product_json"},
        "raw_data": {"product": product, "variant": variant},
        "name": name, "brand": clean(product.get("vendor")), "price": f"{p:.2f}".replace(".", ",") + " €" if p is not None else None, "price_num": p, "url": url, "available": available, "availability": stock, "size_ml": size, "size": f"{int(size)} ml" if size is not None and float(size).is_integer() else (f"{size} ml" if size is not None else None), "concentration": conc, "image": image,
    }


def search(query):
    query = clean(query)
    if not query: return []
    session = requests.Session(); results = []; seen = set()
    try:
        for url in discover(session, query):
            data = product_json(session, url)
            if not data: continue
            for variant in data.get("variants") or []:
                if not isinstance(variant, dict): continue
                item = make_item(data, variant, url, query)
                if not item: continue
                key = (item["url"], (item.get("identity", {}).get("store_variant_id") or {}).get("value"))
                if key in seen: continue
                seen.add(key); results.append(item)
        return results
    finally: session.close()


def search_stream(query, emit=None):
    rows = search(query)
    if callable(emit):
        for row in rows: emit(row)
        return None
    return iter(rows)


def scrape(query): return search(query)
