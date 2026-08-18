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

    amount = None
    product_data = {}
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
                offers = item.get("offers")
                offers = offers if isinstance(offers, list) else [offers]
                for offer in offers:
                    if isinstance(offer, dict):
                        try:
                            amount = float(str(offer.get("price")).replace(",", "."))
                        except (TypeError, ValueError):
                            pass
                        if amount:
                            product_data = item
                            break
                if amount:
                    break

    if amount is None:
        text = soup.get_text(" ", strip=True)
        amount = price(text)

    if amount is None:
        return None

    if not isinstance(product_data, dict):
        product_data = {}
    brand = product_data.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    brand = clean(brand) if brand else None

    image = product_data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if image:
        image = urljoin(url, str(image))
    else:
        meta = soup.select_one('meta[property="og:image"]')
        image = urljoin(url, meta["content"]) if meta and meta.get("content") else None

    gtin = product_data.get("gtin13") or product_data.get("gtin") or product_data.get("gtin8")
    mpn = product_data.get("mpn")
    sku = product_data.get("sku")
    product_id = product_data.get("productID") or product_data.get("productId")

    offers_data = product_data.get("offers")
    offers_data = offers_data if isinstance(offers_data, list) else [offers_data]
    availability = "unknown"
    for offer in offers_data:
        if isinstance(offer, dict):
            av = str(offer.get("availability") or "").lower()
            if "outofstock" in av or "soldout" in av:
                availability = "out_of_stock"
                break
            if "instock" in av or "preorder" in av:
                availability = "in_stock"

    def ident(value, source="jsonld"):
        return {"value": str(value).strip(), "source": source} if value is not None and str(value).strip() else None

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand,
            "url": url,
            "image": image,
        },
        "identity": {
            "gtin": ident(gtin),
            "mpn": ident(mpn),
            "sku": ident(sku),
            "store_product_id": ident(product_id),
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {"value": size_ml(name), "source": "product_title"} if size_ml(name) else None,
            "concentration": {"value": concentration(name), "source": "product_title"} if concentration(name) else None,
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
        },
        "offer": {
            "price": round(amount, 2),
            "currency": "EUR",
            "availability": availability,
        },
        "provenance": {"source_page": url, "product_source": "jsonld_or_page"},
        "raw_data": {"jsonld": product_data},
        "name": name,
        "price": f"{amount:.2f}".replace(".", ",") + "€",
        "url": url,
        "available": True,
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
