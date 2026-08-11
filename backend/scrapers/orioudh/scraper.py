import json
import re
import html
from typing import List, Dict, Optional, Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = 25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
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


def _product_from_shopify_object(p: Dict[str, Any], query: str) -> Optional[Dict[str, str]]:
    title = _clean(p.get("title"))
    vendor = _clean(p.get("vendor"))
    text = f"{title} {vendor}"

    if not title or not _matches(text, query):
        return None

    url = urljoin(BASE_URL, p.get("url") or "")
    if not url:
        return None

    price = _price(p.get("price")) or _price(p.get("price_min")) or _price(p.get("price_max"))
    if not price:
        return None

    return {
        "store": STORE,
        "name": title,
        "price": price,
        "url": url.split("?")[0],
    }


def _from_shopify_json(session: requests.Session, query: str) -> List[Dict[str, str]]:
    # Run BOTH predictive-search variants. The old code stopped after the
    # first endpoint returned any result, which could hide sold-out products.
    queries = [query]

    # Shopify predictive search can omit an exact product when the query is
    # too specific. For multi-word searches, add a broader pass using the
    # first two meaningful words, but keep the strict title filter below.
    toks = _tokens(query)
    if len(toks) >= 3:
        broad = " ".join(toks[:2])
        if broad and broad != _norm(query):
            queries.append(broad)

    endpoints = []
    for search_query in queries:
        endpoints.extend([
            BASE_URL + "/search/suggest.json?q={q}&resources[type]=product&resources[limit]=20",
            BASE_URL + "/search/suggest.json?q={q}&resources[type]=product&resources[options][unavailable_products]=show&resources[limit]=50",
        ])

    results = []
    seen = set()

    for template in endpoints:
        try:
            r = session.get(template.format(q=quote_plus(query)), headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            data = r.json()
        except (requests.RequestException, ValueError):
            continue

        products = data.get("resources", {}).get("results", {}).get("products", [])
        for p in products:
            # Always validate against the ORIGINAL user query, not the
            # broader fallback query.
            item = _product_from_shopify_object(p, query)
            if not item:
                continue
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            results.append(item)

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
        if not href or href in seen:
            continue

        card = a
        for _ in range(6):
            if not card.parent:
                break
            card = card.parent
            txt = _clean(card.get_text(" ", strip=True))
            if "€" in txt and len(txt) < 1600:
                break

        text = _clean(card.get_text(" ", strip=True))
        title = _clean(a.get("title") or a.get_text(" ", strip=True))
        if not title or not _matches(title + " " + text, query):
            continue

        price = None
        for raw in re.findall(r"\b\d{1,4}[.,]\d{2}\s*€", text):
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


def _availability_from_value(value) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value

    s = _clean(value).lower()

    if any(x in s for x in (
        "outofstock", "out of stock", "soldout", "sold out", "unavailable",
        "rupture de stock", "épuisé", "ausverkauft", "nicht auf lager",
    )):
        return False

    if any(x in s for x in (
        "instock", "in stock", "available", "disponible", "auf lager",
    )):
        return True

    return None


def _extract_variant_availability(data: Any) -> Optional[bool]:
    if not isinstance(data, dict):
        return None

    variants = data.get("variants")
    if isinstance(variants, list) and variants:
        values = [
            bool(v.get("available"))
            for v in variants
            if isinstance(v, dict) and "available" in v
        ]
        if values:
            return any(values)

    if "available" in data:
        return bool(data.get("available"))

    return None


def _read_shopify_product_json(session: requests.Session, url: str) -> Optional[bool]:
    js_url = url.rstrip("/") + ".js"
    try:
        r = session.get(js_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return None
        return _extract_variant_availability(r.json())
    except (requests.RequestException, ValueError):
        return None


def _read_product_page_signals(session: requests.Session, url: str) -> Dict[str, Optional[bool]]:
    signals = {"jsonld": None, "button": None, "html_data": None, "embedded_json": None}

    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return signals
    except requests.RequestException:
        return signals

    soup = BeautifulSoup(r.text, "html.parser")

    # JSON-LD availability.
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        for x in (obj if isinstance(obj, list) else [obj]):
            if not isinstance(x, dict) or x.get("@type") != "Product":
                continue
            offers = x.get("offers") or {}
            for offer in (offers if isinstance(offers, list) else [offers]):
                if isinstance(offer, dict):
                    av = _availability_from_value(offer.get("availability"))
                    if av is not None:
                        signals["jsonld"] = av
                        break
            if signals["jsonld"] is not None:
                break
        if signals["jsonld"] is not None:
            break

    # Actual purchase controls.
    selectors = (
        'button[name="add"]', '.product-form__submit', '[data-add-to-cart]',
        'button[type="submit"]', 'input[name="add"]',
    )
    controls = []
    for selector in selectors:
        controls.extend(soup.select(selector))

    unavailable_words = (
        "out of stock", "sold out", "unavailable", "ausverkauft",
        "nicht auf lager", "rupture de stock", "épuisé",
    )
    available_words = (
        "add to cart", "buy now", "add", "add to bag",
        "acheter", "in den warenkorb",
    )

    for control in controls:
        label = _clean(
            control.get_text(" ", strip=True)
            or control.get("value")
            or control.get("aria-label")
            or ""
        ).lower()
        disabled = (
            control.has_attr("disabled")
            or str(control.get("aria-disabled", "")).lower() == "true"
        )

        if any(word in label for word in unavailable_words) or disabled:
            signals["button"] = False
            break
        if any(word in label for word in available_words):
            signals["button"] = True

    # Explicit availability attributes.
    for node in soup.select("[data-available],[data-product-available],[data-availability],[data-stock]"):
        for attr in ("data-available", "data-product-available", "data-availability", "data-stock"):
            if node.has_attr(attr):
                av = _availability_from_value(node.get(attr))
                if av is not None:
                    signals["html_data"] = av
                    break
        if signals["html_data"] is not None:
            break

    # Embedded Shopify product JSON.
    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        if not raw or "variants" not in raw or "available" not in raw:
            continue
        try:
            obj = json.loads(raw)
            av = _extract_variant_availability(obj)
            if av is not None:
                signals["embedded_json"] = av
                break
        except Exception:
            pass

        matches = re.findall(r'"available"\s*:\s*(true|false)', raw, flags=re.IGNORECASE)
        if matches:
            signals["embedded_json"] = any(m.lower() == "true" for m in matches)
            break

    return signals


def _is_out_of_stock_page(session: requests.Session, url: str) -> bool:
    """
    Determine availability from the real storefront first.

    Why:
    Shopify's product .js can report a variant as available even when the
    storefront purchase control is currently sold out (theme/inventory
    configuration can make those signals disagree).

    Priority:
      1. Explicit product-page purchase control.
      2. Explicit structured/data availability on the product page.
      3. Shopify .js variant availability.
    """
    signals = _read_product_page_signals(session, url)

    # The actual purchase control is the most useful storefront signal.
    button = signals.get("button")
    if button is False:
        return True
    if button is True:
        return False

    # Structured storefront signals.
    for key in ("jsonld", "html_data", "embedded_json"):
        value = signals.get(key)
        if value is False:
            return True
        if value is True:
            return False

    # Last resort: Shopify product JSON.
    variant_availability = _read_shopify_product_json(session, url)
    if variant_availability is False:
        return True
    if variant_availability is True:
        return False

    return False


def search(query: str) -> List[Dict[str, str]]:
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()

    # Merge predictive-search and server-rendered search. Never stop merely
    # because the first source returned another member of the same family.
    sources = [
        _from_shopify_json(session, query),
        _from_search_html(session, query),
    ]

    results = []
    seen = set()
    for source in sources:
        for item in source:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            results.append(item)

    final = []
    for item in results:
        checked = dict(item)
        if _is_out_of_stock_page(session, item["url"]):
            checked["price"] = "Out of stock"
        final.append(checked)

    return final


if __name__ == "__main__":
    query = "9 PM Pour Femme"
    results = search(query)
    print(f"QUERY: {query}")
    print(f"RISULTATI: {len(results)}")
    for item in results:
        print(item)
