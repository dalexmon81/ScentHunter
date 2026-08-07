import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

STORE = "Notino"
BASE_URL = "https://www.notino.fr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

PRICE_RE = re.compile(
    r"€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€",
    re.I,
)

OUT_OF_STOCK_TERMS = (
    "actuellement en rupture de stock",
    "rupture de stock",
    "en rupture",
    "indisponible",
    "épuisé",
    "epuise",
)


def _clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _words(s):
    return [
        x for x in re.findall(r"[a-z0-9]+", _clean(s).lower())
        if len(x) > 1
    ]


def _matches(text, query):
    text = _clean(text).lower()
    return all(word in text for word in _words(query))


def _price(text):
    matches = list(PRICE_RE.finditer(text or ""))

    if not matches:
        return ""

    match = matches[-1]
    value = match.group(1) or match.group(2)

    return value.replace(".", ",") + "€"


def _is_out_of_stock(text):
    low = _clean(text).lower()
    return any(term in low for term in OUT_OF_STOCK_TERMS)


def _get(session, url):
    try:
        response = session.get(url, timeout=15, allow_redirects=True)
        response.raise_for_status()
        return response
    except requests.RequestException as error:
        print("NOTINO ERROR:", error)
        return None


def _search_page(query, session):
    urls = [
        BASE_URL + "/search.asp?exps=" + quote_plus(query),
        BASE_URL + "/search?query=" + quote_plus(query),
    ]

    for url in urls:
        response = _get(session, url)

        if response is not None and response.text:
            yield response.text


def _valid_notino_url(url):
    if not url or "notino.fr" not in url.lower():
        return False

    path = url.replace(BASE_URL, "").strip("/").lower()

    if not path:
        return False

    if any(
        bad in path
        for bad in (
            "search.asp",
            "search/",
            "panier",
            "cart",
            "login",
            "account",
            "contact",
            "livraison",
            "conditions",
            "magazine",
        )
    ):
        return False

    return True


def _product_from_detail_page(session, url, query):
    """
    Verifica il candidato direttamente sulla sua pagina Notino.
    È questo il fix importante: il prezzo non viene più preso
    dal contenitore generale della pagina di ricerca.
    """
    response = _get(session, url)

    if response is None or not response.text:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = _clean(soup.get_text(" ", strip=True))

    if not _matches(page_text, query):
        return None

    if _is_out_of_stock(page_text):
        return None

    # Nome: preferiamo H1 della pagina reale.
    name = ""
    h1 = soup.find("h1")
    if h1:
        candidate = _clean(h1.get_text(" ", strip=True))
        if candidate and _matches(candidate, query):
            name = candidate

    if not name:
        title = soup.find("title")
        candidate = _clean(title.get_text(" ", strip=True)) if title else ""
        if candidate and _matches(candidate, query):
            name = candidate

    if not name:
        return None

    # Cerca prima prezzi in blocchi piccoli vicini al prodotto.
    price = ""

    for tag in soup.find_all(["span", "div", "p"]):
        text = _clean(tag.get_text(" ", strip=True))

        if not text or len(text) > 500:
            continue

        candidate_price = _price(text)
        if candidate_price:
            price = candidate_price
            break

    # Fallback al testo pagina, ma solo della PAGINA PRODOTTO verificata.
    if not price:
        price = _price(page_text)

    if not price:
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": response.url.split("?")[0],
    }


def search(query):
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    candidates = []
    candidate_seen = set()

    # Manteniamo la logica dello scraper che funzionava:
    # la ricerca serve solo a trovare URL candidati.
    for html in _search_page(query, session):
        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a", href=True):
            href = _clean(link.get("href", ""))

            if not href:
                continue

            product_url = urljoin(BASE_URL, href).split("?")[0]

            if not _valid_notino_url(product_url):
                continue

            if product_url in candidate_seen:
                continue

            node = link
            matched = False

            # Stessa logica permissiva della versione funzionante.
            # Qui NON salviamo più il prezzo: individuiamo solo il candidato.
            for _ in range(8):
                if node is None:
                    break

                text = _clean(node.get_text(" ", strip=True))

                if _matches(text, query):
                    matched = True
                    break

                node = node.parent

            if not matched:
                continue

            candidate_seen.add(product_url)
            candidates.append(product_url)

            if len(candidates) >= 20:
                break

        if candidates:
            break

    # Ora ogni candidato viene verificato sulla pagina reale.
    results = []
    final_seen = set()

    for product_url in candidates:
        item = _product_from_detail_page(session, product_url, query)

        if not item:
            continue

        final_url = item["url"]

        if final_url in final_seen:
            continue

        final_seen.add(final_url)
        results.append(item)

        if len(results) >= 10:
            break

    return results


if __name__ == "__main__":
    print(search("Hawas Ice"))
