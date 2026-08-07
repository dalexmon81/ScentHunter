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


def _matches(text, query):
    text = (text or "").lower()
    tokens = [t.lower() for t in query.split() if t.strip()]
    return bool(tokens) and all(token in text for token in tokens)


def _catalog_results(query, headers):
    """
    Fallback Shopify: legge il catalogo prodotti in JSON in una sola richiesta.
    Serve per recuperare formati che la pagina /search non mostra,
    per esempio 30 ml e 50 ml dello stesso profumo.
    """
    url = BASE_URL + "/collections/all-perfumes/products.json?limit=250"

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return []

    results = []

    for product in data.get("products", []):
        title = str(product.get("title") or "").strip()

        if not title or not _matches(title, query):
            continue

        handle = str(product.get("handle") or "").strip()
        if not handle:
            continue

        product_url = BASE_URL + "/products/" + handle
        variants = product.get("variants") or []

        # Normalmente PerfumeMarket mette il formato già nel titolo prodotto.
        # Se ci sono più varianti con prezzi diversi, le manteniamo separate.
        for variant in variants:
            price_raw = str(variant.get("price") or "").strip()

            if not price_raw:
                continue

            try:
                price = f"{float(price_raw):.2f}".replace(".", ",") + " €"
            except ValueError:
                continue

            variant_title = str(variant.get("title") or "").strip()
            name = title

            if variant_title and variant_title.lower() != "default title":
                if variant_title.lower() not in title.lower():
                    name = f"{title} {variant_title}"

            results.append({
                "store": "PerfumeMarket",
                "name": name,
                "price": price,
                "url": product_url
            })

    return results


def search(query):
    url = BASE_URL + "/search?q=" + quote(query)

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"PERFUMEMARKET ERROR: {error}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()

    query_tokens = [t.lower() for t in query.split() if t.strip()]

    # LOGICA ORIGINALE: lasciata invariata.
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

    # PICCOLA AGGIUNTA:
    # completa i risultati con il catalogo JSON Shopify.
    for item in _catalog_results(query, headers):
        key = item["url"].split("?")[0]

        if key in seen:
            continue

        seen.add(key)
        results.append(item)

    return results


if __name__ == "__main__":
    results = search("Neroli Portofino Tom Ford")

    print("RISULTATI:", len(results))

    for product in results[:20]:
        print(product)
