import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = (2.5, 7.0)
MAX_CANDIDATES = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
    "Cache-Control": "no-cache",
}

STOPWORDS = {"eau", "de", "parfum", "perfume", "edp", "edt", "extrait", "spray", "for", "by", "pour", "ml", "cl", "men", "man", "women", "woman", "unisex", "herren", "damen"}


def clean(v): return re.sub(r"\s+", " ", str(v or "")).strip()
def norm(v): return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(v).lower())).strip()
def tokens(q): return [x for x in norm(q).split() if x not in STOPWORDS and len(x) > 1]
def matches(text, q):
    h = set(norm(text).split()); wanted = tokens(q)
    return bool(wanted) and all(x in h for x in wanted)


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
    return None


def parse_price(v):
    if v in (None, ""): return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = float(v)
        if n <= 0: return None
        if n.is_integer() and n >= 100: n /= 100
        return round(n, 2)
    s = clean(v).replace("€", "").replace("EUR", "")
    m = re.search(r"\d{1,3}(?:[.,]\d{3})*,\d{2}|\d+(?:[.,]\d{1,2})?", s)
    if not m: return None
    raw = m.group(0)
    if "," in raw and "." in raw: raw = raw.replace(".", "").replace(",", ".")
    else: raw = raw.replace(",", ".")
    try: n = float(raw)
    except ValueError: return None
    return round(n, 2) if n > 0 else None


