import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, quote_plus

import requests
from bs4 import BeautifulSoup

STORE = "PerfumeMarket"
BASE = "https://www.perfumemarket.nl"
TIMEOUT = 12
RETRIES = 3
RETRY_SLEEP = 0.8
MAX_PRODUCT_URLS = 40
PRODUCT_WORKERS = 6

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    x = unicodedata.normalize("NFKD", clean(v).lower())
    x = "".join(c for c in x if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", x)).strip()


def toks(v):
    return [x for x in norm(v).split() if len(x) > 1]


def matches(t, q):
    query_tokens = set(toks(q))
    return bool(query_tokens) and query_tokens.issubset(set(toks(t)))


def size_ml(v):
    m = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", clean(v), re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    n *= 10 if m.group(2).lower() == "cl" else 1
    return int(n) if n.is_integer() else n


def concentration(v):
    t = norm(v)
    if re.search(r"\beau de toilette\b|\bedt\b", t):
        return "Eau de Toilette"
    if re.search(r"\beau de parfum\b|\bedp\b", t):
        return "Eau de Parfum"
    if re.search(r"\bextrait(?: de parfum)?\b", t):
        return "Extrait de Parfum"
    return None


def price(v):
    t = clean(v)
    if re.fullmatch(r"\d+(?:[.,]\d{1,2})?", t):
        return float(t.replace(",", "."))
    m = re.search(r"(?<![\d.,])(\d{1,4}(?:[.,]\d{2}))\s*€", t)
    return float(m.group(1).replace(",", ".")) if m else None


def _get(session, url, **kwargs):
    for attempt in range(RETRIES):
        try:
            response = session.get(url, **kwargs)
            if response.ok:
                return response
            # Retry transient/rate-limit/server responses; do not spin on 404.
            if response.status_code not in {403, 408, 425, 429} and response.status_code < 500:
                return None
        except requests.RequestException:
            pass
        if attempt + 1 < RETRIES:
            time.sleep(RETRY_SLEEP * (attempt + 1))
    return None


def _xml_urls(text):
    soup = BeautifulSoup(text, "xml")
    return [x.get_text(strip=True) for x in soup.find_all("loc")]


def _candidate_urls_from_html(text, query):
    soup = BeautifulSoup(text or "", "html.parser")
    out = []
    seen = set()

    for a in soup.select('a[href*="/products/"]'):
        href = a.get("href")
        if not href:
            continue
        u = urljoin(BASE, href.split("?")[0].split("#")[0]).rstrip("/")
        if u in seen:
            continue
        label = clean(a.get_text(" ", strip=True))
        context = f"{label} {u}"
        if matches(context, query):
            seen.add(u)
            out.append(u)

    # Some Shopify themes expose product URLs only in JSON/script data.
    for match in re.findall(r'["\']([^"\']*/products/[^"\']+)["\']', text or "", re.I):
        u = urljoin(BASE, match.split("?")[0].split("#")[0]).rstrip("/")
        if u in seen:
            continue
        if matches(u, query):
            seen.add(u)
            out.append(u)

    return out


def _candidate_urls_from_json(data, query):
    out = []
    seen = set()

    def walk(x):
        if isinstance(x, dict):
            # Shopify search/suggest commonly exposes url/title fields.
            title = x.get("title") or x.get("name") or x.get("product_title") or ""
            handle = x.get("handle") or ""
            url = x.get("url") or x.get("product_url") or ""
            if not url and handle:
                url = f"/products/{handle}"
            if url:
                u = urljoin(BASE, str(url).split("?")[0].split("#")[0]).rstrip("/")
                context = f"{title} {handle} {u}"
                if u not in seen and matches(context, query):
                    seen.add(u)
                    out.append(u)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data)
    return out


