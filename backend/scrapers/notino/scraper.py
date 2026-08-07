import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

STORE = "Notino"
BASE_URL = "https://www.notino.fr"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

PRICE_RE = re.compile(
    r"€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€",
    re.I,
)

GENERIC_TITLES = (
    "résultat de la recherche",
    "resultat de la recherche",
    "nombre de produits",
    "recherche",
    "résultats",
    "resultats",
    "produits",
    "chargement",
    "loading",
)

BAD_PATHS = (
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

OUT_OF_STOCK_TEXTS = (
    "rupture de stock",
    "épuisé",
    "epuise",
    "indisponible",
    "non disponible",
    "out of stock",
    "sold out",
)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    value = _clean(value).lower()
    value = (
        value.replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("ë", "e")
        .replace("à", "a")
        .replace("â", "a")
        .replace("ä", "a")
        .replace("î", "i")
        .replace("ï", "i")
        .replace("ô", "o")
        .replace("ö", "o")
        .replace("ù", "u")
        .replace("û", "u")
        .replace("ü", "u")
        .replace("ç", "c")
    )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _words(value):
    return [
        word
        for word in _norm(value).split()
        if len(word) > 1
    ]


def _matches(text, query):
    words = _words(query)
    haystack = _norm(text)
    return bool(words) and all(word in haystack for word in words)


def _is_generic_title(title):
    title_n = _norm(title)
    return any(_norm(text) in title_n for text in GENERIC_TITLES)


def _format_price(value):
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return ""

    if number <= 0:
        return ""

    return f"{number:.2f}".replace(".", ",") + "€"


def _prices_from_text(text):
    values = []

    for match in PRICE_RE.finditer(text or ""):
        raw = match.group(1) or match.group(2)

        try:
            number = float(raw.replace(",", "."))
        except ValueError:
            continue

        if number > 0:
            values.append(number)

    return values


def _session():
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def _get(session, url, timeout=15):
    response = session.get(
        url,
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


def _valid_product_url(url):
    if not url:
        return False

    lower = url.lower()

    if "notino.fr" not in lower:
        return False

    path = lower.replace(BASE_URL, "").strip("/")

    if not path:
        return False

    return not any(bad in path for bad in BAD_PATHS)


def _search_pages(session, query):
    urls = [
        BASE_URL + "/search.asp?exps=" + quote_plus(query),
        BASE_URL + "/search?query=" + quote_plus(query),
    ]

    seen = set()

    for url in urls:
        if url in seen:
            continue

        seen.add(url)

        try:
            response = _get(session, url)
        except requests.RequestException as error:
            print("NOTINO SEARCH ERROR:", repr(error))
            continue

        if response.text:
            yield response.text


def _candidate_urls(html, query):
    """
    La pagina di ricerca serve SOLO a trovare URL plausibili.
    Nessun prezzo viene letto da qui.
    """
    soup = BeautifulSoup(html, "html.parser")
    ranked = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))

        if not href:
            continue

        url = urljoin(BASE_URL, href).split("#")[0].split("?")[0]

        if not _valid_product_url(url):
            continue

        if url in seen:
            continue

        anchor_text = _clean(
            " ".join(
                filter(
                    None,
                    [
                        link.get("title"),
                        link.get("aria-label"),
                        link.get_text(" ", strip=True),
                    ],
                )
            )
        )

        url_text = url.replace("-", " ").replace("/", " ")

        score = 0

        if _matches(anchor_text, query):
            score += 10

        if _matches(url_text, query):
            score += 6

        # Un URL senza alcuna relazione con la query non ci interessa.
        if score == 0:
            continue

        seen.add(url)
        ranked.append((score, len(url), url))

    ranked.sort(key=lambda row: (-row[0], row[1]))

    return [row[2] for row in ranked[:12]]


def _json_ld_objects(soup):
    for script in soup.find_all(
        "script",
        attrs={"type": "application/ld+json"},
    ):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop(0)

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            graph = item.get("@graph")

            if isinstance(graph, list):
                stack.extend(graph)

            yield item


def _product_json_ld(soup, query):
    """
    Prima scelta: dati strutturati Product/Offer della pagina prodotto.
    Qui nome e prezzo appartengono allo stesso oggetto.
    """
    candidates = []

    for item in _json_ld_objects(soup):
        item_type = item.get("@type", "")
        types = item_type if isinstance(item_type, list) else [item_type]

        if not any(str(t).lower() == "product" for t in types):
            continue

        name = _clean(item.get("name"))

        if (
            not name
            or _is_generic_title(name)
            or not _matches(name, query)
        ):
            continue

        offers = item.get("offers")
        offer_list = offers if isinstance(offers, list) else [offers]

        for offer in offer_list:
            if not isinstance(offer, dict):
                continue

            availability = _clean(offer.get("availability")).lower()

            if any(
                marker in availability
                for marker in (
                    "outofstock",
                    "soldout",
                    "discontinued",
                )
            ):
                continue

            raw_price = (
                offer.get("price")
                or offer.get("lowPrice")
            )

            price = _format_price(raw_price)

            if not price:
                continue

            image = item.get("image") or ""

            if isinstance(image, list):
                image = image[0] if image else ""

            return {
                "name": name,
                "price": price,
                "image": _clean(image),
            }

    return None