def request_json(session, url, params=None):
    try:
        r = session.get(url, params=params, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            r.close(); return None
        try: return r.json()
        finally: r.close()
    except (requests.RequestException, ValueError, TypeError):
        return None


def discover(session, query):
    urls, seen = [], set()
    def add(u, context=""):
        if not u: return
        absolute = urljoin(BASE_URL, str(u)).split("?", 1)[0].split("#", 1)[0].rstrip("/")
        if "/products/" not in absolute or absolute in seen: return
        if not matches(f"{context} {absolute}", query): return
        seen.add(absolute); urls.append(absolute)

    # Never require a price during discovery. Out-of-stock products are still
    # valid catalog hits and must reach product-page parsing.
    for params in (
        {"q": query, "resources[type]": "product", "resources[limit]": 50, "resources[options][unavailable_products]": "show"},
        {"q": query, "resources[type]": "product", "resources[limit]": 50},
    ):
        data = request_json(session, BASE_URL + "/search/suggest.json", params)
        products = (((data or {}).get("resources") or {}).get("results") or {}).get("products") or []
        for p in products:
            if isinstance(p, dict): add(p.get("url") or p.get("product_url"), f"{p.get('title','')} {p.get('vendor','')}")
        if urls: return urls[:MAX_CANDIDATES]

    # Shopify JSON search fallback.
    data = request_json(session, BASE_URL + "/search.json", {"q": query, "type": "product", "limit": 50})
    for p in (data or {}).get("products") or []:
        if not isinstance(p, dict): continue
        u = p.get("url") or p.get("handle")
        if p.get("handle") and (not u or not str(u).startswith("/products/")): u = "/products/" + str(p["handle"])
        add(u, f"{p.get('title','')} {p.get('vendor','')}")
    if urls: return urls[:MAX_CANDIDATES]

    # Server-rendered search fallback.
    try:
        r = session.get(BASE_URL + "/search", params={"q": query, "type": "product"}, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code < 400:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select('a[href*="/products/"]'):
                add(a.get("href"), a.get_text(" ", strip=True))
        r.close()
    except requests.RequestException:
        pass
    return urls[:MAX_CANDIDATES]


def product_json(session, url):
    r = None
    try:
        r = session.get(url.rstrip("/") + ".js", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code >= 400: return None
        data = r.json()
        return data if isinstance(data, dict) else None
    except (requests.RequestException, ValueError, TypeError):
        return None
    finally:
        if r is not None: r.close()


def parse_product(session, url, query):
    data = product_json(session, url)
    if data:
        name = clean(data.get("title"))
        vendor = clean(data.get("vendor"))
        if matches(f"{name} {vendor} {url}", query):
            variants = data.get("variants") or []
            image = data.get("featured_image") or (data.get("images") or [None])[0]
            if isinstance(image, dict): image = image.get("src") or image.get("url")
            image = urljoin(BASE_URL, str(image)) if image else None
            rows = []
            for variant in variants:
                if not isinstance(variant, dict): continue
                price = parse_price(variant.get("price"))
                size = size_ml(variant.get("title"), name)
                avail = variant.get("available")
                stock = "in_stock" if avail is True else "out_of_stock" if avail is False else "unknown"
                vname = clean(variant.get("title"))
                source_name = name if not vname or vname.lower() == "default title" else f"{name} {vname}"
                rows.append({
                    "store": STORE,
                    "source": {"source_name": source_name, "source_brand": vendor or None, "url": url, "image": image},
                    "identity": {"gtin": None, "mpn": None, "sku": {"value": str(variant.get("sku")), "source": "shopify_variant"} if variant.get("sku") else None, "store_product_id": {"value": data.get("id"), "source": "shopify_product"} if data.get("id") is not None else None, "store_variant_id": {"value": variant.get("id"), "source": "shopify_variant"} if variant.get("id") is not None else None},
                    "attributes": {"size_ml": {"value": size, "source": "product_variant"} if size is not None else None, "concentration": {"value": concentration(vname, name), "source": "product_title"} if concentration(vname, name) else None, "gender": {"value": "unknown", "source": "not_explicit"}, "packaging_type": {"value": "product", "source": "default"}},
                    "offer": {"price": price, "currency": "EUR", "availability": stock},
                    "provenance": {"source_page": url, "product_source": "shopify_product_json", "variant_source": "shopify_product_json"},
                    "raw_data": {"product": data, "variant": variant},
                    "name": name, "brand": vendor, "price": f"{price:.2f}".replace(".", ",") + " €" if price is not None else None, "price_num": price, "url": url, "available": avail, "availability": stock, "size_ml": size, "size": f"{int(size)} ml" if size is not None and float(size).is_integer() else (f"{size} ml" if size is not None else None), "concentration": concentration(vname, name), "image": image,
                })
            return rows

    # HTML fallback for themes where .js is unavailable.
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code >= 400: return []
        html = r.text; final_url = r.url
    except requests.RequestException:
        return []
    finally:
        try: r.close()
        except Exception: pass
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1"); name = clean(h1.get_text(" ", strip=True)) if h1 else ""
    if not name or not matches(name, query): return []
    text = clean(soup.get_text(" ", strip=True))
    price = None
    m = re.search(r"\b\d{1,4}[.,]\d{2}\s*€", text)
    if m: price = parse_price(m.group(0))
    avail = "out_of_stock" if any(x in norm(text) for x in ("sold out", "out of stock", "ausverkauft")) else "in_stock" if any(x in norm(text) for x in ("add to cart", "buy now")) else "unknown"
    size = size_ml(name, text)
    return [{"store": STORE, "name": name, "price": f"{price:.2f} €" if price is not None else None, "price_num": price, "url": final_url, "available": True if avail == "in_stock" else False if avail == "out_of_stock" else None, "availability": avail, "size_ml": size}]


def search(query):
    query = clean(query)
    if not query: return []
    session = requests.Session(); results=[]; seen=set()
    try:
        for url in discover(session, query):
            try: rows = parse_product(session, url, query)
            except Exception: rows = []
            for row in rows or []:
                key = (row.get("url"), row.get("size_ml"), row.get("price_num"), row.get("availability"))
                if key in seen: continue
                seen.add(key); results.append(row)
        return results
    finally: session.close()


def search_stream(query, emit=None):
    rows = search(query)
    if callable(emit):
        for row in rows: emit(row)
        return None
    return iter(rows)


def scrape(query): return search(query)