def _shopify_discovery(s, q):
    """Fast Shopify-native discovery; avoids crawling the entire sitemap."""
    urls = []
    seen = set()

    def add_many(items):
        for u in items:
            u = str(u or "").strip().rstrip("/")
            if u and u not in seen:
                seen.add(u)
                urls.append(u)

    # 1) Shopify predictive search. This is normally the most reliable
    # discovery endpoint for a Shopify storefront.
    suggest_url = BASE + "/search/suggest.json"
    try:
        r = _get(
            s,
            suggest_url,
            params={
                "q": q,
                "resources[type]": "product",
                "resources[limit]": "20",
                "resources[options][unavailable_products]": "last",
            },
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if r:
            try:
                add_many(_candidate_urls_from_json(r.json(), q))
            except (ValueError, TypeError):
                pass
    except Exception:
        pass

    # 2) Normal Shopify product search page.
    try:
        r = _get(
            s,
            BASE + "/search",
            params={"q": q, "type": "product"},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if r:
            add_many(_candidate_urls_from_html(r.text, q))
    except Exception:
        pass

    # 3) Theme's language-prefixed search, retained as a separate fallback.
    try:
        r = _get(
            s,
            BASE + "/nl/search",
            params={"q": q, "type": "product"},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if r:
            add_many(_candidate_urls_from_html(r.text, q))
    except Exception:
        pass

    return urls


def _targeted_sitemap(s, q):
    """
    Sitemap is a fallback only. Never crawl every child sitemap synchronously:
    that was the main recall/timeout weakness of the old scraper.
    """
    out = []
    seen = set()

    # Product sitemaps are commonly discoverable from robots.txt without
    # downloading the entire catalog.
    try:
        r = _get(s, BASE + "/robots.txt", headers=HEADERS, timeout=TIMEOUT)
        if r:
            sitemap_urls = re.findall(
                r"(?im)^\s*sitemap:\s*(\S+)",
                r.text or "",
            )
            for sm_url in sitemap_urls[:8]:
                try:
                    sm = _get(s, sm_url, headers=HEADERS, timeout=TIMEOUT)
                    if not sm:
                        continue
                    for u in _xml_urls(sm.text):
                        if "/products/" in u.lower() and matches(u, q):
                            u = u.rstrip("/")
                            if u not in seen:
                                seen.add(u)
                                out.append(u)
                                if len(out) >= MAX_PRODUCT_URLS:
                                    return out
                except Exception:
                    continue
    except Exception:
        pass

    # Direct Shopify product sitemap fallback.
    for sm_url in (
        BASE + "/sitemap_products_1.xml?from=1&to=999999999999999999",
        BASE + "/sitemap_products_1.xml",
    ):
        if len(out) >= MAX_PRODUCT_URLS:
            break
        try:
            sm = _get(s, sm_url, headers=HEADERS, timeout=TIMEOUT)
            if not sm:
                continue
            for u in _xml_urls(sm.text):
                if "/products/" in u.lower() and matches(u, q):
                    u = u.rstrip("/")
                    if u not in seen:
                        seen.add(u)
                        out.append(u)
                        if len(out) >= MAX_PRODUCT_URLS:
                            break
        except Exception:
            continue

    return out


def _jsonld_product_data(soup):
    product_data = {}
    brand = None

    for sc in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(sc.get_text(strip=True))
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]
        while stack:
            x = stack.pop(0)
            if isinstance(x, list):
                stack.extend(x)
                continue
            if not isinstance(x, dict):
                continue

            types = x.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" in types or "offers" in x:
                if x.get("@type") == "Product" or "Product" in types:
                    product_data = x
                    brand = x.get("brand")
                    brand = brand.get("name") if isinstance(brand, dict) else brand
                    return product_data, brand

    return product_data, brand


def product(s, url, q):
    r = _get(s, url, headers=HEADERS, timeout=TIMEOUT)
    if not r:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    h = soup.find("h1")
    name = clean(h.get_text(" ", strip=True)) if h else ""

    # Do not require the URL/search result to be perfect; the central matcher
    # remains the final authority. Here we only require the product page itself
    # to contain the requested identity tokens.
    if not name or not matches(name, q):
        return None

    data, brand = _jsonld_product_data(soup)

    price_value = None
    offers = data.get("offers") if isinstance(data, dict) else None
    offers = offers if isinstance(offers, list) else [offers]
    for offer in offers:
        if isinstance(offer, dict):
            price_value = price(offer.get("price"))
            if price_value is not None:
                break

    if price_value is None:
        price_value = price(soup.get_text(" ", strip=True))
    if price_value is None:
        return None

    text = norm(soup.get_text(" ", strip=True))
    stock = (
        "out_of_stock"
        if any(x in text for x in ("out of stock", "uitverkocht", "niet beschikbaar"))
        else (
            "in_stock"
            if any(x in text for x in ("in stock", "op voorraad", "beschikbaar"))
            else "unknown"
        )
    )

    offer0 = next((x for x in offers if isinstance(x, dict)), {})
    structured_price = (
        price(offer0.get("price"))
        if offer0.get("price") is not None
        else None
    )
    final_price = structured_price if structured_price is not None else price_value

    av = offer0.get("availability")
    if av:
        av = str(av).lower()
        if "outofstock" in av or "out of stock" in av:
            stock = "out_of_stock"
        elif "instock" in av or "in stock" in av:
            stock = "in_stock"
        elif "preorder" in av:
            stock = "preorder"

    image = data.get("image") if isinstance(data, dict) else None
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    if not image:
        meta = soup.select_one('meta[property="og:image"]')
        image = meta.get("content") if meta else None
    image = urljoin(url, str(image)) if image else None

    def _val(*keys):
        for key in keys:
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, dict):
                value = value.get("name") or value.get("value") or value.get("@id")
            if value not in (None, ""):
                return str(value).strip()
        return None

    gtin = _val("gtin", "gtin13", "gtin12", "gtin14")
    mpn = _val("mpn")
    sku = _val("sku")
    product_id = _val("productID", "productId", "product_id")

    t = norm(name)
    gender = (
        "women"
        if re.search(r"\b(women|woman|dames|dame|femme|female)\b", t)
        else (
            "men"
            if re.search(r"\b(men|man|heren|homme|male)\b", t)
            else ("unisex" if "unisex" in t else "unknown")
        )
    )

    size = size_ml(name)
    conc = concentration(name)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": clean(brand) or None,
            "url": url,
            "image": image,
        },
        "identity": {
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
            "mpn": {"value": mpn, "source": "jsonld"} if mpn else None,
            "sku": {"value": sku, "source": "jsonld"} if sku else None,
            "store_product_id": (
                {"value": product_id, "source": "jsonld"} if product_id else None
            ),
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {"value": size, "source": "product_title"} if size is not None else None,
            "concentration": {"value": conc, "source": "product_title"} if conc else None,
            "gender": {"value": gender, "source": "product_title"},
            "packaging_type": {"value": "product", "source": "default"},
        },
        "offer": {
            "price": round(final_price, 2),
            "currency": "EUR",
            "availability": stock,
        },
        "provenance": {
            "source_page": url,
            "name_source": "h1",
            "brand_source": "jsonld" if brand else None,
            "price_source": "jsonld" if structured_price is not None else "page",
            "product_source": "jsonld" if data else "product_page",
            "availability_source": "jsonld" if av else "page_text",
        },
        "raw_data": {"jsonld": data},
        "name": name,
        "price": f"{final_price:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": stock == "in_stock",
    }