def _meta_name(soup):
    selectors = (
        ('meta[property="og:title"]', "content"),
        ('meta[name="twitter:title"]', "content"),
    )

    for selector, attribute in selectors:
        tag = soup.select_one(selector)

        if tag:
            value = _clean(tag.get(attribute))

            if value:
                # Rimuove il suffisso del sito, senza inventare il nome.
                value = re.sub(
                    r"\s*[\|\-–—]\s*notino.*$",
                    "",
                    value,
                    flags=re.I,
                ).strip()

                if value:
                    return value

    h1 = soup.find("h1")

    if h1:
        return _clean(h1.get_text(" ", strip=True))

    return ""


def _meta_price(soup):
    """
    Fallback conservativo: solo meta/tag esplicitamente associati
    al prezzo del prodotto. Mai il testo globale della pagina.
    """
    selectors = (
        ('meta[property="product:price:amount"]', "content"),
        ('meta[property="og:price:amount"]', "content"),
        ('meta[itemprop="price"]', "content"),
    )

    for selector, attribute in selectors:
        tag = soup.select_one(selector)

        if not tag:
            continue

        price = _format_price(tag.get(attribute))

        if price:
            return price

    price_nodes = soup.select('[itemprop="price"]')

    for node in price_nodes:
        raw = node.get("content") or node.get_text(" ", strip=True)
        values = _prices_from_text(raw)

        if values:
            return _format_price(values[0])

        price = _format_price(raw)

        if price:
            return price

    return ""


def _page_is_out_of_stock(soup):
    text = _norm(soup.get_text(" ", strip=True))
    return any(_norm(marker) in text for marker in OUT_OF_STOCK_TEXTS)


def _extract_product_page(session, url, query):
    """
    Apre l'URL prodotto e verifica lì nome/prezzo.
    Se non siamo sicuri, restituisce None.
    """
    try:
        response = _get(session, url)
    except requests.RequestException as error:
        print("NOTINO PRODUCT ERROR:", repr(error), url)
        return None

    final_url = response.url.split("#")[0].split("?")[0]

    if not _valid_product_url(final_url):
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    structured = _product_json_ld(soup, query)

    if structured:
        print(
            "NOTINO VERIFIED PRODUCT:",
            final_url,
            "|",
            structured["name"],
            "|",
            structured["price"],
        )

        return {
            "store": STORE,
            "name": structured["name"],
            "price": structured["price"],
            "url": final_url,
            "image": structured.get("image", ""),
            "available": True,
            "stock_status": "in_stock",
        }

    # Se la pagina dichiara chiaramente indisponibilità, non inventiamo prezzo.
    if _page_is_out_of_stock(soup):
        print("NOTINO OUT OF STOCK:", final_url)
        return None

    name = _meta_name(soup)

    if (
        not name
        or _is_generic_title(name)
        or not _matches(name, query)
    ):
        return None

    price = _meta_price(soup)

    if not price:
        print("NOTINO PRICE NOT VERIFIED:", final_url)
        return None

    image = ""
    image_tag = soup.select_one('meta[property="og:image"]')

    if image_tag:
        image = _clean(image_tag.get("content"))

    print(
        "NOTINO VERIFIED PRODUCT:",
        final_url,
        "|",
        name,
        "|",
        price,
    )

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": final_url,
        "image": image,
        "available": True,
        "stock_status": "in_stock",
    }


def search(query):
    query = _clean(query)

    if not query:
        return []

    session = _session()

    urls = []
    seen_urls = set()

    # 1) La ricerca trova soltanto URL candidati.
    for html in _search_pages(session, query):
        for url in _candidate_urls(html, query):
            if url not in seen_urls:
                seen_urls.add(url)
                urls.append(url)

    if not urls:
        print("NOTINO NO PRODUCT URL:", query)
        return []

    # 2) Ogni candidato viene verificato sulla SUA pagina prodotto.
    results = []
    seen_products = set()

    for url in urls:
        product = _extract_product_page(
            session,
            url,
            query,
        )

        if not product:
            continue

        key = product["url"].lower()

        if key in seen_products:
            continue

        seen_products.add(key)
        results.append(product)

        if len(results) >= 10:
            break

    return results


if __name__ == "__main__":
    print(search("Hawas Ice"))
