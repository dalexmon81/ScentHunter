"""ScentHunter - Bplatz generic Shopify store adapter.

Store-specific transport/catalog knowledge only. Canonical product identity
belongs to the central matcher.
"""

from __future__ import annotations
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests

STORE = "Bplatz"
BASE_URL = "https://en.bplatz.de"
CATALOG_URL = BASE_URL + "/products.json"
TIMEOUT = (3.0, 7.0)
CATALOG_PAGE_SIZE = 250
MAX_CATALOG_PAGES = 40
MAX_RESULTS = 80
WORKERS = 8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}

class StoreRequestError(RuntimeError):
    def __init__(self, kind, message, url=None, status_code=None):
        super().__init__(message)
        self.kind, self.url, self.status_code = kind, url, status_code

def clean(v): return re.sub(r"\s+", " ", str(v or "")).strip()
def norm(v):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(v).lower())).strip()

def query_tokens(q):
    return [x for x in norm(q).split() if len(x) > 1 and not re.fullmatch(r"\d+(?:[.,]\d+)?", x)]

def matches(text, q):
    wanted = query_tokens(q)
    if not wanted: return False
    hay = set(norm(text).split())
    return all(x in hay for x in wanted)

def size_ml(*values):
    m = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
                  " ".join(clean(x) for x in values), re.I)
    if not m: return None
    n = float(m.group(1).replace(",", "."))
    if m.group(2).lower() == "cl": n *= 10
    return int(n) if n.is_integer() else n

def concentration(*values):
    t = norm(" ".join(clean(x) for x in values))
    if re.search(r"\beau de toilette\b|\bedt\b", t): return "Eau de Toilette"
    if re.search(r"\bextrait(?: de parfum)?\b", t): return "Extrait de Parfum"
    if re.search(r"\beau de parfum\b|\bedp\b", t): return "Eau de Parfum"
    return None

def price(v):
    if v in (None, ""): return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = float(v)
        if n >= 100: n /= 100
        return round(n, 2)
    s = clean(v).replace("€", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d{1,2})?", s)
    if not m: return None
    n = float(m.group(0))
    if m.group(0).isdigit() and n >= 100: n /= 100
    return round(n, 2)

def _get(session, url, params=None):
    try:
        r = session.get(url, params=params, headers=HEADERS,
                        timeout=TIMEOUT, allow_redirects=True)
    except requests.Timeout as e:
        raise StoreRequestError("timeout", f"timeout while requesting {url}", url) from e
    except requests.ConnectionError as e:
        raise StoreRequestError("unavailable", f"connection failed for {url}", url) from e
    except requests.RequestException as e:
        raise StoreRequestError("error", f"request failed for {url}: {e}", url) from e
    if r.status_code in (403, 429):
        raise StoreRequestError("blocked", f"HTTP {r.status_code} from {url}", url, r.status_code)
    if r.status_code >= 500:
        raise StoreRequestError("unavailable", f"HTTP {r.status_code} from {url}", url, r.status_code)
    if r.status_code >= 400:
        raise StoreRequestError("error", f"HTTP {r.status_code} from {url}", url, r.status_code)
    return r

def _url(v):
    v = clean(v)
    if not v: return ""
    return urljoin(BASE_URL + "/", v).split("#")[0].split("?")[0].rstrip("/")

def _catalog_page(session, page):
    r = _get(session, CATALOG_URL, {"limit": CATALOG_PAGE_SIZE, "page": page})
    try: data = r.json()
    except (ValueError, TypeError) as e:
        raise StoreRequestError("error", f"invalid catalog JSON page {page}", CATALOG_URL) from e
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list):
        raise StoreRequestError("error", f"invalid catalog payload page {page}", CATALOG_URL)
    return products

def _discover_catalog(query, session):
    out = {}
    for page in range(1, MAX_CATALOG_PAGES + 1):
        products = _catalog_page(session, page)
        if not products: break
        for p in products:
            if not isinstance(p, dict): continue
            handle, title, vendor = clean(p.get("handle")), clean(p.get("title")), clean(p.get("vendor"))
            url = _url(p.get("url") or (f"/products/{handle}" if handle else ""))
            if url and title and matches(f"{title} {vendor} {url}", query):
                out[url] = {"url": url, "title": title, "vendor": vendor}
        if len(products) < CATALOG_PAGE_SIZE: break
    return list(out.values())

def _suggest(query, session):
    r = _get(session, BASE_URL + "/search/suggest.json", {
        "q": query, "resources[type]": "product", "resources[limit]": 50,
        "resources[options][unavailable_products]": "show",
    })
    data = r.json()
    products = ((data.get("resources") or {}).get("results") or {}).get("products")
    if not isinstance(products, list):
        raise StoreRequestError("error", "invalid predictive-search payload",
                                BASE_URL + "/search/suggest.json")
    out = {}
    for p in products:
        if not isinstance(p, dict): continue
        handle, title, vendor = clean(p.get("handle")), clean(p.get("title") or p.get("name")), clean(p.get("vendor") or p.get("brand"))
        url = _url(p.get("url") or (f"/products/{handle}" if handle else ""))
        if url and title and matches(f"{title} {vendor} {url}", query):
            out[url] = {"url": url, "title": title, "vendor": vendor}
    return list(out.values())

