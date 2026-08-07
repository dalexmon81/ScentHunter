import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

STORE = "ParfumCity"
BASE_URL = "https://www.parfumcity.nl"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def _norm(value):
    return _clean(value).lower()

def _words(query):
    return [w for w in re.findall(r"[a-z0-9]+", _norm(query)) if len(w) > 1]

def _matches(text, query):
    t = _norm(text)
    words = _words(query)
    return bool(words) and all(w in t for w in words)

def _blocked(text):
    t = _norm(text)
    return any(x in t for x in (
        "sample", "tester", "decant", "sample service"
    ))

def _price(text):
    values = re.findall(r"€\s*(\d{1,4}(?:[.,]\d{2})?)", text or "")
    if not values:
        return ""
    # nelle card Shopify possono esserci prezzo vecchio + prezzo attuale:
    # prendiamo l'ultimo importo visualizzato nella card.
    return values[-1].replace(".", ",") + "€"

def search(query):
    query = _clean(query)
    if not query:
        return []

    results = []
    seen = set()

    # Il catalogo /collections/all è server-rendered.
    # Scorriamo le pagine finché troviamo corrispondenze.
    for page in range(1, 16):
        url = f"{BASE_URL}/collections/all?page={page}"

        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"PARFUMCITY ERROR page {page}:", e)
            break

        soup = BeautifulSoup(response.text, "html.parser")
        product_links = soup.select('a[href*="/products/"]')

        if not product_links:
            break

        page_seen = set()

        for link in product_links:
            href = link.get("href", "")
            if "/products/" not in href:
                continue

            product_url = urljoin(BASE_URL, href).split("?")[0]
            if product_url in page_seen:
                continue
            page_seen.add(product_url)

            # Risaliamo alla card più vicina che contiene nome e prezzo.
            node = link
            card = None
            for _ in range(8):
                if node is None:
                    break
                text = _clean(node.get_text(" ", strip=True))
                if "€" in text and "/products/" in str(node):
                    card = node
                    break
                node = node.parent

            if card is None:
                continue

            card_text = _clean(card.get_text(" ", strip=True))
            if not _matches(card_text, query):
                continue
            if _blocked(card_text) or _blocked(product_url):
                continue

            # Nome: preferisci il testo di un link prodotto che corrisponde alla query.
            name = ""
            for a in card.select('a[href*="/products/"]'):
                candidate = _clean(a.get_text(" ", strip=True))
                if candidate and _matches(candidate, query) and not _blocked(candidate):
                    name = candidate
                    break

            if not name:
                for heading in card.find_all(["h2", "h3", "h4"]):
                    candidate = _clean(heading.get_text(" ", strip=True))
                    if candidate and _matches(candidate, query) and not _blocked(candidate):
                        name = candidate
                        break

            if not name:
                continue

            price = _price(card_text)
            if not price:
                continue

            if product_url in seen:
                continue
            seen.add(product_url)

            results.append({
                "store": STORE,
                "name": name,
                "price": price,
                "url": product_url,
            })

            if len(results) >= 10:
                return results

    return results

if __name__ == "__main__":
    for q in ("Rasasi Hawas Ice", "Rasasi Hawas for Him", "Afnan 9PM"):
        items = search(q)
        print(q, "=>", len(items))
        for item in items:
            print(item)
