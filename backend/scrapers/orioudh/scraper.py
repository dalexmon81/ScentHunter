import json
import re
import html
from typing import List, Dict, Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup


STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/json;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}


# ============================================================
# NORMALIZZAZIONE
# ============================================================

def _clean(value) -> str:
    return re.sub(
        r"\s+",
        " ",
        html.unescape(str(value or "")),
    ).strip()


def _norm(value) -> str:
    value = _clean(value).lower()

    value = re.sub(
        r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)",
        " ",
        value,
    )

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


IGNORED_WORDS = {
    "eau",
    "de",
    "parfum",
    "perfume",
    "edp",
    "edt",
    "extrait",
    "spray",
    "ml",
    "for",
    "by",
}


def _tokens(query: str) -> List[str]:
    return [
        token
        for token in _norm(query).split()
        if token not in IGNORED_WORDS
        and len(token) > 1
    ]


def _matches(text: str, query: str) -> bool:
    normalized_text = _norm(text)
    tokens = _tokens(query)

    return bool(tokens) and all(
        token in normalized_text
        for token in tokens
    )


# ============================================================
# QUERY GENERICA MULTI-PASS
# ============================================================

def _search_queries(query: str) -> List[str]:
    """
    Genera query alternative senza conoscere nomi di profumi.

    Serve soprattutto quando Shopify indicizza una variante con una
    forma leggermente diversa da quella digitata dall'utente.

    Esempi:
        9 PM Night Out
        9PM Night Out
        9 PM -> 9PM

    Non contiene nomi di prodotti hard-coded.
    """
    raw = _clean(query)
    normalized = _norm(raw)

    if not normalized:
        return []

    attempts = []
    seen = set()

    def add(value):
        value = _clean(value)
        key = _norm(value)

        if key and key not in seen:
            seen.add(key)
            attempts.append(value)

    add(raw)

    # 9 PM -> 9PM
    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )

    if compact != normalized:
        add(compact)

    tokens = [
        token
        for token in normalized.split()
        if token not in IGNORED_WORDS
    ]

    # Query senza parole descrittive generiche.
    if len(tokens) >= 2:
        add(" ".join(tokens))

    # Fallback progressivi: permettono a Shopify di trovare prodotti
    # quando il motore non gestisce bene una query lunga.
    if len(tokens) >= 3:
        add(" ".join(tokens[1:]))
        add(" ".join(tokens[-2:]))

    # Singoli token significativi.
    for token in tokens:
        if len(token) >= 3:
            add(token)

    return attempts[:8]


# ============================================================
# PREZZO
# ============================================================

def _price(value) -> Optional[str]:
    if value is None:
        return None

    text = _clean(value).replace("€", "").strip()

    match = re.search(
        r"(\d+(?:[.,]\d{1,2})?)",
        text,
    )

    if not match:
        return None

    try:
        number = float(
            match.group(1).replace(",", ".")
        )
    except ValueError:
        return None

    if number <= 0:
        return None

    return (
        f"{number:.2f}".replace(".", ",")
        + " €"
    )


# ============================================================
# SHOPIFY PREDICTIVE SEARCH
# ============================================================

