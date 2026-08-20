from __future__ import annotations

import json
import re
import html as html_lib
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/it/",
}
PRICE_RE = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*€")
PRODUCT_URL_RE = re.compile(r"^https?://(?:www\.)?sabina\.com/it/(?!content|ricerca|ricerca_old|marchi|negozi|contatto|faq|carrello|ordine|stato-ordine|il-mio-conto|module/)", re.I)


def clean(v):
    return re.sub(r"\s+", " ", html_lib.unescape(str(v or ""))).strip()


def norm(v):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9à-ÿ]+", " ", clean(v).lower())).strip()


def query_matches(text, query):
    words = [w for w in norm(query).split() if len(w) > 1 and w not in {"eau", "de", "parfum", "perfume", "edp", "edt", "extrait", "spray", "for", "by", "ml", "pour"}]
    hay = norm(text)
    return bool(words) and all(w in hay for w in words)


def normalise_url(url):
    if not url:
        return None
    absolute = urljoin(BASE, clean(url))
    p = urlparse(absolute)
    if p.scheme not in {"http", "https"} or p.netloc.lower() not in {"sabina.com", "www.sabina.com"}:
        return None
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/')}"


def is_product_url(url):
    return bool(url and PRODUCT_URL_RE.match(url))


def price_value(v):
    m = PRICE_RE.search(clean(v))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def price_text(n):
    return f"{n:.2f}".replace(".", ",") + " €" if n is not None else ""


def extract_current_price(text):
    text = clean(text)
    # Prefer the explicitly labelled current/sale price. Never take
    # "Prezzo normale" / "Precio normal" as the selling price.
    patterns = (
        r"(?:Prezzo|Precio|Price|Prix)\s*:\s*(\d{1,4}(?:[.,]\d{2}))\s*€",
        r"(?:Prezzo|Precio|Price|Prix)\s+(?:finale|actual|actuel|sale)\s*:?\s*(\d{1,4}(?:[.,]\d{2}))\s*€",
        r"(?:current price|sale price|selling price)\s*:?\s*(\d{1,4}(?:[.,]\d{2}))\s*€",
    )
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return price_text(float(m.group(1).replace(",", ".")))

    # If only labelled normal + current prices exist in nearby text, use the
    # last explicitly non-normal labelled price.
    matches = list(PRICE_RE.finditer(text))
    if not matches:
        return ""
    normal_spans = []
    for m in re.finditer(r"(?:Prezzo normale|Precio normal|Normal price|Prix normal)\s*:?\s*\d{1,4}(?:[.,]\d{2})\s*€", text, re.I):
        normal_spans.append((m.start(), m.end()))
    candidates = []
    for m in matches:
        if any(a <= m.start() < b for a, b in normal_spans):
            continue
        candidates.append(m)
    m = candidates[-1] if candidates else matches[-1]
    return price_text(float(m.group(1).replace(",", ".")))


def _availability_from_value(v):
    s = norm(v)
    if any(x in s for x in ("outofstock", "out of stock", "soldout", "sold out", "unavailable", "indisponible", "rupture de stock", "esaurito")):
        return False
    if any(x in s for x in ("instock", "in stock", "available", "disponible", "en stock")):
        return True
    return None


def structured_product(soup):
    found = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, list):
                stack.extend(obj)
                continue
            if not isinstance(obj, dict):
                continue
            if isinstance(obj.get("@graph"), list):
                stack.extend(obj["@graph"])
            typ = obj.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if any(str(t).lower() == "product" for t in types):
                found.append(obj)
    return found


def page_details(session, url):
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
    except requests.RequestException:
        return None, None, None

    soup = BeautifulSoup(r.text, "html.parser")
    page_text = clean(soup.get_text(" ", strip=True))
    price = ""
    available = None

    for product in structured_product(soup):
        offers = product.get("offers")
        offers = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            state = _availability_from_value(offer.get("availability"))
            if state is not None:
                available = state if available is None else (available or state)
            p = offer.get("price") or offer.get("lowPrice")
            if p is not None and not price:
                try:
                    price = price_text(float(str(p).replace(",", ".")))
                except ValueError:
                    pass

    labelled = extract_current_price(page_text)
    if labelled:
        price = labelled

    low = page_text.lower()
    if any(x in low for x in ("out of stock", "sold out", "rupture de stock", "esaurito", "non disponibile")):
        # Only mark OOS if there is no clear purchase/availability signal.
        if not any(x in low for x in ("aggiungi al carrello", "add to cart", "disponibile", "en stock")):
            available = False
    if available is None and any(x in low for x in ("aggiungi al carrello", "add to cart", "acquista", "quantità")):
        available = True

    return price, available, r.text


def parse_search_html(text, query):
    soup = BeautifulSoup(text or "", "html.parser")
    rows = []
    for a in soup.find_all("a", href=True):
        url = normalise_url(a.get("href"))
        if not is_product_url(url):
            continue
        node = a
        for _ in range(8):
            parent = getattr(node, "parent", None)
            if not parent:
                break
            node = parent
            block = clean(node.get_text(" ", strip=True))
            if "€" in block and len(block) < 1800:
                break
        candidates = [a.get("title"), a.get("aria-label"), a.get_text(" ", strip=True)]
        for sel in ("h1", "h2", "h3", "h4", ".name", ".product-name", ".product-title"):
            for el in node.select(sel):
                candidates.append(el.get_text(" ", strip=True))
        name = next((clean(x) for x in candidates if clean(x) and query_matches(x, query)), "")
        if not name:
            continue
        rows.append({"store": STORE, "name": name, "url": url})
    return rows


def search(query):
    query = clean(query)
    if not query:
        return []
    session = requests.Session()
    session.headers.update(HEADERS)
    results, seen = [], set()
    try:
        try:
            session.get(BASE + "/it/", timeout=TIMEOUT, headers=HEADERS)
        except requests.RequestException:
            pass

        urls = [
            BASE + "/it/ricerca?search_query=" + quote_plus(query),
            BASE + "/it/ricerca_old?s=" + quote_plus(query),
            BASE + "/it/ricerca_old?search_query=" + quote_plus(query),
        ]
        candidates = []
        for url in urls:
            try:
                r = session.get(url, timeout=TIMEOUT, headers=HEADERS)
                r.raise_for_status()
                candidates.extend(parse_search_html(r.text, query))
            except requests.RequestException:
                continue

        for item in candidates:
            key = item["url"]
            if key in seen:
                continue
            seen.add(key)
            price, available, _ = page_details(session, key)
            if not price:
                continue
            item["price"] = price
            item["available"] = available
            item["availability"] = "in_stock" if available is True else "out_of_stock" if available is False else "unknown"
            results.append(item)
        return results
    finally:
        session.close()


def scrape(query):
    return search(query)

def search_sabina(query):
    return search(query)