def search(q):
    q = clean(q)
    if not q:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # Three independent discovery paths, all fast and bounded.
        candidates = []
        seen = set()

        for u in _shopify_discovery(session, q):
            if u not in seen:
                seen.add(u)
                candidates.append(u)

        # Only use sitemap if normal discovery found nothing. This prevents a
        # slow sitemap from delaying an otherwise successful search.
        if not candidates:
            for u in _targeted_sitemap(session, q):
                if u not in seen:
                    seen.add(u)
                    candidates.append(u)

        candidates = candidates[:MAX_PRODUCT_URLS]

        if not candidates:
            return []

        out = []
        seen_products = set()

        with ThreadPoolExecutor(max_workers=min(PRODUCT_WORKERS, len(candidates))) as executor:
            futures = {
                executor.submit(product, session, u, q): u
                for u in candidates
            }
            for future in as_completed(futures):
                try:
                    item = future.result()
                except Exception:
                    item = None
                if item and item.get("url") not in seen_products:
                    seen_products.add(item["url"])
                    out.append(item)

        return out
    finally:
        session.close()


def diagnose(q):
    q = clean(q)
    if not q:
        return {"diagnostic": True, "query": q, "error": "empty_query"}

    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        shopify = _shopify_discovery(session, q)
        sitemap = _targeted_sitemap(session, q) if not shopify else []

        candidates = []
        seen = set()
        for u in shopify + sitemap:
            if u not in seen:
                seen.add(u)
                candidates.append(u)

        product_pages = []
        for u in candidates[:MAX_PRODUCT_URLS]:
            item = product(session, u, q)
            product_pages.append({
                "url": u,
                "accepted": bool(item),
                "name": item.get("name") if item else None,
                "price": item.get("price") if item else None,
            })

        return {
            "diagnostic": True,
            "query": q,
            "discovery_source": "shopify+sitemap_fallback",
            "shopify_candidates": shopify,
            "sitemap_candidates": sitemap,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "product_pages": product_pages,
        }
    finally:
        session.close()
