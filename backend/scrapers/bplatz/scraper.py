import re
import requests
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin

STORE = "Bplatz"
BASE = "https://en.bplatz.de"
CATALOG_URL = BASE + "/collections/produkte"
TIMEOUT = 4
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def norm(v):
    v = str(v or "").lower()
    v = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", v)
    v = re.sub(r"[^a-z0-9]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()


def match(text, query):
    words = norm(query).split()
    hay = norm(text)
    return bool(words) and all(w in hay for w in words)


def money(v):
    try:
        n = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if n >= 1000:
        n /= 100.0
    return round(n, 2)


def fmt(n):
    return f"{n:.2f}".replace(".", ",") + " €" if n is not None else ""


def product_card(a):
    node = a
    best = a
    for _ in range(8):
        parent = getattr(node, "parent", None)
        if not isinstance(parent, Tag):
            break
        text = " ".join(parent.stripped_strings)
        if len(text) > 1500:
            break
        best = parent
        if "€" in text and ("Add to" in text or "Wishlist" in text or "retail price" in text.lower()):
            return parent
        node = parent
    return best


def extract_cards(html, query):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"]).split("#")[0]
        if "/products/" not in href.lower():
            continue
        card = product_card(a)
        card_text = " ".join(card.stripped_strings)
        img = card.find("img")
        candidates = [
            " ".join(a.stripped_strings).strip(),
            (a.get("title") or "").strip(),
            (img.get("alt") or "").strip() if img else "",
        ]
        name = next((x for x in candidates if x and match(x, query)), "")
        if not name:
            for pa in card.find_all("a", href=True):
                txt = " ".join(pa.stripped_strings).strip()
                if "/products/" in urljoin(BASE, pa["href"]).lower() and txt and match(txt, query):
                    name = txt
                    href = urljoin(BASE, pa["href"]).split("#")[0]
                    break
        if not name:
            continue
        key = (href, norm(name))
        if key in seen:
            continue
        seen.add(key)
        out.append({"store": STORE, "name": name, "url": href, "card_price": _card_price(card_text)})
    return out


def _card_price(text):
    for pat in (
        r"sale\s+price\s*€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"retail\s+price\s*€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"(\d{1,4}(?:[.,]\d{2})?)\s*€",
    ):
        m = re.search(pat, text, re.I)
        if m:
            n = money(m.group(1))
            if n is not None and n > 0:
                return fmt(n)
    return ""


def product_json(session, url):
    try:
        r = session.get(url.rstrip("/") + ".js", headers=HEADERS, timeout=TIMEOUT)
        if r.ok:
            return r.json()
    except (requests.RequestException, ValueError):
        pass
    return None


def enrich(session, item):
    data = product_json(session, item["url"])
    if not isinstance(data, dict):
        item["availability"] = "unknown"
        item["available"] = None
        item["price"] = item.get("card_price", "")
        return item

    variants = [v for v in (data.get("variants") or []) if isinstance(v, dict)]
    if not variants:
        item["availability"] = "unknown"
        item["available"] = None
        item["price"] = item.get("card_price", "")
        return item

    states = [v.get("available") for v in variants if isinstance(v.get("available"), bool)]
    available_variants = [v for v in variants if v.get("available") is True]

    if states and not available_variants:
        item["availability"] = "out_of_stock"
        item["available"] = False
        item["price"] = ""
        return item

    item["availability"] = "in_stock" if available_variants else "unknown"
    item["available"] = True if available_variants else None

    prices = []
    for v in (available_variants or variants):
        n = money(v.get("price"))
        if n is not None and n > 0:
            prices.append(n)
    item["price"] = fmt(min(prices)) if prices else item.get("card_price", "")
    return item


def search(query):
    query = str(query or "").strip()
    if not query:
        return []
    session = requests.Session()
    results, seen = [], set()
    try:
        for page in range(1, 31):
            try:
                r = session.get(CATALOG_URL, params={"page": page}, headers=HEADERS, timeout=TIMEOUT)
                if r.status_code != 200:
                    break
            except requests.RequestException:
                break
            cards = extract_cards(r.text, query)
            for item in cards:
                if item["url"] in seen:
                    continue
                seen.add(item["url"])
                results.append(enrich(session, item))
            soup = BeautifulSoup(r.text, "html.parser")
            if not any("/products/" in urljoin(BASE, a.get("href", "")).lower() for a in soup.find_all("a", href=True)):
                break
            # Keep scanning pages so availability is based on the real product data,
            # but stop after enough unique matches for this exact query.
            if len(results) >= 20:
                break
        for item in results:
            item.pop("card_price", None)
        return results
    finally:
        session.close()


def scrape(query):
    return search(query)
