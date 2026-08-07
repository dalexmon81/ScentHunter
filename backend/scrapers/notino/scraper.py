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
ML_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*ml\b", re.I)

OUT_OF_STOCK = (
    "en rupture de stock",
    "rupture de stock",
    "indisponible",
    "épuisé",
    "epuise",
)

BAD_TEXT = (
    "résultat de la recherche",
    "resultat de la recherche",
    "nombre de produits",
    "produits :",
    "le plus pertinent",
    "afficher plus",
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
    n = _norm(text)
    return all(token in n for token in _tokens(query))


def _prices(text):
    return [x.replace(".", ",") + "€" for x in PRICE_RE.findall(_clean(text))]


def _is_out_of_stock(text):
    low = _clean(text).lower()
    return any(marker in low for marker in OUT_OF_STOCK)


def _bad_text(text):
    low = _clean(text).lower()
    return any(x in low for x in BAD_TEXT)


def _product_url(href):
    if not href:
        return ""

    url = urljoin(BASE_URL, href).split("#")[0].split("?")[0]
    p = urlparse(url)

    if p.netloc.lower() not in {"notino.fr", "www.notino.fr"}:
        return ""

    parts = [x for x in p.path.strip("/").split("/") if x]
    if len(parts) < 2:
        return ""

    blocked = {
        "search.asp", "parfums", "parfums-homme", "parfums-femme",
        "cosmetiques", "maquillage", "cheveux", "visage", "corps",
        "marques", "promotions", "nouveautes", "panier", "cart",
        "login", "account", "contact", "magazine", "faqs",
    }

    if parts[0].lower() in blocked:
        return ""

    return url


def _smallest_product_card(link, query):
    """
    Trova il più piccolo antenato che:
    - contiene la query;
    - contiene un prezzo oppure lo stato out-of-stock;
    - non è il wrapper generale dei risultati;
    - contiene pochi link prodotto, così prezzo/nome restano della stessa card.
    """
    node = link

    for _ in range(8):
        if node is None:
            break

        text = _clean(node.get_text(" ", strip=True))

        if 10 <= len(text) <= 900 and _matches(text, query) and not _bad_text(text):
            product_links = set()

            for a in node.find_all("a", href=True):
                u = _product_url(a.get("href", ""))
                if u:
                    product_links.add(u)

            if len(product_links) <= 1 and (_prices(text) or _is_out_of_stock(text)):
                return node

        node = node.parent

    return None


def _name_from_card(card, link, query):
    candidates = []

    for attr in ("title", "aria-label"):
        v = _clean(link.get(attr, ""))
        if v:
            candidates.append(v)

    link_text = _clean(link.get_text(" ", strip=True))
    if link_text:
        candidates.append(link_text)

    for selector in ("h1", "h2", "h3", "h4", "[class*='name']", "[class*='title']"):
        try:
            for el in card.select(selector):
                v = _clean(el.get_text(" ", strip=True))
                if v:
                    candidates.append(v)
        except Exception:
            pass

    # Ultima possibilità: testo card senza prezzo/valutazione.
    card_text = _clean(card.get_text(" ", strip=True))
    candidates.append(card_text)

    for value in candidates:
        if (
            value
            and len(value) <= 260
            and _matches(value, query)
            and not _bad_text(value)
        ):
            return value

    return ""


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

    for link in soup.find_all("a", href=True):
        product_url = _product_url(link.get("href", ""))
        if not product_url or product_url in seen:
            continue

        # Il link o la sua card devono riferirsi davvero alla query.
        link_identity = _clean(
            (link.get("title") or "") + " " +
            (link.get("aria-label") or "") + " " +
            link.get_text(" ", strip=True)
        )

        card = _smallest_product_card(link, query)
        if card is None:
            continue

        text = _clean(card.get_text(" ", strip=True))

        if _bad_text(text) or _is_out_of_stock(text):
            continue

        # Sicurezza fondamentale: nella card deve esserci esattamente
        # questo URL prodotto, non un contenitore con più prodotti.
        urls_in_card = {
            _product_url(a.get("href", ""))
            for a in card.find_all("a", href=True)
        }
        urls_in_card.discard("")

        if urls_in_card and product_url not in urls_in_card:
            continue
        if len(urls_in_card) > 1:
            continue

        name = _name_from_card(card, link, query)
        if not name:
            continue

        # Evita che un link generico erediti una query dal wrapper.
        if link_identity and not _matches(link_identity, query):
            # Va bene solo se il nome estratto dalla stessa card è chiaramente valido
            # e la card contiene un unico URL prodotto.
            if not (_matches(name, query) and len(urls_in_card) == 1):
                continue

        prices = _prices(text)
        if not prices:
            continue

        # In una vera card Notino il prezzo prodotto è quello principale.
        # Se compaiono più importi (es. promo/codice), scegliamo il primo prezzo
        # associato alla card, NON l'ultimo importo della pagina.
        price = prices[0]

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
    print(search(q))