def _discover(query, session):
    candidates = {}
    primary_error = None
    try:
        for x in _discover_catalog(query, session): candidates[x["url"]] = x
    except StoreRequestError as e:
        primary_error = e
    try:
        for x in _suggest(query, session): candidates[x["url"]] = x
    except StoreRequestError as e:
        if not candidates and primary_error: raise primary_error
    return list(candidates.values())

def _image(product):
    x = product.get("featured_image")
    if isinstance(x, dict): x = x.get("src") or x.get("url")
    if x: return urljoin(BASE_URL, str(x))
    images = product.get("images") or []
    if images:
        x = images[0]
        if isinstance(x, dict): x = x.get("src") or x.get("url")
        return urljoin(BASE_URL, str(x)) if x else None
    return None

def _worker(candidate, query):
    session = requests.Session()
    url = candidate["url"]
    try:
        r = _get(session, url + ".js")
        try: product = r.json()
        except (ValueError, TypeError) as e:
            raise StoreRequestError("error", f"invalid product JSON from {url}", url) from e
        if not isinstance(product, dict): return []
        name, brand = clean(product.get("title") or candidate["title"]), clean(product.get("vendor") or candidate["vendor"])
        if not name or not matches(f"{name} {brand} {url}", query): return []
        image, rows = _image(product), []
        for v in product.get("variants") or []:
            if not isinstance(v, dict): continue
            amount = price(v.get("price"))
            if amount is None: continue
            vt, avail = clean(v.get("title")), v.get("available")
            sz, conc = size_ml(vt, name), concentration(vt, name)
            state = "in_stock" if avail is True else "out_of_stock" if avail is False else "unknown"
            rows.append({
                "store": STORE,
                "source": {"source_name": name if not vt or vt.lower()=="default title" else f"{name} {vt}",
                            "source_brand": brand or None, "url": url, "image": image},
                "identity": {
                    "gtin": None, "mpn": None,
                    "sku": {"value": str(v.get("sku")), "source": "shopify_variant"} if v.get("sku") else None,
                    "store_product_id": {"value": product.get("id"), "source": "shopify_product"} if product.get("id") is not None else None,
                    "store_variant_id": {"value": v.get("id"), "source": "shopify_variant"} if v.get("id") is not None else None,
                },
                "attributes": {
                    "size_ml": {"value": sz, "source": "product_variant"} if sz is not None else None,
                    "concentration": {"value": conc, "source": "product_title"} if conc else None,
                    "gender": {"value": "unknown", "source": "not_explicit"},
                    "packaging_type": {"value": "product", "source": "default"},
                },
                "offer": {"price": amount, "currency": "EUR", "availability": state},
                "provenance": {"source_page": url, "product_source": "shopify_product_json", "variant_source": "shopify_product_json"},
                "raw_data": {"product": product, "variant": v},
                "name": name, "price": f"{amount:.2f}".replace(".", ",") + " €",
                "url": url, "available": avail, "availability": state,
                "size_ml": sz, "size": f"{int(sz)} ml" if sz is not None and float(sz).is_integer() else f"{sz} ml" if sz is not None else None,
                "brand": brand, "image": image,
            })
        return rows
    finally: session.close()

def _report(status, results=None, error=None, details=None):
    return {"status": status, "results": results or [], "error": error, "details": details or {}}

def search_stream(query, emit=None):
    query = clean(query)
    if not query:
        return _report("error", error="empty_query")
    session = requests.Session()
    try:
        try: candidates = _discover(query, session)
        except StoreRequestError as e:
            return _report(e.kind, error=str(e), details={"url": e.url, "status_code": e.status_code})
    finally: session.close()
    if not candidates: return _report("success", results=[], details={"verified": True})
    results, failures = [], []
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(candidates))) as pool:
        futures = {pool.submit(_worker, c, query): c for c in candidates}
        for f in as_completed(futures):
            c = futures[f]
            try: rows = f.result() or []
            except StoreRequestError as e:
                failures.append({"url": c["url"], "status": e.kind, "error": str(e)}); continue
            except Exception as e:
                failures.append({"url": c["url"], "status": "error", "error": f"{type(e).__name__}: {e}"}); continue
            for row in rows:
                results.append(row)
                if callable(emit): emit(row)
    return _report("partial" if failures else "success", results=results,
                   details={"candidate_count": len(candidates), "failed_candidates": failures})

def search(query):
    return search_stream(query, lambda row: None)

def scrape(query): return search(query)

def diagnose(query):
    session = requests.Session()
    try:
        try:
            c = _discover(clean(query), session)
            return {"diagnostic": True, "query": clean(query), "status": "success",
                     "candidate_count": len(c), "candidates": [x["url"] for x in c[:100]]}
        except StoreRequestError as e:
            return {"diagnostic": True, "query": clean(query), "status": e.kind,
                     "error": str(e), "candidate_count": 0, "candidates": []}
    finally: session.close()

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--diagnose", action="store_true")
    a = p.parse_args()
    print(json.dumps(diagnose(a.query) if a.diagnose else search(a.query), ensure_ascii=False, indent=2))
