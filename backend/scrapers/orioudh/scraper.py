import json
import re
import html
from typing import List, Dict, Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = 25

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
    # Orioudh is Shopify. Its predictive-search endpoint returns the actual
    # product objects used by the storefront.
    endpoints = [
        BASE_URL + "/search/suggest.json?q={q}&resources[type]=product&resources[limit]=20",
        BASE_URL + "/search/suggest.json?q={q}&resources[type]=product&resources[options][unavailable_products]=show&resources[limit]=20",
    ]
    results = []
    seen = set()

    for template in endpoints:
        try:
            r = session.get(
                template.format(q=quote_plus(query)),
                headers=HEADERS, timeout=TIMEOUT
            )
            if r.status_code != 200:
                continue
            data = r.json()
        except (requests.RequestException, ValueError):
            continue

        products = (
            data.get("resources", {})
                .get("results", {})
                .get("products", [])
        )
        for p in products:
            title = _clean(p.get("title"))
            vendor = _clean(p.get("vendor"))
            text = title + " " + vendor
            if not _matches(text, query):
                continue

            url = urljoin(BASE_URL, p.get("url") or "")
            if not url or url in seen:
                continue

            price = _price(p.get("price"))
            if not price:
                # Some Shopify themes expose price_min instead.
                price = _price(p.get("price_min"))
            if not price:
                continue

            seen.add(url)
            results.append({
                "store": STORE,
                "name": title,
                "price": price,
                "url": url,
            })

        if results:
            break
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

    # Shopify product links are /products/<handle>.
    for a in soup.select('a[href*="/products/"]'):
        href = urljoin(BASE_URL, a.get("href", "")).split("?")[0]
        if href in seen:
            continue

        # Use the smallest useful surrounding card instead of a giant container.
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

        price = None
        # Orioudh displays prices like 36,90 €.
        prices = re.findall(r"\b\d{1,4}[.,]\d{2}\s*€", text)
        for raw in prices:
            price = _price(raw)
            if price:
                break
        if not price:
            continue

        seen.add(href)
        results.append({
            "store": STORE,
            "name": title,
            "price": price,
            "url": href,
        })
    return results

def _product_page(session: requests.Session, url: str, query: str) -> Optional[Dict[str, str]]:
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return None
    except requests.RequestException:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Shopify product JSON-LD.
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        objects = obj if isinstance(obj, list) else [obj]
        for x in objects:
            if not isinstance(x, dict) or x.get("@type") != "Product":
                continue
            name = _clean(x.get("name"))
            if not _matches(name, query):
                continue
            offers = x.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = _price(offers.get("price") if isinstance(offers, dict) else None)
            if price:
                return {"store": STORE, "name": name, "price": price, "url": r.url}

    h1 = soup.find("h1")
    name = _clean(h1.get_text(" ", strip=True)) if h1 else ""
    if not name or not _matches(name, query):
        return None
    text = _clean(soup.get_text(" ", strip=True))
    m = re.search(r"\b(\d{1,4}[.,]\d{2})\s*€", text)
    price = _price(m.group(1)) if m else None
    if not price:
        return None
    return {"store": STORE, "name": name, "price": price, "url": r.url}

def _is_out_of_stock_page(session, url):
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return False
    except requests.RequestException:
        return False

    soup = BeautifulSoup(r.text, "html.parser")

    # Check only the current product's purchase controls.
    selectors = (
        'button[name="add"]',
        '.product-form__submit',
        '[data-add-to-cart]',
        'button[type="submit"]',
    )

    controls = []
    for selector in selectors:
        controls.extend(soup.select(selector))

    unavailable = (
        "out of stock", "sold out", "unavailable",
        "ausverkauft", "nicht auf lager",
        "rupture de stock", "épuisé",
    )

    for control in controls:
        label = _clean(control.get_text(" ", strip=True)).lower()
        disabled = (
            control.has_attr("disabled")
            or str(control.get("aria-disabled", "")).lower() == "true"
        )

        if any(word in label for word in unavailable):
            return True

        if not disabled and any(word in label for word in ("add to cart", "buy now", "add")):
            return False

    return False


def search(query: str) -> List[Dict[str, str]]:
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()

    # Primary: Shopify's predictive search API.
    results = _from_shopify_json(session, query)

    # Fallback: server-rendered Shopify search.
    if not results:
        results = _from_search_html(session, query)

    # Verify availability on the real product page.
    # We keep unavailable products in ScentHunter, but replace the stale price
    # with a stock status so they sort after purchasable offers.
    final = []
    seen = set()

    for item in results:
        url = item["url"]
        if url in seen:
            continue
        seen.add(url)

        checked = dict(item)
        if _is_out_of_stock_page(session, url):
            checked["price"] = "Out of stock"

        final.append(checked)

    return final

if __name__ == "__main__":
    query = "Rasasi Hawas"
    results = search(query)
    print(f"QUERY: {query}")
    print(f"RISULTATI: {len(results)}")
    for item in results:
        print(item)
