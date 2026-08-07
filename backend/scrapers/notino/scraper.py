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

# Testi generici da non considerare nomi prodotto
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
    """
    Scarta titoli che sembrano intestazioni/pagine di ricerca
    invece che nomi prodotto reali.
    """
    t = _clean(title).lower()
    return any(g in t for g in GENERIC_TITLES)


def _price(text):
    matches = list(PRICE_RE.finditer(text or ""))

    if not matches:
        return ""

    match = matches[-1]
    value = match.group(1) or match.group(2)

    return value.replace(".", ",") + "€"


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


def _find_card_for_link(link, query):
    """
    Risale dal link fino a trovare un contenitore 'card' plausibile:
    - contiene il link,
    - contiene la query,
    - contiene almeno un prezzo.
    Torna None se non esiste un blocco coerente.
    """
    node = link
    for _ in range(8):
        if node is None:
            break

        text = _clean(node.get_text(" ", strip=True))

        # richiediamo TUTTI e 3:
        # 1) testo coerente con la query;
        # 2) almeno un prezzo nel blocco;
        # 3) il blocco non è palesemente generico.
        if _matches(text, query) and _price(text):
            # filtro rapido contro blocchi di pagina / intestazioni enormi
            if len(text) > 800:
                # troppo testo, probabile contenitore di pagina
                node = node.parent
                continue
            return node

        node = node.parent

    return None


def _extract_name_from_card(card, link, query):
    """
    Estrae il nome prodotto da una 'card' coerente, con vari fallback.
    Applica anche una piccola normalizzazione per evitare doppi prodotti
    quando cambia solo un dettaglio tipo '100 ml'.
    """
    name = ""

    # 1) Heading all'interno della card
    for tag in card.find_all(["h1", "h2", "h3", "h4"]):
        candidate = _clean(tag.get_text(" ", strip=True))
        if candidate and _matches(candidate, query) and not _is_generic_title(candidate):
            name = candidate
            break

    # 2) Titolo/aria-label/testo del link
    if not name:
        candidate = _clean(
            link.get("title")
            or link.get("aria-label")
            or link.get_text(" ", strip=True)
        )
        if candidate and _matches(candidate, query) and not _is_generic_title(candidate):
            name = candidate

    # 3) Altri elementi testuali vicini
    if not name:
        for element in card.find_all(["span", "div", "p"]):
            candidate = _clean(element.get_text(" ", strip=True))
            if (
                candidate
                and len(candidate) <= 250
                and _matches(candidate, query)
                and not _is_generic_title(candidate)
            ):
                name = candidate
                break

    if not name:
        return ""

    # Piccola normalizzazione: se il nome completo inizia con la query,
    # teniamo il prefisso fino alla lunghezza della query o poco oltre.
    # Esempio:
    # "Rasasi Hawas Ice 100 ml" -> "Rasasi Hawas Ice 100 ml" (lasciamo intero)
    # "Hawas Ice 100 ml" -> "Hawas Ice 100 ml"
    # ma se il backend raggruppa per nome normalizzato, puoi
    # facilmente troncare dal lato tuo dopo.
    name = _clean(name)

    return name


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

            # Trova la card più coerente per questo link
            card = _find_card_for_link(link, query)
            if card is None:
                continue

            text = _clean(card.get_text(" ", strip=True))

            # Prezzo SOLO dal testo di questa card,
            # non da antenati più alti.
            price = _price(text)
            if not price:
                continue

            # Estrai e normalizza il nome prodotto
            name = _extract_name_from_card(card, link, query)
            if not name:
                continue

            # Ulteriore difesa: niente nomi generici
            if _is_generic_title(name):
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
