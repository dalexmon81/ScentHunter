import json
import re
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = 5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}

STOPWORDS = {
    "eau","de","parfum","perfume","edp","edt","extrait","spray","for","by","pour",
    "ml","cl","men","man","women","woman","male","female","homme","femme","herren","damen",
}


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(v).lower())).strip()


def query_tokens(q):
    out = []
    for token in norm(q).split():
        if token in STOPWORDS or re.fullmatch(r"\d+(?:[.,]\d+)?", token):
            continue
        out.append(token)
    return out


def matches(text, q):
    hay = set(norm(text).split())
    toks = query_tokens(q)
    return bool(toks) and all(t in hay for t in toks)


def size_ml(*values):
    m = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        " ".join(clean(x) for x in values),
        re.I,
    )
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    if m.group(2).lower() == "cl":
        n *= 10
    return int(n) if n.is_integer() else n


def concentration(*values):
    t = norm(" ".join(clean(x) for x in values))
    if re.search(r"\beau de toilette\b|\bedt\b", t):
        return "Eau de Toilette"
    if re.search(r"\bextrait(?: de parfum)?\b", t):
        return "Extrait de Parfum"
    if re.search(r"\beau de parfum\b|\bedp\b", t):
        return "Eau de Parfum"
    return None


def price(v):
    if v in (None, ""):
        return None
    # Shopify product JSON normally exposes integer prices in cents.
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = float(v)
        if n.is_integer() and abs(n) >= 100:
            n /= 100.0
        return round(n, 2)
    s = clean(v).replace("€", "").strip()
    m = re.search(r"\d+(?:[.,]\d{1,2})?", s)
    if not m:
        return None
    raw = m.group(0)
    try:
        n = float(raw.replace(",", "."))
        if re.fullmatch(r"\d+", raw) and n >= 100:
            n /= 100.0
        return round(n, 2)
    except ValueError:
        return None


def _get(session, url, params=None):
    try:
        r = session.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        return r if r.ok else None
    except requests.RequestException:
        return None


def _urls_from_sitemap(session, q, limit=80):
    urls = []
    seen = set()
    try:
        r = _get(session, BASE_URL + "/robots.txt")
        if not r:
            return []
        sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text or "")
        queue = sitemaps[:3]
        while queue and len(urls) < limit:
            sm = queue.pop(0)
            x = _get(session, sm)
            if not x:
                continue
            soup = BeautifulSoup(x.text, "xml")
            locs = [u.get_text(strip=True) for u in soup.find_all("loc")]
            for u in locs:
                if u.endswith(".xml") or "sitemap" in u.lower():
                    if u not in queue and u not in seen:
                        queue.append(u)
                elif "/products/" in u and matches(u, q):
                    u = u.split("?")[0].rstrip("/")
                    if u not in seen:
                        seen.add(u)
                        urls.append(u)
                        if len(urls) >= limit:
                            break
    except Exception:
        pass
    return urls


def _urls_from_shopify_catalog(session, q, limit=120):
    """Generic Shopify catalogue fallback.

    Shopify search endpoints can intermittently return no candidates. The public
    products.json catalogue is independent of the search UI and exposes the
    exact product handles plus variant availability. This is deliberately
    generic: no perfume/product handles are hard-coded here.
    """
    urls = []
    seen = set()

    def add_product(p):
        if not isinstance(p, dict):
            return
        title = clean(p.get("title"))
        vendor = clean(p.get("vendor"))
        handle = clean(p.get("handle"))
        hay = f"{title} {vendor} {handle}"
        if not matches(hay, q):
            return
        if not handle:
            return
        u = BASE_URL + "/products/" + handle
        if u not in seen:
            seen.add(u)
            urls.append(u)

    # The store currently exposes a large Shopify catalogue. Paginate until a
    # page is empty; stop once enough relevant candidates are found.
    endpoints = [
        BASE_URL + "/products.json",
        BASE_URL + "/collections/all/products.json",
    ]

    for endpoint in endpoints[:1]:
        for page in range(1, 4):
            r = _get(session, endpoint, {"limit": 250, "page": page})
            if not r:
                break
            try:
                data = r.json()
            except (ValueError, TypeError):
                break
            products = data.get("products") if isinstance(data, dict) else None
            if not isinstance(products, list) or not products:
                break
            for product in products:
                add_product(product)
                if len(urls) >= limit:
                    return urls[:limit]
            if len(products) < 250:
                break

    return urls[:limit]


