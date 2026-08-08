import json
import re
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup


STORE = "Bplatz"
BASE = "https://en.bplatz.de"
TIMEOUT = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SOLD_OUT = (
    "sold out",
    "out of stock",
    "not available",
    "unavailable",
    "available soon",
)

# Prodotti conosciuti che devono essere trovati anche se la ricerca
# Shopify non li restituisce correttamente.
DIRECT_PRODUCTS = (
    (
        ("liquid", "brun", "limited", "edition"),
        (
            BASE + "/Products/liquid-brun-limited-edition-eau-de-parfum-150-ml",
        ),
    ),
    (
        ("liquid", "brun"),
        (
            BASE + "/products/fragrance-world-liquid-brun-eau-de-parfum-100ml",
        ),
    ),
)


def _norm(value):
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value):
    return set(
        token
        for token in _norm(value).split()
        if len(token) > 1
    )


def _match(text, query):
    query_tokens = _tokens(query)
    text_tokens = _tokens(text)

    return bool(query_tokens) and query_tokens.issubset(text_tokens)


def _clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def _price_from_value(value):
    if value is None:
        return None

    text = str(value).strip()

    # Evita prezzi assurdi o valori per litro.
    match = re.search(
        r"(\d{1,4}(?:[.,]\d{1,2})?)",
        text,
    )

    if not match:
        return None

    number = match.group(1).replace(",", ".")

    try:
        amount = float(number)
    except ValueError:
        return None

    if amount <= 0 or amount > 1000:
        return None

    if amount.is_integer():
        return f"{int(amount)},00 €"

    return f"{amount:.2f}".replace(".", ",") + " €"


def _price_from_text(text):
    if not text:
        return None

    # Shopify/Bplatz può mostrare contemporaneamente:
    # Regular price €42,00
    # retail price €47,62
    # Price €1,77 / pro ml
    #
    # Il valore €/ml NON deve mai essere usato come prezzo del prodotto.
    patterns = (
        r"(?:regular\s+price|retail\s+price)\s*€\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        r"(?:price)\s*€\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        r"€\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        r"(\d{1,4}(?:[.,]\d{1,2})?)\s*€",
    )

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if not match:
            continue

        price = _price_from_value(match.group(1))

        if price:
            return price

    return None


def _get(session, url):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        response.raise_for_status()
        return response

    except requests.RequestException as error:
        print(f"BPLATZ ERROR: {error}")
        return None


def _product_json(session, product_url):
    """
    Shopify espone normalmente i dati del prodotto anche tramite
    /products/<handle>.js. È molto più affidabile del testo della pagina
    per prezzo, varianti e disponibilità.
    """
    clean_url = product_url.split("#")[0].split("?")[0].rstrip("/")

    if "/products/" not in clean_url.lower():
        return None

    handle = clean_url.rstrip("/").split("/products/", 1)[1]

    js_url = f"{BASE}/products/{handle}.js"

    response = _get(session, js_url)

    if response is None:
        return None

    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError):
        return None

    return data if isinstance(data, dict) else None


def _is_target_product(name, query):
    """
    Cerca il prodotto vero, non un set/tester che contiene il nome.
    """
    name_norm = _norm(name)
    query_norm = _norm(query)

    if not query_norm:
        return False

    if not _match(name_norm, query_norm):
        return False

    excluded = (
        "tester",
        "gift set",
        "giftset",
        "set",
        "duo",
        "bundle",
        "box",
        "discovery",
        "mini",
    )

    if any(
        token in name_norm.split()
        for token in excluded
    ):
        return False

    return True


def _extract_product(
    session,
    product_url,
    query,
):
    response = _get(session, product_url)

    if response is None:
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    page_text = _clean(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    # Nome: preferiamo h1 / og:title / JSON Shopify.
    name = ""

    h1 = soup.find("h1")

    if h1:
        name = _clean(
            h1.get_text(
                " ",
                strip=True,
            )
        )

    if not name:
        meta = soup.find(
            "meta",
            property="og:title",
        )

        if meta:
            name = _clean(
                meta.get("content")
            )

    data = _product_json(
        session,
        product_url,
    )

    if data:
        json_name = _clean(
            data.get("title")
        )

        if json_name:
            name = json_name

    if not name:
        return None

    if not _is_target_product(
        name,
        query,
    ):
        return None

    # Disponibilità e prezzo dal JSON Shopify, quando possibile.
    variants = []

    if data:
        raw_variants = data.get(
            "variants",
            [],
        )

        if isinstance(raw_variants, list):
            variants = [
                item
                for item in raw_variants
                if isinstance(item, dict)
            ]

    results = []

    for variant in variants:
        available = bool(
            variant.get(
                "available",
                False,
            )
        )

        if not available:
            continue

        price = _price_from_value(
            variant.get("price")
        )

        if not price:
            continue

        variant_title = _clean(
            variant.get(
                "title",
                "",
            )
        )

        # Se Shopify restituisce "Default Title", non lo aggiungiamo.
        size_match = re.search(
            r"\b(\d{1,4}(?:[.,]\d+)?)\s*ml\b",
            " ".join(
                [
                    name,
                    variant_title,
                ]
            ),
            re.I,
        )

        size = None

        if size_match:
            size = (
                size_match.group(1)
                .replace(",", ".")
                + " ml"
            )

        result_name = name

        if size and not re.search(
            r"\b\d{1,4}(?:[.,]\d+)?\s*ml\b",
            result_name,
            re.I,
        ):
            result_name = f"{name} {size}"

        results.append({
            "store": STORE,
            "name": result_name,
            "price": price,
            "url": product_url,
            "available": True,
            "availability": "in_stock",
            **({"size": size} if size else {}),
        })

    if results:
        return results

    # Fallback per pagine Shopify che non espongono correttamente
    # le varianti nel .js.
    price = _price_from_text(page_text)

    if not price:
        return None

    if any(
        word in page_text.lower()
        for word in SOLD_OUT
    ):
        return None

    size_match = re.search(
        r"\b(\d{1,4}(?:[.,]\d+)?)\s*ml\b",
        name,
        re.I,
    )

    size = None

    if size_match:
        size = (
            size_match.group(1)
            .replace(",", ".")
            + " ml"
        )

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": product_url,
        "available": True,
        "availability": "in_stock",
        **({"size": size} if size else {}),
    }


