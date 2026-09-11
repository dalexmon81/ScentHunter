"""ScentHunter - Deloox scraper.

Live first-party Deloox discovery.  The important rule here is that Deloox
product URLs are /product/<id>/..., not only category URLs.  Discovery is
bounded and product pages are parsed independently.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE = "https://www.deloox.com"
HOME = BASE + "/en"
TIMEOUT = (2.5, 6.0)
MAX_CANDIDATES = 12
MAX_RESULTS = 40

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", re.I)
PRICE_RE = re.compile(r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?")
NON_FRAGRANCE = ("body mist", "body spray", "body lotion", "body cream", "deodorant", "after shave", "aftershave", "shower gel", "soap", "hair mist")


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(r"[^a-z0-9]+", " ", clean(v).lower()).strip()


def tokens(v):
    return {x for x in norm(v).split() if len(x) > 1}


def size_ml(*values):
    m = SIZE_RE.search(" ".join(clean(x) for x in values if x))
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    if m.group(2).lower() == "cl":
        n *= 10
    return int(n) if n.is_integer() else n


def price_num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 2)
    text = clean(v).replace("\xa0", " ")
    m = re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d{2})?)(?!\d)", text)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return round(n, 2) if 0 < n < 10000 else None


def price_text(v):
    n = price_num(v)
    return f"{n:.2f}".replace(".", ",") + " €" if n is not None else None


def availability(value):
    text = norm(value)
    if any(x in text for x in ("out of stock", "outofstock", "sold out", "soldout", "unavailable", "not available")):
        return "out_of_stock"
    if any(x in text for x in ("in stock", "instock", "available", "add to cart", "in winkelwagen")):
        return "in_stock"
    return None


def get(session, url):
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code >= 400 or not r.text:
            return None
        return r
    except requests.RequestException:
        return None


def is_product_url(url):
    try:
        p = urlparse(url)
    except Exception:
        return False
    host = p.netloc.lower().split(":", 1)[0]
    # Deloox localizes traffic to country domains. Search/category pages can
    # return absolute product links on country domains even when discovery
    # started from deloox.com.
    if not re.fullmatch(r"(?:www\.)?deloox\.(?:com|nl|es|fr|de|it|be)", host):
        return False
    return bool(re.search(r"/(?:product|produit|producto)/\d+/", p.path, re.I))


def product_url(raw):
    url = urljoin(BASE + "/", clean(raw)).split("#", 1)[0].split("?", 1)[0]
    return url if is_product_url(url) else ""


def relevant(text, query):
    q = tokens(query)
    if not q:
        return False
    hay = norm(text)
    hits = sum(t in hay for t in q)
    if len(q) == 1:
        return hits == 1
    return hits >= max(2, len(q) - 1)


def non_fragrance(text):
    t = norm(text)
    return any(norm(x) in t for x in NON_FRAGRANCE)


def extract_candidates(html, query):
    soup = BeautifulSoup(html, "html.parser")
    q = tokens(query)
    scored = {}

    def add(raw, context=""):
        url = product_url(raw)
        if not url:
            return
        blob = norm(f"{context} {url}")
        hits = sum(t in blob for t in q)
        if q and hits == 0:
            return
        old = scored.get(url)
        if old is None or hits > old[0]:
            scored[url] = (hits, clean(context))

    for a in soup.find_all("a", href=True):
        add(a.get("href"), a.get_text(" ", strip=True))

    html_urls = re.findall(r"(?:https?:)?//(?:www\.)?deloox\.(?:com|nl|es)/[^\"'<>\s]+/(?:product|produit|producto)/\d+/[^\"'<>\s]+", html, re.I)
    for raw in html_urls:
        add(raw)

    for tag in soup.find_all(["article", "li", "div"], limit=2500):
        blob = str(tag)
        if "/product/" not in blob.lower() and "/producto/" not in blob.lower() and "/produit/" not in blob.lower():
            continue
        if len(blob) > 10000:
            continue
        context = tag.get_text(" ", strip=True)[:1200]
        if not relevant(context, query):
            continue
        for a in tag.find_all("a", href=True):
            add(a.get("href"), context)

    ordered = sorted(scored.items(), key=lambda x: (-x[1][0], len(x[0]), x[0]))
    return [u for u, _ in ordered[:MAX_CANDIDATES]]


def discover(session, query):
    candidates = []
    seen = set()
    encoded = quote_plus(query)
    endpoints = (
        f"{BASE}/en/search?query={encoded}",
        f"{BASE}/en/search?q={encoded}",
        f"{BASE}/en/search?search={encoded}",
        f"{BASE}/en/search?searchTerm={encoded}",
    )
    for endpoint in endpoints:
        r = get(session, endpoint)
        if not r:
            continue
        for url in extract_candidates(r.text, query):
            if url not in seen:
                seen.add(url); candidates.append(url)
        if candidates:
            return candidates[:MAX_CANDIDATES]

    # Fallback: the public fragrance catalog is first-party and searchable by
    # product text. This is bounded to the first catalog page returned by Deloox.
    for url in (f"{BASE}/en/category/1103659/fragrances.html", f"{BASE}/en/category/1121334/french-avenue-mens-fragrances.html"):
        r = get(session, url)
        if not r:
            continue
        for candidate in extract_candidates(r.text, query):
            if candidate not in seen:
                seen.add(candidate); candidates.append(candidate)
            if len(candidates) >= MAX_CANDIDATES:
                return candidates[:MAX_CANDIDATES]
    return candidates[:MAX_CANDIDATES]


def jsonld_products(soup):
    out = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
        except Exception:
            continue
        queue = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item); continue
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "Product" or (isinstance(item.get("@type"), list) and "Product" in item.get("@type")):
                out.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
    return out


def parse_product(url, query):
    session = requests.Session()
    r = get(session, url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    rows = []

    products = jsonld_products(soup)
    for p in products:
        name = clean(p.get("name") or query)
        if not relevant(name, query) or non_fragrance(name):
            continue
        brand = p.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        offers = p.get("offers")
        offers = offers if isinstance(offers, list) else ([offers] if isinstance(offers, dict) else [])
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            n = price_num(offer.get("price"))
            if n is None:
                continue
            state = availability(offer.get("availability"))
            rows.append({"store": STORE, "brand": clean(brand), "name": name, "price": price_text(n), "price_num": n, "url": url, "available": state != "out_of_stock", "availability": state or "in_stock", "size_ml": size_ml(name, p.get("description", ""))})

    # HTML fallback: use the product title and the first plausible price/size.
    if not rows:
        title = ""
        node = soup.find("h1")
        if node:
            title = clean(node.get_text(" ", strip=True))
        if not title:
            meta = soup.find("meta", attrs={"property": "og:title"})
            title = clean(meta.get("content") if meta else query)
        if relevant(title, query) and not non_fragrance(title):
            text = soup.get_text(" ", strip=True)
            n = price_num(text)
            if n is not None:
                state = availability(text)
                rows.append({"store": STORE, "brand": "", "name": title, "price": price_text(n), "price_num": n, "url": url, "available": state != "out_of_stock", "availability": state or "in_stock", "size_ml": size_ml(title, text)})
    return rows


def search(query):
    query = clean(query)
    if not query:
        return []
    session = requests.Session()
    urls = discover(session, query)
    session.close()
    if not urls:
        return []
    results = []
    with ThreadPoolExecutor(max_workers=min(6, len(urls))) as pool:
        futures = [pool.submit(parse_product, url, query) for url in urls]
        for f in as_completed(futures):
            try:
                results.extend(f.result())
            except Exception:
                continue
    seen = set(); final = []
    for row in results:
        key = (row.get("url"), row.get("size_ml"), row.get("price_num"))
        if key in seen:
            continue
        seen.add(key); final.append(row)
    final.sort(key=lambda x: (2 if x.get("available") is False else 0, x.get("price_num") or 999999, x.get("size_ml") or 999999))
    return final[:MAX_RESULTS]


def scrape(query):
    return search(query)


def search_deloox(query):
    return search(query)