def _from_shopify_json(
    session: requests.Session,
    query: str,
) -> List[Dict[str, str]]:

    endpoint = (
        BASE_URL
        + "/search/suggest.json"
    )

    params = {
        "q": query,
        "resources[type]": "product",
        "resources[options][unavailable_products]": "show",
        "resources[limit]": "20",
    }

    try:
        response = session.get(
            endpoint,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if response.status_code != 200:
            return []

        data = response.json()

    except (
        requests.RequestException,
        ValueError,
    ):
        return []

    products = (
        data.get("resources", {})
        .get("results", {})
        .get("products", [])
    )

    results = []
    seen = set()

    for product in products:
        if not isinstance(product, dict):
            continue

        title = _clean(
            product.get("title")
        )

        vendor = _clean(
            product.get("vendor")
        )

        if not title:
            continue

        # Filtro sul titolo reale.
        # Non basta che Shopify abbia trovato il prodotto:
        # deve realmente appartenere alla query.
        if not _matches(
            title + " " + vendor,
            query,
        ):
            continue

        product_url = product.get("url")

        if not product_url:
            continue

        url = (
            urljoin(
                BASE_URL,
                product_url,
            )
            .split("?")[0]
        )

        if url in seen:
            continue

        price = (
            _price(product.get("price"))
            or _price(product.get("price_min"))
        )

        # Per i risultati di ScentHunter ci interessa comunque
        # conoscere il prodotto anche quando è esaurito.
        # Se Shopify non espone il prezzo qui, lo recuperiamo
        # dalla pagina prodotto più avanti.
        seen.add(url)

        results.append({
            "store": STORE,
            "name": title,
            "price": price or "",
            "url": url,
        })

    return results


# ============================================================
# SHOPIFY SEARCH HTML
# ============================================================

def _from_search_html(
    session: requests.Session,
    query: str,
) -> List[Dict[str, str]]:

    url = (
        BASE_URL
        + "/search?q="
        + quote_plus(query)
        + "&type=product"
    )

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return []

    except requests.RequestException:
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    results = []
    seen = set()

    for anchor in soup.select(
        'a[href*="/products/"]'
    ):
        href = (
            urljoin(
                BASE_URL,
                anchor.get("href", ""),
            )
            .split("?")[0]
        )

        if not href or href in seen:
            continue

        card = anchor

        for _ in range(5):
            if not card.parent:
                break

            card = card.parent

            text = _clean(
                card.get_text(
                    " ",
                    strip=True,
                )
            )

            if "€" in text and len(text) < 1200:
                break

        card_text = _clean(
            card.get_text(
                " ",
                strip=True,
            )
        )

        title = _clean(
            anchor.get("title")
            or anchor.get_text(
                " ",
                strip=True,
            )
        )

        if not title:
            continue

        if not _matches(
            title + " " + card_text,
            query,
        ):
            continue

        price = None

        prices = re.findall(
            r"\b\d{1,4}[.,]\d{2}\s*€",
            card_text,
        )

        for raw_price in prices:
            price = _price(raw_price)

            if price:
                break

        seen.add(href)

        results.append({
            "store": STORE,
            "name": title,
            "price": price or "",
            "url": href,
        })

    return results


# ============================================================
# PRODUCT PAGE
# ============================================================

def _product_page(
    session: requests.Session,
    url: str,
    query: str,
) -> Optional[Dict[str, str]]:

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return None

    except requests.RequestException:
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    # --------------------------------------------------------
    # JSON-LD
    # --------------------------------------------------------

    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        raw = (
            script.string
            or script.get_text()
        )

        try:
            obj = json.loads(raw)
        except Exception:
            continue

        objects = (
            obj
            if isinstance(obj, list)
            else [obj]
        )

        for item in objects:
            if not isinstance(item, dict):
                continue

            if item.get("@type") != "Product":
                continue

            name = _clean(
                item.get("name")
            )

            if not name or not _matches(
                name,
                query,
            ):
                continue

            offers = (
                item.get("offers")
                or {}
            )

            if isinstance(
                offers,
                list,
            ):
                offers = (
                    offers[0]
                    if offers
                    else {}
                )

            price = _price(
                offers.get("price")
                if isinstance(
                    offers,
                    dict,
                )
                else None
            )

            if price:
                return {
                    "store": STORE,
                    "name": name,
                    "price": price,
                    "url": response.url,
                }

    # --------------------------------------------------------
    # H1 + pagina
    # --------------------------------------------------------

    h1 = soup.find("h1")

    name = (
        _clean(
            h1.get_text(
                " ",
                strip=True,
            )
        )
        if h1
        else ""
    )

    if not name or not _matches(
        name,
        query,
    ):
        return None

    text = _clean(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    match = re.search(
        r"\b(\d{1,4}[.,]\d{2})\s*€",
        text,
    )

    price = (
        _price(match.group(1))
        if match
        else None
    )

    if not price:
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": response.url,
    }


# ============================================================
# STOCK
# ============================================================

def _is_out_of_stock_page(
    session: requests.Session,
    url: str,
) -> bool:

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return False

    except requests.RequestException:
        return False

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    found_offer = False
    found_available = False

    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        raw = (
            script.string
            or script.get_text()
        )

        try:
            obj = json.loads(raw)
        except Exception:
            continue

        stack = (
            obj
            if isinstance(obj, list)
            else [obj]
        )

        while stack:
            item = stack.pop(0)

            if not isinstance(item, dict):
                continue

            if item.get("@type") == "Product":
                offers = (
                    item.get("offers")
                    or []
                )

                if isinstance(
                    offers,
                    dict,
                ):
                    offers = [offers]

                for offer in offers:
                    if not isinstance(
                        offer,
                        dict,
                    ):
                        continue

                    found_offer = True

                    availability = _clean(
                        offer.get(
                            "availability"
                        )
                    ).lower()

                    if any(
                        marker
                        in availability
                        for marker in (
                            "instock",
                            "in_stock",
                            "limitedavailability",
                            "preorder",
                            "backorder",
                        )
                    ):
                        found_available = True

            for value in item.values():
                if isinstance(
                    value,
                    dict,
                ):
                    stack.append(value)

                elif isinstance(
                    value,
                    list,
                ):
                    stack.extend(
                        value
                        for value in value
                        if isinstance(
                            value,
                            dict,
                        )
                    )

    page_text = _clean(
        soup.get_text(
            " ",
            strip=True,
        )
    ).lower()

    explicit_markers = (
        "out of stock",
        "sold out",
        "nicht auf lager",
        "ausverkauft",
        "rupture de stock",
        "épuisé",
    )

    if found_offer and not found_available:
        if any(
            marker in page_text
            for marker in explicit_markers
        ):
            return True

    if any(
        marker in page_text
        for marker in explicit_markers
    ):
        return True

    for button in soup.find_all(
        ["button", "input"]
    ):
        label = _clean(
            button.get_text(
                " ",
                strip=True,
            )
            if button.name == "button"
            else button.get("value")
        ).lower()

        if any(
            marker in label
            for marker in explicit_markers
        ):
            return True

    return False


# ============================================================
# SEARCH
# ============================================================

def search(
    query: str,
) -> List[Dict[str, str]]:

    query = _clean(query)

    if not query:
        return []

    session = requests.Session()

    results = []
    seen = set()

    # --------------------------------------------------------
    # IMPORTANTISSIMO:
    # proviamo più forme della stessa query.
    # Non ci sono nomi di profumi hard-coded.
    # --------------------------------------------------------

    for search_query in _search_queries(query):

        batch = _from_shopify_json(
            session,
            search_query,
        )

        # Se predictive search non restituisce nulla,
        # proviamo anche la ricerca HTML.
        if not batch:
            batch = _from_search_html(
                session,
                search_query,
            )

        for item in batch:
            if not isinstance(item, dict):
                continue

            url = item.get("url")

            if not url or url in seen:
                continue

            # Filtro finale sempre sulla query ORIGINALE.
            # Così un fallback generico non può introdurre
            # prodotti estranei.
            if not _matches(
                item.get("name", ""),
                query,
            ):
                continue

            seen.add(url)

            checked = dict(item)

            # Se la ricerca Shopify non ha dato il prezzo,
            # recuperiamo la pagina reale.
            if not checked.get("price"):
                page_item = _product_page(
                    session,
                    url,
                    query,
                )

                if page_item:
                    checked.update(
                        page_item
                    )

            # Verifica stock sulla pagina reale.
            if _is_out_of_stock_page(
                session,
                url,
            ):
                checked["price"] = (
                    "Out of stock"
                )
                checked["available"] = False
                checked["availability"] = (
                    "out_of_stock"
                )
                checked["stock_status"] = (
                    "out_of_stock"
                )
            else:
                checked.setdefault(
                    "available",
                    True,
                )
                checked.setdefault(
                    "availability",
                    "in_stock",
                )
                checked.setdefault(
                    "stock_status",
                    "in_stock",
                )

            results.append(checked)

    return results


# ============================================================
# TEST LOCALE
# ============================================================

if __name__ == "__main__":

    for query in (
        "9 PM",
        "9 PM Night Out",
        "9 PM Rebel",
        "Rayhaan Aquatica",
        "Turathi Blue",
    ):
        print(
            "\nQUERY:",
            query,
        )

        found = search(query)

        print(
            "RISULTATI:",
            len(found),
        )

        for item in found:
            print(item)
