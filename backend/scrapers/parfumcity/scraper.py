import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

STORE = "ParfumCity"
BASE_URL = "https://www.parfumcity.nl"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

def _clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def _words(s):
    return [x for x in re.findall(r"[a-z0-9]+", _clean(s).lower()) if len(x) > 1]

def _matches(text, query):
    t = _clean(text).lower()
    return all(w in t for w in _words(query))

def _price(text):
    vals = re.findall(r"€\s*(\d{1,4}(?:[.,]\d{2})?)", text or "")
    return (vals[-1].replace(".", ",") + "€") if vals else ""

def search(query):
    query = _clean(query)
    if not query:
        return []

    url = BASE_URL + "/search?q=" + quote_plus(query)
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        r.raise_for_status()
    except requests.RequestException as e:
        print("PARFUMCITY ERROR:", e)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results, seen = [], set()

    for a in soup.select('a[href*="/products/"]'):
        href = a.get("href", "")
        product_url = urljoin(BASE_URL, href).split("?")[0]
        if product_url in seen:
            continue

        node = a
        card = None
        for _ in range(7):
            if node is None:
                break
            txt = _clean(node.get_text(" ", strip=True))
            if "€" in txt and _matches(txt, query):
                card = node
                break
            node = node.parent
        if card is None:
            continue

        text = _clean(card.get_text(" ", strip=True))
        low = text.lower()
        if any(x in low for x in ("sample", "decant", "tester service", "sample service")):
            continue

        name = ""
        for h in card.find_all(["h2","h3","h4"]):
            candidate = _clean(h.get_text(" ", strip=True))
            if candidate and _matches(candidate, query):
                name = candidate
                break
        if not name:
            candidate = _clean(a.get_text(" ", strip=True))
            if _matches(candidate, query):
                name = candidate
        if not name:
            continue

        price = _price(text)
        if not price:
            continue

        seen.add(product_url)
        results.append({"store": STORE, "name": name, "price": price, "url": product_url})
        if len(results) >= 10:
            break

    return results
