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

# Titoli generici di pagina/ricerca da scartare come nome prodotto
GENERIC_TITLES = [
    "résultat de la recherche",
    "nombre de produits",
    "recherche",
    "produits",
    "résultats",
    "page",
    "chargement",
    "loading",
]

# Testi che indicano chiaramente indisponibilità / niente vendita attuale
UNAVAILABLE_PATTERNS = [
    "rupture de stock",   # actuellement en rupture de stock
    "épuisé",             # produit épuisé
    "non disponible",     # non disponible
    "pas disponible",     # pas disponible
]

def _clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def _words(s):
    return [
        x
        for x in re.findall(r"[a-z0-9]+", _clean(s).lower())
        if len(x) > 1
    ]

def _matches(text, query):
    text = _clean(text).lower()
    return all(word in text for word in _words(query))

def _is_generic_title(title):
    t = _clean(title).lower()
    return any(g in t for g in GENERIC_TITLES)

def _is_unavailable_block(text: str) -> bool:
    """
    True se il blocco di testo contiene segnali chiari
    che il prodotto/variante è non disponibile.
    Questo evita di usare prezzi da blocchi tipo
    'Actuellement en rupture de stock / Prix minimal 25,50 €'.
    """
    t = _clean(text).lower()
    return any(pattern in t for pattern in UNAVAILABLE_PATTERNS)

def _price(text):
    matches = list(PRICE_RE.finditer(text or ""))

    if not matches:
        return ""

    match = matches[-1]
    value = match.group(1) or match.group(2)

    return value.replace(".", ",") + "€"

def _search_page(query):
    url = BASE_URL + "/search.asp?exps=" + quote_plus(query)

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        response = session.get(
            url,
            timeout=8,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        print("NOTINO ERROR:", error)
        return

    if response.text:
        yield response.text


def search(query):
    query = _clean(query)

    if not query:
        return []

    results = []
    seen = set()

    for html in _search_page(query):
        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a", href=True):
            href = _clean(link.get("href", ""))

            if not href:
                continue

            product_url = urljoin(BASE_URL, href).split("?")[0]

            if "notino.fr" not in product_url.lower():
                continue

            path = product_url.replace(BASE_URL, "").strip("/").lower()

            if not path:
                continue

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
                continue

            if product_url in seen:
                continue

            node = link
            card = None

            # Stessa logica di ParfumCity/PerfumeMarket:
            # risale dalla voce prodotto fino alla card che contiene
            # query + prezzo.
            for _ in range(8):
                if node is None:
                    break

                text = _clean(node.get_text(" ", strip=True))

                if _matches(text, query) and _price(text):
                    card = node
                    break

                node = node.parent

            if card is None:
                continue

            text = _clean(card.get_text(" ", strip=True))

            # NOVITÀ: se il blocco/card indica chiaramente
            # che il prodotto/variante è in rottura di stock / non disponibile,
            # NON usiamo i prezzi presenti in questo blocco.
            if _is_unavailable_block(text):
                continue

            name = ""

            # 1) Heading nella card
            for tag in card.find_all(["h1", "h2", "h3", "h4"]):
                candidate = _clean(tag.get_text(" ", strip=True))

                if candidate and _matches(candidate, query):
                    if not _is_generic_title(candidate):
                        name = candidate
                        break

            # 2) Titolo/aria-label/testo del link
            if not name:
                candidate = _clean(
                    link.get("title")
                    or link.get("aria-label")
                    or link.get_text(" ", strip=True)
                )

                if candidate and _matches(candidate, query):
                    if not _is_generic_title(candidate):
                        name = candidate

            # 3) Altri elementi testuali nella card
            if not name:
                # Alcune card Notino hanno il nome separato dal link:
                # usiamo il testo della card soltanto se contiene la query.
                for element in card.find_all(["span", "div", "p"]):
                    candidate = _clean(
                        element.get_text(" ", strip=True)
                    )

                    if (
                        candidate
                        and len(candidate) <= 250
                        and _matches(candidate, query)
                        and not _is_generic_title(candidate)
                    ):
                        name = candidate
                        break

            if not name:
                continue

            price = _price(text)

            if not price:
                continue

            seen.add(product_url)

            results.append(
                {
                    "store": STORE,
                    "name": name,
                    "price": price,
                    "url": product_url,
                }
            )

            if len(results) >= 10:
                return results

        if results:
            return results

    return results

if __name__ == "__main__":
    print(search("Hawas Ice"))
