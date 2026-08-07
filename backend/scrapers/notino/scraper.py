import re
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
BASE_URL = "https://www.notino.fr/"
SEARCH_URL = "https://www.notino.fr/search.asp?exps="

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}

OUT_OF_STOCK = (
    "actuellement en rupture de stock",
    "rupture de stock",
    "en rupture",
    "indisponible",
    "épuisé",
    "epuise",
    "out of stock",
    "sold out",
)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value):
    return re.findall(r"[a-z0-9]+", _clean(value).lower())


def _matches(text, query):
    haystack = set(_tokens(text))
    wanted = [x for x in _tokens(query) if len(x) >= 2]
    return bool(wanted) and all(x in haystack for x in wanted)


def _price(text):
    text = _clean(text)

    # Evita di trasformare "Prix minimal 25,50 €" in offerta corrente.
    if re.search(r"prix\s+minimal", text, re.I):
        return ""

    m = re.search(
        r"(?:de\s+)?(\d{1,4}[,.]\d{2})\s*€",
        text,
        re.I,
    )
    return (m.group(1).replace(".", ",") + "€") if m else ""


def _out_of_stock(text):
    low = _clean(text).lower()
    return any(marker in low for marker in OUT_OF_STOCK)


def _direct(query):
    url = SEARCH_URL + quote_plus(query)

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=12,
            allow_redirects=True,
        )
        if response.status_code != 200:
            return []
    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = _clean(a.get("href"))
        if not href:
            continue

        product_url = urljoin(BASE_URL, href)
        if "notino.fr/" not in product_url.lower():
            continue

        node = a
        card_text = ""

        for _ in range(7):
            card_text = _clean(node.get_text(" ", strip=True))
            if (
                "€" in card_text
                or _out_of_stock(card_text)
            ):
                break

            if node.parent is None:
                break
            node = node.parent

        if not _matches(card_text, query):
            continue

        # Notino può mostrare il prodotto nella ricerca anche quando esaurito.
        # In quel caso NON è un'offerta acquistabile.
        if _out_of_stock(card_text):
            continue

        price = _price(card_text)
        if not price:
            continue

        title = _clean(
            a.get("title")
            or a.get("aria-label")
            or a.get_text(" ", strip=True)
        )

        if not title or not _matches(
            f"{title} {card_text}",
            query,
        ):
            continue

        key = product_url.split("?")[0]
        if key in seen:
            continue

        seen.add(key)
        results.append({
            "store": STORE,
            "name": title,
            "price": price,
            "url": key,
        })

        if len(results) >= 10:
            break

    return results


def _bing(query):
    # Mantiene il fallback che permetteva a Notino di comparire
    # quando il datacenter veniva bloccato dal sito diretto.
    search_url = (
        "https://www.bing.com/search?q="
        + quote_plus(f'site:notino.fr "{query}"')
    )

    try:
        response = requests.get(
            search_url,
            headers=HEADERS,
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        print("NOTINO FALLBACK ERROR:", error)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()

    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")
        if not a:
            continue

        href = _clean(a.get("href"))
        title = _clean(a.get_text(" ", strip=True))
        snippet = _clean(li.get_text(" ", strip=True))
        combined = f"{title} {snippet}"

        if "notino.fr" not in href.lower():
            continue

        if not _matches(combined, query):
            continue

        # Se l'indice dice esplicitamente che è esaurito, non mostrarlo.
        if _out_of_stock(combined):
            continue

        # Non usare prezzi "minimal" / storici come offerte.
        price = _price(snippet)
        if not price:
            continue

        key = href.split("?")[0]
        if key in seen:
            continue

        seen.add(key)
        results.append({
            "store": STORE,
            "name": title or query,
            "price": price,
            "url": key,
        })

        if len(results) >= 10:
            break

    return results


def search(query):
    query = _clean(query)
    if not query:
        return []

    direct = _direct(query)
    if direct:
        return direct

    return _bing(query)


if __name__ == "__main__":
    print(search("Rasasi Hawas Ice"))
