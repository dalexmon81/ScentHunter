import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_PROXY = "https://www.google.com/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}

def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()

def search(query):
    query = _clean(query)
    if not query:
        return []

    # Notino blocca le richieste dirette da alcuni datacenter (403).
    # Cerchiamo quindi le pagine Notino indicizzate dal motore di ricerca.
    params = {"q": f'site:notino.fr "{query}"'}
    try:
        r = requests.get(SEARCH_PROXY, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        print("NOTINO SEARCH ERROR:", e)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    seen = set()
    words = [w.lower() for w in query.split() if len(w) >= 2]

    for block in soup.select("div"):
        text = _clean(block.get_text(" ", strip=True))
        low = text.lower()

        if not text or not all(w in low for w in words):
            continue

        # Deve sembrare un risultato prodotto Notino.
        if "notino.fr" not in low and "rasasi" not in low:
            continue

        link_tag = block.find("a", href=True)
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        m = re.search(r"(https?://(?:www\.)?notino\.fr/[^\s&]+)", href)
        if not m:
            continue

        url = m.group(1)
        if url in seen:
            continue

        # Nome: preferiamo il titolo del risultato.
        title = block.find("h3")
        name = _clean(title.get_text(" ", strip=True)) if title else query

        # Prezzo oppure disponibilità.
        price_match = re.search(r"\b\d{1,4}[,.]\d{2}\s*€", text)
        if price_match:
            price = price_match.group(0).replace(".", ",")
        elif "rupture de stock" in low:
            price = "En rupture de stock"
        else:
            # Non mostriamo risultati senza prezzo/disponibilità.
            continue

        seen.add(url)
        results.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": url,
        })

        if len(results) >= 10:
            break

    return results

if __name__ == "__main__":
    items = search("Rasasi Hawas Ice")
    print("RISULTATI:", len(items))
    for item in items:
        print(item)
