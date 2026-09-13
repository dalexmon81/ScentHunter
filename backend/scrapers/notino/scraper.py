from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Notino"
BASE_HOSTS = {"www.notino.fr", "notino.fr"}

BING_URL = "https://www.bing.com/search?q="

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
}


# ---------------------------------------------------------------------------
# NORMALIZZAZIONE
# ---------------------------------------------------------------------------

def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _price(text: str) -> str:
    """
    Estrae prezzi francesi/europei dagli snippet Bing.

    Esempi:
      51,00 €
      51.00 €
      de 40,00 €
      à partir de 40,00 €
      40 €
    """

    if not text:
        return ""

    patterns = (
        r"(?:à\s+partir\s+de|a\s+partir\s+de|de|dès)\s+"
        r"(\d{1,4}(?:[.,]\d{2})?)\s*€",

        r"(\d{1,4}(?:[.,]\d{2}))\s*€",

        r"(\d{1,4})\s*€",
    )

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).replace(".", ",")
            if "," not in value:
                value += ",00"
            return f"{value}€"

    return ""


def _clean_title(title: str) -> str:
    title = _clean(title)

    # Testi promozionali che Bing/Notino possono mettere davanti al prodotto.
    title = re.sub(
        r"^(?:livraison\s+offerte\s+)?"
        r"(?:promo\s+|promotion\s+)?"
        r"(?:cadeaux?|cadeau)\s+offerts?\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )

    title = re.sub(
        r"^(?:promo|promotion)\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )

    # Rating / prezzo alla fine del titolo Bing.
    title = re.sub(
        r"\s+\d[,.]\d\s*\(\s*\d+\s*\)"
        r"\s+(?:de\s+)?\d{1,4}[,.]\d{2}\s*€.*$",
        "",
        title,
        flags=re.IGNORECASE,
    )

    title = re.sub(
        r"\s+(?:de\s+)?\d{1,4}[,.]\d{2}\s*€.*$",
        "",
        title,
        flags=re.IGNORECASE,
    )

    return _clean(title)


# ---------------------------------------------------------------------------
# FILTRI PRODOTTO
# ---------------------------------------------------------------------------

def _single_perfume(title: str) -> bool:
    """
    Evita che una ricerca di profumo restituisca:
    - coffret
    - gift set
    - miniature
    - campioni
    - prodotti corpo
    - deodoranti
    - ecc.
    """

    low = _clean(title).lower()

    blocked = (
        "coffret",
        "gift set",
        "set cadeau",
        "coffret cadeau",
        "miniature",
        "échantillon",
        "echantillon",
        "sample",
        "discovery set",
        "lot de ",
        "pack de ",
        "duo ",
        "trio ",
        "gel douche",
        "shower gel",
        "déodorant",
        "deodorant",
        "lotion corps",
        "body lotion",
        "crème corps",
        "creme corps",
        "body cream",
        "après-rasage",
        "apres-rasage",
        "after shave",
        "aftershave",
        "spray corps",
        "body spray",
        "brume",
        "hair mist",
        "shampooing",
        "shampoo",
        "conditioner",
    )

    return not any(item in low for item in blocked)


def _is_notino_product_url(url: str) -> bool:
    """
    Notino oggi usa normalmente URL del tipo:

    /french-avenue/liquid-brun-eau-de-parfum-mixte/p-16289640/

    Il vecchio scraper richiedeva esattamente due segmenti e quindi
    avrebbe scartato questi URL.
    """

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    if parsed.netloc.lower() not in BASE_HOSTS:
        return False

    path = parsed.path.lower()

    if "/p-" not in path:
        return False

    # Deve esserci un ID prodotto numerico.
    if not re.search(r"/p-\d+/?$", path):
        return False

    blocked = (
        "/search",
        "/cart",
        "/wishlist",
        "/mynotino",
        "/livraison",
        "/avis",
        "/contact",
        "/magazine",
        "/marques/",
        "/parfums/",
        "/cosmetiques/",
        "/cheveux/",
        "/dentaire/",
        "/homme/",
        "/femme/",
    )

    if any(item in path for item in blocked):
        return False

    return True


def _query_words(query: str) -> List[str]:
    return [
        re.sub(r"[^a-z0-9àâäéèêëîïôöùûüÿç-]", "", word.lower())
        for word in query.split()
        if len(word.strip()) >= 2
    ]


def _matches_query(title: str, snippet: str, query: str) -> bool:
    """
    Controllo morbido:
    non richiede che ogni parola compaia nello stesso campo,
    perché Bing può mettere parte del nome nel title e parte nello snippet.
    """

    words = _query_words(query)

    if not words:
        return True

    text = f"{title} {snippet}".lower()

    matches = 0

    for word in words:
        if word and word in text:
            matches += 1

    # Per query composte come "Liquid Brun":
    # almeno 1 parola è sufficiente se il risultato è chiaramente Notino.
    if len(words) == 1:
        return matches >= 1

    return matches >= max(1, len(words) - 1)


# ---------------------------------------------------------------------------
# BING
# ---------------------------------------------------------------------------

def _bing_request(query: str) -> str:
    url = BING_URL + quote_plus(query)

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=(4.0, 12.0),
        allow_redirects=True,
    )

    response.raise_for_status()

    return response.text


def _parse_bing_html(
    html: str,
    query: str,
) -> List[Dict[str, Any]]:

    soup = BeautifulSoup(html, "html.parser")

    results: List[Dict[str, Any]] = []
    seen = set()

    # Bing classico.
    nodes = soup.select("li.b_algo")

    # Fallback nel caso Bing cambi leggermente markup.
    if not nodes:
        nodes = soup.select("main li")

    for node in nodes:
        link = node.select_one("h2 a")

        if link is None:
            link = node.select_one("a[href]")

        if link is None:
            continue

        href = _clean(link.get("href"))

        if not href:
            continue

        # Bing può restituire URL di tracking.
        # In quel caso proviamo a recuperare l'URL Notino reale.
        if "notino.fr" not in href.lower():
            continue

        title = _clean_title(link.get_text(" ", strip=True))
        snippet = _clean(node.get_text(" ", strip=True))

        if not _is_notino_product_url(href):
            continue

        if not _matches_query(title, snippet, query):
            continue

        if not _single_perfume(title):
            continue

        price = _price(snippet)

        # Alcuni risultati possono avere il prezzo nel titolo.
        if not price:
            price = _price(title)

        # Se Bing non espone il prezzo, non inventiamo nulla.
        if not price:
            continue

        if href in seen:
            continue

        seen.add(href)

        if len(title) < 3:
            title = _clean(query)

        results.append(
            {
                "store": STORE,
                "name": title,
                "price": price,
                "url": href,
            }
        )

        if len(results) >= 12:
            break

    return results


def _bing(query: str) -> List[Dict[str, Any]]:
    """
    Fallback storico di Notino.

    IMPORTANTE:
    questa funzione NON contatta Notino.

    Cerca su Bing:
        site:notino.fr "QUERY"

    e recupera:
        nome
        prezzo
        URL reale Notino
    """

    query = _clean(query)

    if not query:
        return []

    search_queries = [
        f'site:notino.fr "{query}"',
        f"site:notino.fr {query}",
        f'site:www.notino.fr "{query}"',
    ]

    output: List[Dict[str, Any]] = []
    seen = set()

    for bing_query in search_queries:

        try:
            html = _bing_request(bing_query)

        except requests.RequestException as exc:
            print(
                f"NOTINO BING ERROR: {type(exc).__name__}: {exc}"
            )
            continue

        except Exception as exc:
            print(
                f"NOTINO BING UNEXPECTED ERROR: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        try:
            found = _parse_bing_html(html, query)

        except Exception as exc:
            print(
                f"NOTINO BING PARSE ERROR: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        for item in found:

            url = item.get("url", "")

            if not url:
                continue

            if url in seen:
                continue

            seen.add(url)
            output.append(item)

            if len(output) >= 12:
                return output

    return output


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def search(query: str) -> List[Dict[str, Any]]:
    """
    Entry point utilizzato da ScentHunter.

    Non facciamo più una richiesta diretta a Notino:
    il 403 è a livello di trasporto/IP e quindi il tentativo diretto
    sarebbe soltanto tempo perso.

    Bing viene utilizzato come discovery layer.
    """

    query = _clean(query)

    if not query:
        return []

    return _bing(query)


# ---------------------------------------------------------------------------
# TEST LOCALE
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_query = "Liquid Brun"

    results = search(test_query)

    print(f"RISULTATI: {len(results)}")

    for result in results:
        print(result)
