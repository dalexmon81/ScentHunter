import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

STORE = "Bplatz"
BASE = "https://en.bplatz.de"
TIMEOUT = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def _norm(value):
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def _matches(text, query):
    tokens = _norm(query).split()
    hay = _norm(text)
    return bool(tokens) and all(token in hay for token in tokens)

def _price_from_product_json(session, product_url):
    product_url = product_url.split("?")[0].split("#")[0].rstrip("/")
    try:
        r = session.get(product_url + ".js", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None, None
        data = r.json()
    except (requests.RequestException, ValueError):
        return None, None

    name = str(data.get("title") or "").strip()
    variants = data.get("variants") or []
    available = [v for v in variants if v.get("available")]
    variants = available or variants

    prices = []
    for variant in variants:
        try:
            prices.append(int(variant.get("price")))
        except (TypeError, ValueError):
            pass

    if not prices:
        return name, None

    price = f"{min(prices) / 100:.2f}".replace(".", ",") + " €"
    return name, price

def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    session = requests.Session()
    product_urls = []

    # Shopify search page used by Bplatz.
    try:
        r = session.get(
            BASE + "/search",
            params={"q": query, "type": "product"},
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                url = urljoin(BASE, a["href"]).split("#")[0]
                if "/products/" in url.lower() and url not in product_urls:
                    product_urls.append(url)
    except requests.RequestException:
        pass

    # Shopify predictive search fallback.
    if not product_urls:
        try:
            r = session.get(
                BASE + "/search/suggest.json",
                params={
                    "q": query,
                    "resources[type]": "product",
                    "resources[limit]": "20",
                },
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                products = data.get("resources", {}).get("results", {}).get("products", [])
                for product in products:
                    url = urljoin(BASE, product.get("url") or "")
                    if "/products/" in url.lower() and url not in product_urls:
                        product_urls.append(url)
        except (requests.RequestException, ValueError):
            pass

    results = []
    seen = set()

    for url in product_urls:
        name, price = _price_from_product_json(session, url)
        if not name or not price or not _matches(name, query):
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": url,
        })

    return results

if __name__ == "__main__":
    for query in ("Rasasi Hawas", "Armaf Club de Nuit", "Riiffs"):
        print("\\nQUERY:", query)
        results = search(query)
        print("RISULTATI:", len(results))
        for item in results:
            print(item)
