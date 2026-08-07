import re import requests from bs4 import BeautifulSoup from
urllib.parse import quote, urljoin

BASE_URL = “https://www.perfumemarket.nl” PRICE_RE =
re.compile(r”€([.,])|([.,])€“)

COLLECTION_URL = BASE_URL + “/collections/all-perfumes”

def _extract_price(text): match = PRICE_RE.search(text or ““) if not
match: return None value = match.group(1) or match.group(2) return
value.replace(”.”, “,”) + ” €”

def _tokens(query): return [t.lower() for t in str(query or ““).split()
if t.strip()]

def _extract_results(html, query): soup = BeautifulSoup(html,
“html.parser”) results = [] seen = set()

    query_tokens = _tokens(query)

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

        # Stessa logica dello scraper originale funzionante.
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

def search(query): query = str(query or ““).strip()

    if not query:
        return []

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    results = []
    seen = set()

    # 1) Ricerca originale: resta identica alla versione che funziona.
    search_url = BASE_URL + "/search?q=" + quote(query)

    try:
        response = requests.get(
            search_url,
            headers=headers,
            timeout=15
        )
        response.raise_for_status()

        for item in _extract_results(response.text, query):
            if item["url"] not in seen:
                seen.add(item["url"])
                results.append(item)

    except requests.RequestException as error:
        print(f"PERFUMEMARKET SEARCH ERROR: {error}")

    # 2) Piccolo fallback: controlla le pagine REALI della collezione.
    # Non apre ogni prodotto e non usa products.json.
    # Si ferma quando trova una pagina senza prodotti.
    for page in range(1, 13):
        try:
            response = requests.get(
                COLLECTION_URL,
                params={"page": page},
                headers=headers,
                timeout=15
            )
            response.raise_for_status()
        except requests.RequestException as error:
            print(f"PERFUMEMARKET COLLECTION ERROR: {error}")
            break

        soup = BeautifulSoup(response.text, "html.parser")

        product_links = [
            a for a in soup.find_all("a", href=True)
            if "/products/" in a.get("href", "").lower()
        ]

        if not product_links:
            break

        for item in _extract_results(response.text, query):
            if item["url"] in seen:
                continue

            seen.add(item["url"])
            results.append(item)

    return results

if name == “main”: results = search(“Neroli Portofino Tom Ford”)

    print("RISULTATI:", len(results))

    for product in results[:20]:
        print(product)