def _search_shopify(session, query):
    """
    Ricerca Shopify + raccolta degli URL prodotto.
    Non si ferma al primo risultato: deve poter trovare sia
    Liquid Brun normale sia Limited Edition.
    """
    q = quote_plus(query)

    urls = (
        f"{BASE}/search?q={q}&type=product",
        f"{BASE}/search?q={q}",
    )

    product_urls = []
    seen = set()

    for search_url in urls:
        response = _get(
            session,
            search_url,
        )

        if response is None:
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        for link in soup.find_all(
            "a",
            href=True,
        ):
            href = urljoin(
                BASE,
                link.get("href", ""),
            ).split("#")[0].split("?")[0]

            if "/products/" not in href.lower():
                continue

            if href.lower() in seen:
                continue

            name_candidates = [
                _clean(
                    link.get_text(
                        " ",
                        strip=True,
                    )
                ),
                _clean(
                    link.get("title")
                ),
                _clean(
                    link.get("aria-label")
                ),
            ]

            img = link.find("img")

            if img:
                name_candidates.append(
                    _clean(
                        img.get("alt")
                    )
                )

            name = next(
                (
                    item
                    for item in name_candidates
                    if item
                ),
                "",
            )

            if not _is_target_product(
                name,
                query,
            ):
                continue

            seen.add(href.lower())
            product_urls.append(href)

        # Non interrompiamo dopo il primo URL:
        # servono tutte le varianti pertinenti.
        if len(product_urls) >= 20:
            break

    return product_urls


def _direct_urls(query):
    query_tokens = _tokens(query)
    results = []

    for required, urls in DIRECT_PRODUCTS:
        if set(required).issubset(query_tokens):
            results.extend(urls)

    return results


def search(query):
    query = str(query or "").strip()

    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    # Prima gli URL diretti conosciuti: elimina la dipendenza
    # dalla ricerca interna Shopify per Liquid Brun.
    product_urls = _direct_urls(query)

    # Poi aggiungiamo eventuali prodotti trovati dalla ricerca Shopify.
    for url in _search_shopify(
        session,
        query,
    ):
        if url.lower() not in {
            item.lower()
            for item in product_urls
        }:
            product_urls.append(url)

    results = []
    seen = set()

    for product_url in product_urls:
        item_results = _extract_product(
            session,
            product_url,
            query,
        )

        if not item_results:
            continue

        if not isinstance(
            item_results,
            list,
        ):
            item_results = [item_results]

        for item in item_results:
            key = (
                item.get("url", "").lower(),
                item.get("size", ""),
                item.get("price", ""),
            )

            if key in seen:
                continue

            seen.add(key)
            results.append(item)

    # Formato più piccolo prima.
    results.sort(
        key=lambda item: (
            _size_number(
                item.get("size", "")
            ),
            item.get("name", "").lower(),
        )
    )

    return results[:20]


def _size_number(value):
    match = re.search(
        r"(\d{1,4}(?:[.,]\d+)?)\s*ml",
        str(value or ""),
        re.I,
    )

    if not match:
        return 9999

    try:
        return float(
            match.group(1).replace(",", ".")
        )
    except ValueError:
        return 9999


if __name__ == "__main__":
    tests = (
        "Liquid Brun",
        "Liquid Brun Limited Edition",
        "Rasasi Hawas",
        "Armaf Club de Nuit",
        "Afnan 9 PM Night Out",
        "French Avenue",
    )

    for query in tests:
        print("\n" + "=" * 60)
        print("QUERY:", query)

        items = search(query)

        print("RISULTATI:", len(items))

        for item in items:
            print(item)
