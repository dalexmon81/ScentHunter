import re
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _clean(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()


def _tokens(x):
    return re.findall(r"[a-z0-9]+", _clean(x).lower())


def _matches(name, query):
    n = _tokens(name)
    return all(x in n for x in _tokens(query))


def _price(text):
    text = _clean(text)

    patterns = [
        r"€\s*(\d{1,4})\s*,\s*(\d{2})",
        r"€\s*(\d{1,4})[.,](\d{2})",
        r"(\d{1,4})[.,](\d{2})\s*€",
    ]

    for p in patterns:
        m = re.search(p, text)
        if m:
            return f"{m.group(1)},{m.group(2)}€"

    return None


def search(query):
    query = _clean(query)
    if not query:
        return []

    s = requests.Session()
    s.headers.update(HEADERS)

    # Cerca la pagina Deloox indicizzata tramite Bing
    bing_url = (
        "https://www.google.com/search?q="
        + quote_plus(f'site:deloox.com/product/ "{query}"')
    )

    try:
        r = s.get(bing_url, timeout=8)
    except requests.RequestException:
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    product_urls = []

    for a in soup.find_all("a", href=True):
        href = a["href"]

        m = re.search(
            r"https?://(?:www\.)?deloox\.com/(?:en/)?product/[^&\" ]+",
            href,
            re.I,
        )

        if not m:
            continue

        url = m.group(0)
        url = url.split("&")[0]

        if url not in product_urls:
            product_urls.append(url)

    results = []
    seen = set()

    for product_url in product_urls[:8]:

        try:
            r = s.get(product_url, timeout=8)

            if r.status_code != 200:
                continue

            ps = BeautifulSoup(r.text, "html.parser")

            h1 = ps.find("h1")

            if not h1:
                continue

            name = _clean(h1.get_text(" ", strip=True))

            if not _matches(name, query):
                continue

            text = _clean(ps.get_text(" ", strip=True))

            # Deloox mostra chiaramente Sold out
            sold_out = bool(
                re.search(r"\bsold\s*out\b", text, re.I)
            )

            price = _price(text)

            # Se è esaurito ma non c'è prezzo, lo restituiamo comunque
            if sold_out and not price:
                price = None

            if not sold_out and not price:
                continue

            key = product_url.split("?")[0]

            if key in seen:
                continue

            seen.add(key)

            item = {
                "store": STORE,
                "name": name,
                "price": price,
                "url": key,
            }

            if sold_out:
                item["available"] = False
                item["availability"] = "out_of_stock"
            else:
                item["available"] = True
                item["availability"] = "in_stock"

            results.append(item)

        except requests.RequestException:
            continue

    return results


if __name__ == "__main__":
    print(search("Hawas Ice"))
