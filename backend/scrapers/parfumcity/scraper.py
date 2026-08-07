import re
import requests

STORE = "ParfumCity"
BASE_URL = "https://www.parfumcity.nl"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

def _clean(value):
    return re.sub(r"\\s+", " ", str(value or "")).strip()

def _norm(value):
    return _clean(value).lower()

def _matches(name, query):
    words = [w for w in _norm(query).split() if len(w) > 1]
    text = _norm(name)
    return bool(words) and all(w in text for w in words)

def _blocked(name):
    text = _norm(name)
    return any(x in text for x in ("sample", "tester", "decant", "sample service"))

def _format_price(value):
    try:
        return f"{float(value):.2f}".replace(".", ",") + "€"
    except (TypeError, ValueError):
        return ""

def search(query):
    query = _clean(query)
    if not query:
        return []

    url = BASE_URL + "/search/suggest.json"
    params = {
        "q": query,
        "resources[type]": "product",
        "resources[limit]": "10",
        "resources[options][unavailable_products]": "last",
    }

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as e:
        print("PARFUMCITY ERROR:", e)
        return []

    products = data.get("resources", {}).get("results", {}).get("products", [])
    results = []
    seen = set()

    for product in products:
        title = _clean(product.get("title") or product.get("product_title") or "")
        if not title or not _matches(title, query) or _blocked(title):
            continue

        product_url = _clean(product.get("url") or "")
        if not product_url:
            handle = _clean(product.get("handle") or "")
            if handle:
                product_url = "/products/" + handle

        if product_url.startswith("/"):
            product_url = BASE_URL + product_url
        elif product_url and not product_url.startswith("http"):
            product_url = BASE_URL + "/" + product_url.lstrip("/")

        if not product_url:
            continue

        product_url = product_url.split("?")[0]
        if product_url in seen:
            continue

        price = product.get("price")
        if isinstance(price, dict):
            price = price.get("amount") or price.get("min") or price.get("value")

        price_text = _format_price(price)
        if not price_text:
            raw = _clean(product.get("price") or "")
            m = re.search(r"(\\d{1,4}(?:[.,]\\d{2})?)", raw)
            if m:
                price_text = m.group(1).replace(".", ",") + "€"

        if not price_text:
            continue

        seen.add(product_url)
        results.append({
            "store": STORE,
            "name": title,
            "price": price_text,
            "url": product_url,
        })

    return results

if __name__ == "__main__":
    for q in ("Hawas Ice", "Hawas for Him", "Afnan 9PM"):
        items = search(q)
        print(q, "=>", len(items))
        for item in items:
            print(item)
