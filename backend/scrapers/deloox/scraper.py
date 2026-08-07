import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
HOME_URL = BASE_URL + "/en"
TIMEOUT = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-GB,en;q=0.9",
}

PRICE_RE = re.compile(
    r"(?:our\s+price|from)?\s*€\s*(\d{1,4})\s*[,.\^]?\s*(\d{2})",
    re.I,
)

SOLD_OUT = (
    "sold out",
    "out of stock",
    "not available",
)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _tokens(value):
    return [x for x in _norm(value).split() if len(x) > 1]


def _matches(text, query):
    hay = _norm(text)
    words = _tokens(query)
    return bool(words) and all(word in hay for word in words)


def _extract_price(text):
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    return f"{match.group(1)},{match.group(2)} €"


def _get(session, url):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response
    except requests.RequestException as error:
        print(f"DELOOX ERROR: {error}")
        return None


def _find_brand_category(session, query):
    """
    Deloox non usa un normale /search?q=...
    La home espone invece l'indice dei brand.
    Cerchiamo il brand direttamente lì e apriamo la sua categoria.
    """
    response = _get(session, HOME_URL)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    query_words = _tokens(query)

    candidates = []

    for link in soup.find_all("a", href=True):
        name = _clean(link.get_text(" ", strip=True))
        href = _clean(link.get("href"))

        if not name or not href:
            continue

        url = urljoin(BASE_URL, href)

        if "/category/" not in url.lower():
            continue

        brand_words = _tokens(name)
        if not brand_words:
            continue

        # Il nome brand deve comparire nella query.
        if all(word in query_words for word in brand_words):
            candidates.append((len(brand_words), len(name), url))

    if not candidates:
        return None

    # Preferisci il brand più specifico.
    candidates.sort(key=lambda x: (-x[0], -x[1]))
    return candidates[0][2]


def _extract_category(html, query):
    """
    La pagina categoria Deloox contiene direttamente:
    nome prodotto, formato, disponibilità e prezzo.
    Usiamo la stessa filosofia semplice di PerfumeMarket:
    link -> pochi parent -> prezzo della stessa card.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    query_tokens = _tokens(query)

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        name = _clean(link.get_text(" ", strip=True))

        if not href:
            continue

        product_url = urljoin(BASE_URL, href).split("?")[0]

        if "/product/" not in product_url.lower():
            continue

        if not name:
            continue

        name_norm = _norm(name)

        if not all(token in name_norm for token in query_tokens):
            continue

        node = link
        price = None
        card_text = ""

        for _ in range(6):
            if node is None:
                break

            card_text = _clean(node.get_text(" ", strip=True))
            price = _extract_price(card_text)

            if price:
                break

            node = node.parent

        if any(word in card_text.lower() for word in SOLD_OUT):
            continue

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
            "available": True,
            "availability": "in_stock",
        })

    return results


def _extract_brand_page(html, query):
    """
    Alcune pagine brand mostrano i prodotti senza link /product/
    immediatamente leggibile. In quel caso prendiamo i blocchi testuali
    che contengono query + prezzo e recuperiamo il link prodotto vicino.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        if not href:
            continue

        node = link

        for _ in range(6):
            if node is None:
                break

            text = _clean(node.get_text(" ", strip=True))

            if _matches(text, query):
                price = _extract_price(text)

                if price and not any(x in text.lower() for x in SOLD_OUT):
                    product_link = None
                    product_name = ""

                    for a in node.find_all("a", href=True):
                        candidate_url = urljoin(BASE_URL, a.get("href", "")).split("?")[0]
                        candidate_name = _clean(a.get_text(" ", strip=True))

                        if "/product/" in candidate_url.lower():
                            product_link = candidate_url

                            if candidate_name and _matches(candidate_name, query):
                                product_name = candidate_name
                                break

                    if product_link:
                        if not product_name:
                            product_name = query

                        if product_link not in seen:
                            seen.add(product_link)
                            results.append({
                                "store": STORE,
                                "name": product_name,
                                "price": price,
                                "url": product_link,
                                "available": True,
                                "availability": "in_stock",
                            })

                break

            node = node.parent

    return results


def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()

    # 1) Trova il brand dall'indice Deloox.
    brand_url = _find_brand_category(session, query)

    if not brand_url:
        return []

    # 2) La categoria brand è il vero punto di ingresso utile.
    response = _get(session, brand_url)

    if response is None:
        return []

    results = _extract_category(response.text, query)

    if not results:
        results = _extract_brand_page(response.text, query)

    return results[:20]


if __name__ == "__main__":
    for q in (
        "French Avenue Liquid Brun",
        "Miu Miu Miutine",
        "Rasasi Hawas Ice",
    ):
        print(q, search(q))
