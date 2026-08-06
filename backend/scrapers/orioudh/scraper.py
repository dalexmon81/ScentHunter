import json
import re
import html
from typing import List, Dict, Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}

def _clean(v) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(v or ""))).strip()

def _norm(v) -> str:
    s = _clean(v).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def _tokens(q: str):
    return [x for x in _norm(q).split() if len(x) > 1]

def _matches(text: str, query: str) -> bool:
    n = _norm(text)
    return all(t in n for t in _tokens(query))

def _price(v) -> Optional[str]:
    if v is None:
        return None
    s = _clean(v).replace("€", "").strip()
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", s)
    if not m:
        return None
    try:
        x = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    if x <= 0:
        return None
    return f"{x:.2f}".replace(".", ",") + " €"

def _from_shopify_json(session: requests.Session, query: str) -> List[Dict[str, str]]:
    url = BASE_URL + "/search/suggest.json?q=" + quote_plus(query) + "&resources[type]=product&resources[limit]=20"
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
    except (requests.RequestException, ValueError):
        return []

    products = data.get("resources", {}).get("results", {}).get("products", [])
    results = []
    seen = set()

    for p in products:
        title = _clean(p.get("title"))
        vendor = _clean(p.get("vendor"))
        if not _matches(title + " " + vendor, query):
            continue
        url = urljoin(BASE_URL, p.get("url") or "")
        if not url or url in seen:
            continue
        price = _price(p.get("price")) or _price(p.get("price_min"))
        if not price:
            continue
        seen.add(url)
        results.append({"store": STORE, "name": title, "price": price, "url": url})
    return results

def _from_search_html(session: requests.Session, query: str) -> List[Dict[str, str]]:
    url = BASE_URL + "/search?q=" + quote_plus(query) + "&type=product"
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return []
    except requests.RequestException:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    seen = set()

    for a in soup.select('a[href*="/products/"]'):
        href = urljoin(BASE_URL, a.get("href", "")).split("?")[0]
        if href in seen:
            continue
        card = a
        for _ in range(5):
            if not card.parent:
                break
            card = card.parent
            txt = _clean(card.get_text(" ", strip=True))
            if "€" in txt and len(txt) < 1200:
                break
        text = _clean(card.get_text(" ", strip=True))
        title = _clean(a.get("title") or a.get_text(" ", strip=True))
        if not title or not _matches(title + " " + text, query):
            continue
        prices = re.findall(r"\b\d{1,4}[.,]\d{2}\s*€", text)
        price = next((_price(raw) for raw in prices if _price(raw)), None)
        if not price:
            continue
        seen.add(href)
        results.append({"store": STORE, "name": title, "price": price, "url": href})
    return results

def search(query: str) -> List[Dict[str, str]]:
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    results = _from_shopify_json(session, query)
    if not results:
        results = _from_search_html(session, query)

    final = []
    seen = set()
    for item in results:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        final.append(item)
    return final

if __name__ == "__main__":
    print(search("Rasasi Hawas"))