def _discover(session, q):
    """Fast, bounded Shopify discovery.

    The old implementation tried several query variants, then HTML search,
    then a multi-page public catalogue and finally sitemaps. That is far too
    expensive for a normal comparison search. Shopify's suggest endpoint is
    the primary search surface and is explicitly asked to include unavailable
    products, which is important because Out of Stock must remain visible.
    """
    urls = []
    seen = set()

    def add(u):
        if not u:
            return
        u = urljoin(BASE_URL, str(u)).split("?")[0].split("#")[0].rstrip("/")
        # Canonicalize host so www/non-www cannot create duplicate offers.
        u = re.sub(r"^https?://www\.orioudh\.com", BASE_URL, u, flags=re.I)
        if "/products/" in u and u not in seen:
            seen.add(u)
            urls.append(u)

    # PRIMARY: one Shopify predictive-search request. Keep the full query so
    # both Liquid Brun variants can be returned together.
    r = _get(session, BASE_URL + "/search/suggest.json", {
        "q": q,
        "resources[type]": "product",
        "resources[limit]": 20,
        "resources[options][unavailable_products]": "show",
    })
    if r:
        try:
            data = r.json()
            products = ((data.get("resources") or {}).get("results") or {}).get("products") or []
            for product in products:
                if not isinstance(product, dict):
                    continue
                u = product.get("url") or product.get("product_url")
                if matches(f"{product.get('title','')} {product.get('vendor','')} {u or ''}", q):
                    add(u)
        except (ValueError, TypeError):
            pass

    if urls:
        return urls[:8]

    # ONE fallback: Shopify's normal search page. No catalogue/sitemap crawl.
    r = _get(session, BASE_URL + "/search", {"q": q, "type": "product"})
    if r:
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select('a[href*="/products/"]'):
            u = a.get("href")
            text = f"{a.get('title','')} {a.get_text(' ',strip=True)} {u or ''}"
            if matches(text, q):
                add(u)
                if len(urls) >= 8:
                    break

    return urls[:8]

def _product_json(session, url):
    r = _get(session, url.rstrip("/") + ".js")
    if not r:
        return None
    try:
        data = r.json()
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def _item(product, variant, url):
    name = clean(product.get("title"))
    vname = clean(variant.get("title"))
    source_name = name if not vname or vname == "Default Title" else f"{name} {vname}"

    if not matches(f"{name} {product.get('vendor','')} {url}", CURRENT_QUERY):
        return None

    p = price(variant.get("price"))
    if p is None:
        return None

    size = size_ml(vname, name)
    conc = concentration(vname, name)

    # Shopify's variant.available is authoritative for the specific variant.
    # True = in stock, False = out of stock, missing = unknown.
    available = variant.get("available")
    if available is True:
        stock = "in_stock"
    elif available is False:
        stock = "out_of_stock"
    else:
        stock = "unknown"

    image = product.get("featured_image")
    if isinstance(image, dict):
        image = image.get("src") or image.get("url")
    if not image:
        imgs = product.get("images") or []
        image = imgs[0] if imgs else None

    return {
        "store": STORE,
        "source": {
            "source_name": source_name,
            "source_brand": clean(product.get("vendor")) or None,
            "url": url,
            "image": urljoin(BASE_URL, str(image)) if image else None,
        },
        "identity": {
            "gtin": None,
            "mpn": None,
            "sku": ({"value": str(variant.get("sku")), "source": "shopify_variant"} if variant.get("sku") else None),
            "store_product_id": ({"value": product.get("id"), "source": "shopify_product"} if product.get("id") is not None else None),
            "store_variant_id": ({"value": variant.get("id"), "source": "shopify_variant"} if variant.get("id") is not None else None),
        },
        "attributes": {
            "size_ml": ({"value": size, "source": "product_variant"} if size is not None else None),
            "concentration": ({"value": conc, "source": "product_title"} if conc else None),
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
        },
        "offer": {"price": p, "currency": "EUR", "availability": stock},
        "provenance": {
            "source_page": url,
            "product_source": "shopify_product_json",
            "variant_source": "shopify_product_json",
        },
        "raw_data": {"product": product, "variant": variant},
        "name": name,
        "price": f"{p:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": available,
    }


CURRENT_QUERY = ""


def search(query):
    global CURRENT_QUERY
    CURRENT_QUERY = clean(query)
    if not CURRENT_QUERY:
        return []

    # Discover first, with at most two HTTP requests.
    session = requests.Session()
    try:
        discovered = _discover(session, CURRENT_QUERY)[:8]
    finally:
        session.close()

    if not discovered:
        return []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch_one(url):
        try:
            r = requests.get(
                url.rstrip("/") + ".js",
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            return None
        if not r.ok:
            return None
        try:
            data = r.json()
        except (ValueError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    out = []
    seen = set()
    with ThreadPoolExecutor(max_workers=min(4, len(discovered))) as pool:
        futures = {
            pool.submit(fetch_one, url): url for url in discovered
        }
        for future in as_completed(futures):
            url = futures[future]
            data = future.result()
            if not data:
                continue
            variants = data.get("variants") or []
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                item = _item(data, variant, url)
                if not item:
                    continue
                variant_id = (item["identity"].get("store_variant_id") or {}).get("value")
                # URL + variant id is the real Shopify offer identity. Also
                # canonicalize the URL to prevent www/non-www duplicates.
                canonical_url = re.sub(
                    r"^https?://www\.orioudh\.com",
                    BASE_URL,
                    item["url"].rstrip("/"),
                    flags=re.I,
                )
                key = (canonical_url, variant_id)
                if key in seen:
                    continue
                seen.add(key)
                item["url"] = canonical_url
                item["source"]["url"] = canonical_url
                out.append(item)

    return out

def scrape(query):
    return search(query)


def diagnose(query):
    global CURRENT_QUERY
    CURRENT_QUERY = clean(query)
    session = requests.Session()
    try:
        urls = _discover(session, CURRENT_QUERY)
        return {
            "diagnostic": True,
            "query": CURRENT_QUERY,
            "candidate_count": len(urls),
            "candidates": urls[:50],
        }
    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    print(json.dumps(
        diagnose(args.query) if args.diagnose else search(args.query),
        ensure_ascii=False,
        indent=2,
    ))
