import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

PRICE_RE = re.compile(
    r"(?<!\d)(\d{1,4}[.,]\d{2})\s*€",
    re.I,
)

OUT_OF_STOCK = (
    "en rupture de stock",
    "rupture de stock",
    "indisponible",
    "épuisé",
    "epuise",
)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    value = _clean(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value):
    return [x for x in _norm(value).split() if len(x) > 1]


def _matches(text, query):
    text_n = _norm(text)
    return all(token in text_n for token in _tokens(query))


def _price(text):
    matches = PRICE_RE.findall(_clean(text))
    if not matches:
        return ""
    return matches[-1].replace(".", ",") + "€"


def _is_out_of_stock(text):
    low = _clean(text).lower()
    return any(marker in low for marker in OUT_OF_STOCK)


def _is_product_url(url):
    if not url:
        return False

    low = url.lower()

    if "notino.fr" not in low:
        return False

    blocked = (
        "/search.asp",
        "/search/",
        "/panier",
        "/cart",
        "/login",
        "/account",
        "/contact",
        "/magazine",
        "/marques",
        "/promotions",
    )

    if any(part in low for part in blocked):
        return False

    # Esclude home/category/wrapper links: servono almeno due segmenti reali.
    path = product_url_path = url.split("notino.fr", 1)[-1].split("?", 1)[0].strip("/")
    return len([p for p in path.split("/") if p]) >= 2


def search(query):
    query = _clean(query)

    if not query:
        return []

    url = BASE_URL + "/search.asp?exps=" + quote_plus(query)

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        print("NOTINO ERROR:", error)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()

    # Notino restituisce già i prodotti nell'HTML della ricerca.
    # Ogni link prodotto contiene nome, formato e prezzo/stato disponibilità.
    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href", ""))

        if not href:
            continue

        product_url = urljoin(BASE_URL, href).split("?")[0]

        if not _is_product_url(product_url):
            continue

        if product_url in seen:
            continue

        # Il link deve rappresentare il prodotto stesso.
        # Non accettiamo wrapper della pagina di ricerca ("Résultat de la recherche...",
        # "Nombre de produits 50", filtri, categorie, ecc.).
        link_text = _clean(link.get_text(" ", strip=True))
        label = _clean(link.get("title") or link.get("aria-label") or "")

        candidate_name = label or link_text
        candidate_low = candidate_name.lower()

        if (
            not candidate_name
            or not _matches(candidate_name, query)
            or "résultat de la recherche" in candidate_low
            or "resultat de la recherche" in candidate_low
            or "nombre de produits" in candidate_low
        ):
            continue

        text = link_text
        card = link

        # Se il link non contiene prezzo/stato, risaliamo solo pochi livelli.
        if not _price(text) and not _is_out_of_stock(text):
            node = link.parent

            for _ in range(4):
                if node is None:
                    break

                candidate = _clean(node.get_text(" ", strip=True))

                # Evita il vecchio errore: non accettare contenitori enormi
                # che possono contenere il prezzo di un altro profumo.
                if (
                    len(candidate) <= 1200
                    and _matches(candidate, query)
                    and (_price(candidate) or _is_out_of_stock(candidate))
                ):
                    text = candidate
                    card = node
                    break

                node = node.parent

        # Un prodotto esaurito è un risultato reale di Notino,
        # ma non è un'offerta acquistabile e non deve ereditare
        # il prezzo della card vicina.
        if _is_out_of_stock(text):
            continue

        price = _price(text)

        if not price:
            continue

        name = ""

        # Il testo del link è la fonte più sicura perché appartiene
        # esattamente allo stesso URL prodotto.
        candidate = candidate_name

        if candidate and _matches(candidate, query):
            name = candidate

        if not name and card is not None:
            for tag in card.find_all(["h1", "h2", "h3", "h4"]):
                candidate = _clean(tag.get_text(" ", strip=True))

                if candidate and _matches(candidate, query):
                    name = candidate
                    break

        if not name:
            continue

        seen.add(product_url)

        results.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": product_url,
        })

        if len(results) >= 10:
            break

    return results
