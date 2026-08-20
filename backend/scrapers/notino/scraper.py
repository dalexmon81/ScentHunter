from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URLS = (
    BASE_URL + "/search.asp?exps={query}",
    BASE_URL + "/search?query={query}",
)
READER_BASE = "https://r.jina.ai/"
TIMEOUT = 8
READER_TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}
READER_HEADERS = {"User-Agent": "ScentHunter/1.0", "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}
PRICE_RE = re.compile(r"€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€", re.I)
PRODUCT_RE = re.compile(r"/p-\d+(?:/|$)", re.I)
GENERIC_TITLES = {"résultat de la recherche", "nombre de produits", "recherche", "produits", "résultats", "page", "chargement", "loading"}
OOS = ("en rupture de stock", "rupture de stock", "actuellement indisponible", "produit indisponible", "épuisé", "non disponible")


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(r"\s+", " ", clean(v).lower()).strip()


def tokens(v):
    return [x for x in re.findall(r"[a-z0-9]+", norm(v)) if len(x) > 1]


def matches(text, query):
    t = norm(text)
    return bool(tokens(query)) and all(x in t for x in tokens(query))


def format_price(v):
    m = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)", clean(v))
    if not m:
        return ""
    try:
        n = float(m.group(1).replace(",", "."))
    except ValueError:
        return ""
    return f"{n:.2f}".replace(".", ",") + "€" if n > 0 else ""


def prices(text):
    return [format_price(m.group(1) or m.group(2)) for m in PRICE_RE.finditer(clean(text))]


def product_url(url):
    try:
        p = urlparse(url)
    except Exception:
        return False
    return p.netloc.lower() in {"www.notino.fr", "notino.fr"} and bool(PRODUCT_RE.search(p.path))


def discovery_queries(query):
    base = clean(query)
    out, seen = [], set()
    def add(v):
        k = norm(v)
        if k and k not in seen:
            seen.add(k); out.append(clean(v))
    add(base)
    ts = tokens(base)
    if len(ts) > 1:
        for t in ts:
            if len(t) >= 3: add(t)
    return out[:5]


def narrow_card(link):
    node = link
    best = link
    for _ in range(6):
        parent = getattr(node, "parent", None)
        if parent is None:
            break
        text = clean(parent.get_text(" ", strip=True))
        if len(text) > 700:
            break
        best = parent
        if matches(text, link.get_text(" ", strip=True)) and prices(text):
            return parent
        node = parent
    return best


def candidate_from_link(link, query):
    url = urljoin(BASE_URL, clean(link.get("href"))).split("?")[0]
    if not product_url(url):
        return None
    title = clean(link.get("title") or link.get("aria-label") or link.get_text(" ", strip=True))
    card = narrow_card(link)
    card_text = clean(card.get_text(" ", strip=True))
    # Do not use a giant parent block: it is the source of unrelated 7,30€ prices.
    if not matches(f"{title} {card_text} {url}", query):
        return None
    name = title if matches(title, query) and len(title) <= 250 else ""
    if not name:
        for tag in card.find_all(["h1", "h2", "h3", "h4"]):
            x = clean(tag.get_text(" ", strip=True))
            if x and len(x) <= 250 and matches(x, query) and norm(x) not in GENERIC_TITLES:
                name = x; break
    if not name:
        return None
    # Price is only provisional; product page is authoritative.
    provisional = prices(link.get_text(" ", strip=True))
    if not provisional:
        provisional = prices(card_text)
    return {"url": url, "name": name, "provisional_price": provisional[-1] if provisional else ""}


def search_page(session, url, query):
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
    except requests.RequestException:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    out, seen = [], set()
    for link in soup.find_all("a", href=True):
        c = candidate_from_link(link, query)
        if c and c["url"] not in seen:
            seen.add(c["url"]); out.append(c)
    return out


def structured_products(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try: data = json.loads(script.get_text(strip=True))
        except Exception: continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list): stack.extend(x); continue
            if not isinstance(x, dict): continue
            if isinstance(x.get("@graph"), list): stack.extend(x["@graph"])
            typ = x.get("@type"); types = typ if isinstance(typ, list) else [typ]
            if any(str(t).lower() == "product" for t in types): yield x


