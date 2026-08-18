import json
import re
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup

STORE = "ParfumCity"
BASE_URL = "https://www.parfumcity.nl"
TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def norm(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(value).lower())).strip()

def tokens(value):
    return [x for x in norm(value).split() if len(x) > 1]

def matches(text, query):
    q = set(tokens(query))
    return bool(q) and q.issubset(set(tokens(text)))

def price(value):
    match = re.search(r"(?<![\d.,])(\d{1,4}(?:[.,]\d{2}))\s*€|€\s*(\d{1,4}(?:[.,]\d{2}))", clean(value))
    if not match:
        return None
    raw = next(x for x in match.groups() if x)
    return float(raw.replace(".", "").replace(",", ".")) if "," in raw and "." in raw else float(raw.replace(",", "."))

def size_ml(*values):
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", " ".join(clean(x) for x in values), re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10
    return int(value) if value.is_integer() else value

def concentration(*values):
    text = norm(" ".join(clean(x) for x in values))
    if re.search(r"\beau de toilette\b|\bedt\b", text): return "Eau de Toilette"
    if re.search(r"\beau de parfum\b|\bedp\b", text): return "Eau de Parfum"
    if re.search(r"\bextrait(?: de parfum)?\b", text): return "Extrait de Parfum"
    return None

def _walk_jsonld(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                yield item
                for value in item.values():
                    if isinstance(value, (dict, list)):
                        stack.append(value)


def _first_product_jsonld(soup):
    for item in _walk_jsonld(soup):
        types = item.get("@type")
        types = types if isinstance(types, list) else [types]
        if "Product" in types or item.get("sku") or item.get("gtin") or "offers" in item:
            return item
    return {}


def _value_from(item, *keys):
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("value") or value.get("name") or value.get("@id")
        if value not in (None, ""):
            return clean(value)
    return None


def _availability(value):
    text = clean(value).lower()
    if "outofstock" in text or "out of stock" in text:
        return "out_of_stock"
    if "instock" in text or "in stock" in text:
        return "in_stock"
    if "preorder" in text:
        return "preorder"
    return "unknown"


def _gender(name):
    text = norm(name)
    if re.search(r"\b(women|woman|dames|dame|femme|female)\b", text):
        return "women"
    if re.search(r"\b(men|man|heren|homme|male)\b", text):
        return "men"
    if re.search(r"\bunisex\b", text):
        return "unisex"
    return "unknown"


def product_page(session, url, query):
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    name = clean(h1.get_text(" ", strip=True)) if h1 else ""
    if not name or not matches(name, query):
        return None

    product_data = _first_product_jsonld(soup)

    amount = None
    offers = product_data.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        try:
            candidate = float(str(offer.get("price")).replace(",", "."))
        except (TypeError, ValueError):
            candidate = None
        if candidate is not None and candidate > 0:
            amount = candidate
            break

    if amount is None:
        amount = price(soup.get_text(" ", strip=True))

    if amount is None:
        return None

    brand = product_data.get("brand")
    brand = brand.get("name") if isinstance(brand, dict) else brand
    brand = clean(brand) or None

    image = product_data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    if not image:
        meta = soup.select_one('meta[property="og:image"]')
        if meta and meta.get("content"):
            image = urljoin(url, meta["content"])
    else:
        image = urljoin(url, str(image))

    offer0 = next((x for x in offers if isinstance(x, dict)), {})
    availability = _availability(offer0.get("availability"))

    sku = _value_from(product_data, "sku")
    gtin = _value_from(product_data, "gtin", "gtin13", "gtin12", "gtin14")
    mpn = _value_from(product_data, "mpn")
    product_id = _value_from(product_data, "productID", "productId", "product_id")

    size = size_ml(name)
    conc = concentration(name)
    gender = _gender(name)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand,
            "url": url,
            "image": image,
        },
        "identity": {
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
            "mpn": {"value": mpn, "source": "jsonld"} if mpn else None,
            "sku": {"value": sku, "source": "jsonld"} if sku else None,
            "store_product_id": {"value": product_id, "source": "jsonld"} if product_id else None,
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {"value": size, "source": "product_title"} if size is not None else None,
            "concentration": {"value": conc, "source": "product_title"} if conc else None,
            "gender": {"value": gender, "source": "product_title"},
            "packaging_type": {"value": "product", "source": "default"},
        },
        "offer": {
            "price": round(amount, 2),
            "currency": "EUR",
            "availability": availability,
        },
        "provenance": {
            "source_page": url,
            "name_source": "h1",
            "brand_source": "jsonld" if brand else None,
            "price_source": "jsonld_or_page",
            "product_source": "jsonld",
            "availability_source": "jsonld" if offer0.get("availability") else "default",
        },
        "raw_data": {
            "jsonld": product_data,
        },
        "name": name,
        "price": f"{amount:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": availability == "in_stock",
    }

def search(query):
    query = clean(query)
    if not query:
        return []
    session = requests.Session()
    try:
        r = session.get(BASE_URL + "/search?q=" + quote_plus(query), headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        urls, seen = [], set()
        for a in soup.select('a[href*="/products/"]'):
            url = urljoin(BASE_URL, a.get("href") or "").split("?")[0]
            if url in seen:
                continue
            card = a
            for _ in range(7):
                if card is None:
                    break
                text = clean(card.get_text(" ", strip=True))
                if matches(text, query) and "€" in text:
                    break
                card = card.parent
            if card is None:
                continue
            if matches(clean(card.get_text(" ", strip=True)), query):
                seen.add(url)
                urls.append(url)
        results = []
        for url in urls[:15]:
            item = product_page(session, url, query)
            if item:
                results.append(item)
        return results
    except requests.RequestException:
        return []
    finally:
        session.close()

def scrape(query):
    return search(query)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generic ParfumCity store adapter")
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
