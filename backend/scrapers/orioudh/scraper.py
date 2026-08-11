import json
import re
import html
from typing import List, Dict, Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup


STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}

IGNORED_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "ml", "for", "by",
}


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
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(query: str) -> List[str]:
    return [
        x for x in _norm(query).split()
        if x not in IGNORED_WORDS and len(x) > 1
    ]


def _matches(text: str, query: str) -> bool:
    n = _norm(text)
    tokens = _tokens(query)
    return bool(tokens) and all(t in n for t in tokens)


def _price(value) -> Optional[str]:
    if value is None:
        return None

    s = _clean(value).replace("€", "").strip()
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", s)

    if not m:
        return None

    try:
        number = float(m.group(1).replace(",", "."))
    except ValueError:
        return None

    if number <= 0:
        return None

    return f"{number:.2f}".replace(".", ",") + " €"


def _search_terms(query: str) -> List[str]:
    """
    Genera solo forme generiche della query ricevuta.
    Non contiene nomi di profumi hard-coded.
    """
    raw = _clean(query)
    normalized = _norm(raw)

    if not normalized:
        return []

    terms = []
    seen = set()

    def add(value):
        value = _clean(value)
        key = _norm(value)
        if key and key not in seen:
            seen.add(key)
            terms.append(value)

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
        t for t in normalized.split()
        if t not in IGNORED_WORDS
    ]

    if len(tokens) >= 2:
        add(" ".join(tokens))

    # Per query lunghe proviamo anche il nucleo senza il primo token.
    if len(tokens) >= 3:
        add(" ".join(tokens[1:]))

    return terms


def _predictive(
    session: requests.Session,
    query: str,
) -> List[Dict]:
    endpoint = BASE_URL + "/search/suggest.json"

    params = {
        "q": query,
        "resources[type]": "product",
        "resources[options][unavailable_products]": "show",
        "resources[limit]": "50",
    }

    try:
        r = session.get(
            endpoint,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if r.status_code != 200:
            return []

        data = r.json()

    except (requests.RequestException, ValueError):
        return []

    return (
        data.get("resources", {})
        .get("results", {})
        .get("products", [])
        or []
    )


def _search_html(
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
        r = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if r.status_code != 200:
            return []

    except requests.RequestException:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    seen = set()

    for a in soup.select('a[href*="/products/"]'):
        href = urljoin(
            BASE_URL,
            a.get("href", ""),
        ).split("?")[0]

        if not href or href in seen:
            continue

        card = a
        title = _clean(
            a.get("title")
            or a.get("aria-label")
            or a.get_text(" ", strip=True)
        )

        # Cerca il titolo nel contenitore della card.
        for _ in range(6):
            if not card.parent:
                break
            card = card.parent
            text = _clean(
                card.get_text(" ", strip=True)
            )
            if len(text) < 1500 and (
                "€" in text or title
            ):
                if not title:
                    title = text
                break

        text = _clean(
            card.get_text(" ", strip=True)
        )

        if not title:
            title = text

        if not _matches(
            title + " " + text,
            query,
        ):
            continue

        price = None
        for raw in re.findall(
            r"\b\d{1,4}[.,]\d{2}\s*€",
            text,
        ):
            price = _price(raw)
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


def _product_json(
    session: requests.Session,
    url: str,
) -> Optional[Dict]:
    """
    Shopify .js: fonte autorevole per titolo, prezzo e disponibilità
    delle varianti.
    """
    clean = url.split("?")[0].rstrip("/")
    js_url = clean + ".js"

    try:
        r = session.get(
            js_url,
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if r.status_code != 200:
            return None

        data = r.json()

        return data if isinstance(data, dict) else None

    except (requests.RequestException, ValueError):
        return None


def _from_product_json(
    data: Dict,
    url: str,
) -> Optional[Dict[str, str]]:
    title = _clean(data.get("title"))

    if not title:
        return None

    variants = data.get("variants") or []

    # Shopify indica la disponibilità vera sulle varianti.
    available = [
        v for v in variants
        if isinstance(v, dict)
        and v.get("available") is True
    ]

    prices = []

    # Preferiamo le varianti realmente acquistabili.
    pool = available or variants

    for variant in pool:
        if not isinstance(variant, dict):
            continue

        value = variant.get("price")

        if value is None:
            continue

        try:
            number = float(value)

            # Gestisce sia centesimi sia formato decimale.
            if number >= 100:
                number /= 100

            prices.append(number)

        except (ValueError, TypeError):
            continue

    price = ""

    if prices:
        price = (
            f"{min(prices):.2f}"
            .replace(".", ",")
            + " €"
        )

    is_available = bool(available)

    return {
        "store": STORE,
        "name": title,
        "price": price,
        "url": url,
        "available": is_available,
        "availability": (
            "in_stock"
            if is_available
            else "out_of_stock"
        ),
        "stock_status": (
            "in_stock"
            if is_available
            else "out_of_stock"
        ),
    }


def search(query: str) -> List[Dict[str, str]]:
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()
    results = []
    seen = set()

    # ========================================================
    # 1. Tutte le forme della query ricevuta
    # ========================================================

    for search_query in _search_terms(query):

        # ----------------------------------------------------
        # Shopify predictive
        # ----------------------------------------------------

        products = _predictive(
            session,
            search_query,
        )

        # ----------------------------------------------------
        # Anche HTML, SEMPRE.
        # Non usiamo il fallback solo quando predictive è vuoto:
        # i due motori possono restituire prodotti diversi.
        # ----------------------------------------------------

        html_products = _search_html(
            session,
            search_query,
        )

        candidates = []

        for product in products:
            if not isinstance(product, dict):
                continue

            title = _clean(
                product.get("title")
            )

            url = product.get("url")

            if not title or not url:
                continue

            url = urljoin(
                BASE_URL,
                url,
            ).split("?")[0]

            candidates.append({
                "name": title,
                "url": url,
                "price": (
                    _price(product.get("price"))
                    or _price(product.get("price_min"))
                    or ""
                ),
            })

        candidates.extend(
            html_products
        )

        # ----------------------------------------------------
        # 2. Verifica definitiva sul titolo reale.
        # ----------------------------------------------------

        for candidate in candidates:

            url = candidate.get("url")
            title = candidate.get("name", "")

            if not url or url in seen:
                continue

            if not _matches(
                title,
                query,
            ):
                continue

            # IMPORTANTE:
            # filtriamo anche sulla query originale.
            # Una query alternativa non può introdurre
            # un prodotto di un'altra famiglia.
            if not _matches(
                title,
                query,
            ):
                continue

            data = _product_json(
                session,
                url,
            )

            if data:
                item = _from_product_json(
                    data,
                    url,
                )
            else:
                item = None

            # Se .js non è disponibile, manteniamo comunque
            # il risultato trovato dal motore Shopify.
            if not item:
                item = {
                    "store": STORE,
                    "name": title,
                    "price": candidate.get(
                        "price",
                        "",
                    ),
                    "url": url,
                }

            # Verifica nuovamente il titolo canonico Shopify.
            if not _matches(
                item.get("name", ""),
                query,
            ):
                continue

            seen.add(url)
            results.append(item)

    return results


if __name__ == "__main__":
    for query in (
        "9 PM",
        "9 PM Night Out",
        "9 PM Rebel",
    ):
        print("\nQUERY:", query)

        for item in search(query):
            print(item)