def page_details(session, candidate, query):
    url = candidate["url"]
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        if r.url and product_url(r.url):
            final_url = r.url.split("?")[0]
        else:
            final_url = url
    except requests.RequestException:
        try:
            rr = session.get(READER_BASE + url, headers=READER_HEADERS, timeout=READER_TIMEOUT, allow_redirects=True)
            rr.raise_for_status()
            return reader_details(rr.text, candidate, query)
        except requests.RequestException:
            return None

    soup = BeautifulSoup(r.text, "html.parser")
    page_text = clean(soup.get_text(" ", strip=True))
    name = ""
    price = ""
    available = None

    for product in structured_products(soup):
        pname = clean(product.get("name"))
        brand = product.get("brand")
        brand = clean(brand.get("name")) if isinstance(brand, dict) else clean(brand)
        if not pname or not matches(f"{brand} {pname}", query):
            continue
        name = pname
        offers = product.get("offers")
        offers = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
        for offer in offers:
            if not isinstance(offer, dict): continue
            av = norm(offer.get("availability"))
            if any(x in av for x in ("outofstock", "soldout", "discontinued")):
                continue
            p = offer.get("price") or offer.get("lowPrice")
            if p and not price: price = format_price(p)
            if p: available = True
        if price: break

    if not name:
        h1 = soup.find("h1")
        if h1 and matches(h1.get_text(" ", strip=True), query): name = clean(h1.get_text(" ", strip=True))
    if not name:
        return None

    # Explicit current-price labels are preferred over old/list prices.
    for pat in (
        r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€",
        r"prix\s+(?:de\s+vente|final)\s*(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€",
    ):
        m = re.search(pat, page_text, re.I)
        if m:
            price = format_price(m.group(1)); break

    if not price:
        p = prices(page_text)
        # Product-page text can contain related products. Use the first price
        # only when no explicit current-price label was found and the product
        # structured data did not provide a price.
        if p: price = p[0]
    if not price:
        price = candidate.get("provisional_price", "")
    if not price:
        return None

    low = page_text.lower()
    if any(x in low for x in OOS) and "ajouter au panier" not in low and "en stock" not in low:
        available = False
    elif available is None:
        available = True

    return {"store": STORE, "name": name, "price": price, "url": final_url, "available": available, "availability": "in_stock" if available is True else "out_of_stock" if available is False else "unknown"}


def reader_details(text, candidate, query):
    content = clean(text)
    if not matches(content + " " + candidate["url"], query): return None
    name = candidate.get("name", "")
    for line in [x.strip() for x in (text or "").splitlines() if x.strip()][:100]:
        x = re.sub(r"^#+\s*", "", line).strip()
        if len(x) <= 220 and matches(x, query) and not PRICE_RE.search(x):
            name = x; break
    if not name: return None
    m = re.search(r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€", content, re.I)
    price = format_price(m.group(1)) if m else candidate.get("provisional_price", "")
    if not price:
        p = prices(content); price = p[0] if p else ""
    if not price: return None
    low = content.lower()
    available = not any(x in low for x in OOS)
    return {"store": STORE, "name": name, "price": price, "url": candidate["url"], "available": available, "availability": "in_stock" if available else "out_of_stock"}


def search(query):
    query = clean(query)
    if not query: return []
    session = requests.Session(); session.headers.update(HEADERS)
    candidates = {}; results = []; seen = set()
    try:
        for dq in discovery_queries(query):
            encoded = quote_plus(dq)
            for template in SEARCH_URLS:
                for c in search_page(session, template.format(query=encoded), dq):
                    candidates[c["url"]] = c
        # Details are authoritative and the original query is always used for final validation.
        for c in candidates.values():
            r = page_details(session, c, query)
            if not r: continue
            key = (r["url"], norm(r["name"]))
            if key in seen: continue
            seen.add(key); results.append(r)
        return results
    finally:
        session.close()


def scrape(query): return search(query)
