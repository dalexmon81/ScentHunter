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
    """Scarta titoli che sembrano intestazioni/pagine di ricerca."""
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


def _find_local_price_anchor(node):
    """
    Cerca il prezzo in porzioni *vicine* al link:
    - prima nei fratelli (precedenti/successivi),
    - poi nel genitore diretto e al massimo nel genitore del genitore.
    Evita di salire troppo, per non prendere prezzi di altre card.
    """
    # 1) Fratelli del link
    for sib in list(node.previous_siblings) + list(node.next_siblings):
        if not hasattr(sib, "get_text"):
            continue
        text = _clean(sib.get_text(" ", strip=True))
        price = _price(text)
        if price:
            return sib, price

    # 2) Genitore diretto
    parent = node.parent
    if parent and hasattr(parent, "get_text"):
        text = _clean(parent.get_text(" ", strip=True))
        price = _price(text)
        if price and len(text) <= 800:  # limite dimensione blocco
            return parent, price

    # 3) Genitore del genitore (un solo livello in più)
    if parent is not None:
        grand = parent.parent
    else:
        grand = None

    if grand and hasattr(grand, "get_text"):
        text = _clean(grand.get_text(" ", strip=True))
        price = _price(text)
        # qui siamo più sospettosi: se il blocco è enorme, evitiamo
        if price and len(text) <= 600:
            return grand, price

    return None, ""


def _extract_name_from_card(card, link, query):
    """
    Estrae il nome prodotto da una 'card' coerente, con vari fallback.
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

            # Partiamo sempre dal link come "core" della card.
            # Trova porzioni di DOM vicine che contengono un prezzo.
            price_node, price = _find_local_price_anchor(link)
            if not price:
                # Nessun prezzo vicino in modo credibile → scarta
                continue

            # Usa il nodo che contiene il prezzo come 'card' di riferimento:
            # è abbastanza locale da evitare contaminazioni,
            # ma non troppo stretto da perdere il contenuto della card.
            card = price_node

            # Estrai il nome prodotto dal blocco card
            name = _extract_name_from_card(card, link, query)
            if not name:
                continue

            if _is_generic_title(name):
