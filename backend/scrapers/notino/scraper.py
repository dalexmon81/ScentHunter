import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin, urlparse

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

PRICE_RE = re.compile(r"(?<!\d)(\d{1,4}[.,]\d{2})\s*€", re.I)

OUT_OF_STOCK = (
    "en rupture de stock",
    "rupture de stock",
    "indisponible",
    "épuisé",
    "epuise",
)

BAD_RESULT_TEXT = (
    "résultat de la recherche",
    "resultat de la recherche",
    "nombre de produits",
    "produits :",
    "afficher plus",
    "le plus pertinent",
)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    value = _clean(value).lower()
    value = (
        value.replace("é", "e").replace("è", "e").replace("ê", "e")
        .replace("ë", "e").replace("à", "a").replace("â", "a")
        .replace("î", "i").replace("ï", "i").replace("ô", "o")
        .replace("ù", "u").replace("û", "u").replace("ü", "u")
        .replace("ç", "c")
    )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value):
    return [x for x in _norm(value).split() if len(x) > 1]


def _matches(text, query):
    text = _norm(text)
    tokens = _tokens(query)
    return bool(tokens) and all(token in text for token in tokens)


def _prices(text):
    return [p.replace(".", ",") + " €" for p in PRICE_RE.findall(_clean(text))]


def _out_of_stock(text):
    low = _clean(text).lower()
    return any(x in low for x in OUT_OF_STOCK)


def _bad_result(text):
    low = _clean(text).lower()
    return any(x in low for x in BAD_RESULT_TEXT)


def _product_url(href):
    if not href:
        return ""

    url = urljoin(BASE_URL, href).split("#")[0].split("?")[0]
    parsed = urlparse(url)

    if parsed.netloc.lower() not in {"notino.fr", "www.notino.fr"}:
        return ""

    path = parsed.path.strip("/")
    if not path:
        return ""

    first = path.split("/", 1)[0].lower()

    blocked = {
        "search.asp", "parfums", "parfums-homme", "parfums-femme",
        "cosmetiques", "maquillage", "cheveux", "visage", "corps",
        "marques", "promotions", "nouveautes", "panier", "cart",
        "login", "account", "contact", "magazine", "faqs",
        "livraison-offerte", "premium", "cadeau-luxe",
    }

    if first in blocked:
        return ""

    # Le vere pagine prodotto Notino normalmente hanno brand + prodotto.
    if len([x for x in path.split("/") if x]) < 2:
        return ""

    return url


def _link_identity(link):
    return _clean(
        " ".join([
            link.get("title") or "",
            link.get("aria-label") or "",
            link.get_text(" ", strip=True),
        ])
    )


def _nearest_price_block(link, query):
    """
    Parte DAL link prodotto corretto e risale solo finché trova il suo prezzo.
    Non cerca link a caso nella pagina e non usa il wrapper generale dei risultati.
    """
    node = link

    for _ in range(7):
        if node is None:
            break

        text = _clean(node.get_text(" ", strip=True))

        if len(text) > 1600:
            break

        if _bad_result(text):
            node = node.parent
            continue

        if _matches(text, query):
            if _out_of_stock(text):
                return node, text, None

            prices = _prices(text)
            if prices:
                return node, text, prices[0]

        node = node.parent

    return None, "", None


def _name(link, block, query):
    # Prima scelta: il testo/label DEL link prodotto.
    identity = _link_identity(link)
    if identity and _matches(identity, query) and not _bad_result(identity):
        # Togli solo rumore commerciale in coda, senza inventare il nome.
        identity = re.split(
            r"\b(?:\d{1,4}[.,]\d{2}\s*€|en rupture de stock|livraison offerte)\b",
            identity,
            maxsplit=1,
            flags=re.I,
        )[0]
        identity = _clean(identity)
        if 2 <= len(identity) <= 300:
            return identity

    # Fallback: heading dentro la stessa card.
    if block is not None:
        for selector in ("h1", "h2", "h3", "h4"):
            for el in block.select(selector):
                candidate = _clean(el.get_text(" ", strip=True))
                if (
                    2 <= len(candidate) <= 300
                    and _matches(candidate, query)
                    and not _bad_result(candidate)
                ):
                    return candidate

    return ""


def search(query):
    query = _clean(query)
    if not query:
        return []

    search_url = BASE_URL + "/search.asp?exps=" + quote_plus(query)

    try:
        response = requests.get(
            search_url,
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

    for link in soup.find_all("a", href=True):
        product_url = _product_url(link.get("href", ""))
        if not product_url or product_url in seen:
            continue

        # Punto chiave:
        # il LINK prodotto deve già riferirsi alla query.
        # Così "Résultat de la recherche..." non può diventare un prodotto.
        identity = _link_identity(link)
        if not identity or not _matches(identity, query) or _bad_result(identity):
            continue

        block, text, price = _nearest_price_block(link, query)
        if block is None:
            continue

        # Un prodotto non disponibile non deve entrare nel comparatore.
        if _out_of_stock(text):
            continue

        if not price:
            continue

        name = _name(link, block, query)
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


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]).strip() or "Majesty"
    for item in search(q):
        print(item)
