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


def _price_raw_matches(text):
    """Ritorna tutte le stringhe prezzo trovate nel testo (lista)."""
    matches = list(PRICE_RE.finditer(text or ""))
    values = []
    for m in matches:
        value = m.group(1) or m.group(2)
        if value:
            values.append(value.replace(".", ",") + "€")
    return values


def _price(text):
    """Versione originale: prende l'ultimo prezzo trovato."""
    matches = list(PRICE_RE.finditer(text or ""))

    if not matches:
        return ""

    match = matches[-1]
    value = match.group(1) or match.group(2)

    return value.replace(".", ",") + "€"


def _unique_price_or_empty(text):
    """
    Se nel blocco c'è UN SOLO prezzo coerente, restituiscilo.
    Se ce ne sono 0 o >1, torna stringa vuota (associazione non sicura).
    Questo blocca i casi tipo 'Résultat de la recherche' con più prezzi.
    """
    prices = _price_raw_matches(text)
    unique = sorted(set(prices))
    if len(unique) == 1:
        return unique[0]
    # 0 prezzi o più di uno => meglio nessun risultato Notino
    return ""


def _search_page(query):
    urls = [
        BASE_URL + "/search.asp?exps=" + quote_plus(query),
        BASE_URL + "/search?query=" + quote_plus(query),
    ]

    session = requests.Session()
    session.headers.update(HEADERS)

    for url in urls:
        try:
            response = session.get(
                url,
                timeout=15,
                allow_redirects=True,
            )

            response.raise_for_status()
        except requests.RequestException as error:
            print("NOTINO ERROR:", error)
            continue

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

                # qui usiamo ancora _price per trovare "qualche" prezzo
                # e capire se questo blocco è interessante.
                if _matches(text, query) and _price(text):
                    card = node
                    break

                node = node.parent

            if card is None:
                continue

            text = _clean(card.get_text(" ", strip=True))

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

            # Prezzo: deve esserci un SOLO prezzo nel blocco card.
            price = _unique_price_or_empty(text)

            if not price:
                # 0 o più di un prezzo => associazione non sicura, scartiamo
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
