import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin

BASE_URL = "https://www.perfumemarket.nl"
PRICE_RE = re.compile(r"€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€")


def _extract_price(text):
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return value.replace(".", ",") + " €"


def search(query):
    url = BASE_URL + "/search?q=" + quote(query)

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()

    query_tokens = [t.lower() for t in query.split() if t.strip()]

    for link in soup.find_all("a", href=True):
        name = link.get_text(" ", strip=True)
        href = link.get("href", "")

        if not name or not href:
            continue

        name_lower = name.lower()
        if not all(token in name_lower for token in query_tokens):
            continue

        node = link
        price = None

        # Risale pochi livelli per trovare il prezzo della stessa card prodotto.
        for _ in range(5):
            if node is None:
                break

            text = node.get_text(" ", strip=True)
            price = _extract_price(text)

            if price:
                break

            node = node.parent

        if not price:
            continue

        product_url = urljoin(BASE_URL, href).split("?")[0]

        if product_url in seen:
            continue

        seen.add(product_url)

        results.append({
            "store": "PerfumeMarket",
            "name": name,
            "price": price,
            "url": product_url
        })

    return results


if __name__ == "__main__":
    results = search("Hawas Ice")

    print("RISULTATI:", len(results))

    for product in results[:10]:
        print(product)
