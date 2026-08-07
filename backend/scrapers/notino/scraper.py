import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin, urlparse

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


def _format_price(value):
    if value is None:
        return ""

    match = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)", _clean(value))
    if not match:
        return ""

    try:
        number = float(match.group(1).replace(",", "."))
    except ValueError:
        return ""

    if number <= 0:
        return ""

    return f"{number:.2f}".replace(".", ",") + "€"


def _price(text):
    matches = list(PRICE_RE.finditer(text or ""))

    if not matches:
        return ""

    match = matches[-1]
    value = match.group(1) or match.group(2)

    return value.replace(".", ",") + "€"


def _looks_like_product_url(url):
    parsed = urlparse(url)

    if parsed.netloc.lower() not in ("www.notino.fr", "notino.fr"):
        return False

    parts = [part for part in parsed.path.split("/") if part]

    # Le pagine prodotto Notino usate dallo scraper hanno normalmente:
    # /marca/prodotto/
    if len(parts) < 2:
        return False

    low = parsed.path.lower()

    if any(
        bad in low
        for bad in (
            "/search",
            "search.asp",
            "/panier",
            "/cart",
            "/login",
            "/account",
            "/contact",
            "/livraison",
            "/conditions",
            "/magazine",
            "/marques/",
            "/parfums/",
            "/cosmetiques/",
        )
    ):
        return False

    return True


def _search_page(session, query):
    urls = [
        BASE_URL + "/search.asp?exps=" + quote_plus(query),
        BASE_URL + "/search?query=" + quote_plus(query),
    ]

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


def _json_ld_products(soup):
    products = []

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop()

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)

            item_type = item.get("@type", "")
            types = item_type if isinstance(item_type, list) else [item_type]

            if "Product" in types:
                products.append(item)

    return products


def _offer_data(offers):
    if isinstance(offers, list):
        offer_list = offers
    elif isinstance(offers, dict):
        offer_list = [offers]
    else:
        return "", ""

    for offer in offer_list:
        if not isinstance(offer, dict):
            continue

        availability = _clean(offer.get("availability")).lower()

        # Non restituiamo prodotti dichiarati non disponibili.
        if any(
            term in availability
            for term in ("outofstock", "soldout", "discontinued")
        ):
            continue

        price = (
            _format_price(offer.get("price"))
            or _format_price(offer.get("lowPrice"))
        )

        if price:
            return price, availability

    return "", ""


def _product_details(session, product_url, query):
    try:
        response = session.get(
            product_url,
            timeout=15,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        print("NOTINO PRODUCT ERROR:", error)
        return None

    final_url = response.url.split("?")[0]

    if not _looks_like_product_url(final_url):
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = _clean(soup.get_text(" ", strip=True))
    low = page_text.lower()

    # Se la pagina dichiara chiaramente il prodotto non disponibile,
    # non lo inviamo a ScentHunter.
    if any(
        term in low
        for term in (
            "rupture de stock",
            "en rupture",
            "actuellement indisponible",
            "produit indisponible",
        )
    ):
        return None

    name = ""
    price = ""

    # 1) Fonte preferita: dati strutturati della PAGINA PRODOTTO.
    # Qui prezzo, nome e URL appartengono allo stesso prodotto.
    for product in _json_ld_products(soup):
        candidate_name = _clean(product.get("name"))

        brand = product.get("brand")
        if isinstance(brand, dict):
            brand = _clean(brand.get("name"))
        else:
            brand = _clean(brand)

        match_text = _clean(brand + " " + candidate_name)

        if not _matches(match_text, query):
            continue

        candidate_price, _ = _offer_data(product.get("offers"))

        if candidate_price:
            name = candidate_name
            price = candidate_price
            break

    # 2) Fallback: nome reale dalla pagina.
    if not name:
        h1 = soup.find("h1")
        if h1:
            candidate = _clean(h1.get_text(" ", strip=True))
            if _matches(candidate + " " + page_text[:1500], query):
                name = candidate

    if not name:
        title = soup.find("title")
        if title:
            candidate = _clean(title.get_text(" ", strip=True)).split("|")[0]
            if _matches(candidate, query):
                name = candidate

    if not name:
        return None

    # La query deve corrispondere al prodotto vero, non soltanto
    # a testo generico della pagina.
    if not _matches(name + " " + page_text[:1200], query):
        return None

    # 3) Fallback prezzo: scegliamo SOLO indicatori di prezzo attuale.
    # Non usiamo più "_price(page_text)", che poteva prendere
    # "Dernier prix le plus bas" o altri prezzi non correnti.
    if not price:
        current = re.search(
            r"prix\s+actuel\s+(\d{1,4}[.,]\d{2})\s*€",
            page_text,
            re.I,
        )
        if current:
            price = _format_price(current.group(1))

    if not price:
        stock_price = re.search(
            r"en\s+stock\s*[|:]?\s*(\d{1,4}[.,]\d{2})\s*€",
            page_text,
            re.I,
        )
        if stock_price:
            price = _format_price(stock_price.group(1))

    if not price:
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": final_url,
    }


def search(query):
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    results = []
    seen = set()

    # Manteniamo la ricerca dello scraper funzionante.
    # La card serve soltanto per trovare URL candidati.
    for html in _search_page(session, query):
        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a", href=True):
            href = _clean(link.get("href", ""))

            if not href:
                continue

            product_url = urljoin(BASE_URL, href).split("?")[0]

            if not _looks_like_product_url(product_url):
                continue

            if product_url in seen:
                continue

            node = link
            card = None

            # Logica originale funzionante:
            # risale dalla voce prodotto fino alla card con query + prezzo.
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

            # Segniamo l'URL prima della verifica per non richiederlo
            # più volte se la pagina ricerca contiene link duplicati.
            seen.add(product_url)

            # NOVITÀ: nome/prezzo/disponibilità arrivano dalla pagina
            # prodotto reale, non dalla card di ricerca.
            details = _product_details(session, product_url, query)

            if not details:
                continue

            results.append(details)

            if len(results) >= 10:
                return results

        if results:
            return results

    return results


if __name__ == "__main__":
    print(search("Hawas Ice"))
