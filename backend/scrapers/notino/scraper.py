import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

STORE = "Notino"
BASE_URL = "https://www.notino.fr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
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
    if not value:
        return ""

    value = str(value).strip().replace(" ", "").replace("€", "")

    m = re.search(r"\d{1,4}(?:[.,]\d{2})", value)
    if not m:
        return ""

    return m.group(0).replace(".", ",") + "€"


def _extract_product(session, product_url, query):
    """
    Apre la VERA scheda prodotto Notino.
    Nome e prezzo vengono estratti solo da questa pagina.
    """

    try:
        response = session.get(
            product_url,
            headers=HEADERS,
            timeout=15,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        print("NOTINO PRODUCT ERROR:", product_url, error, flush=True)
        return None

    final_url = response.url.split("?")[0]

    # Sicurezza: dobbiamo essere ancora su Notino.
    if "notino.fr" not in final_url.lower():
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    # -----------------------
    # NOME PRODOTTO
    # -----------------------

    name = ""

    h1 = soup.find("h1")
    if h1:
        name = _clean(h1.get_text(" ", strip=True))

    # Fallback: title / meta
    if not name or not _matches(name, query):
        meta = soup.find("meta", property="og:title")

        if meta:
            candidate = _clean(meta.get("content"))
            if _matches(candidate, query):
                name = candidate

    # La scheda aperta deve essere davvero del prodotto cercato.
    if not name or not _matches(name, query):
        print(
            "NOTINO REJECT PRODUCT NAME:",
            product_url,
            "| NAME:",
            name,
            flush=True,
        )
        return None

    # -----------------------
    # DISPONIBILITÀ
    # -----------------------

    page_text = _clean(soup.get_text(" ", strip=True))
    page_lower = page_text.lower()

    unavailable = (
        "rupture de stock",
        "épuisé",
        "indisponible",
        "produit indisponible",
        "actuellement indisponible",
    )

    if any(x in page_lower for x in unavailable):
        print(
            "NOTINO OUT OF STOCK:",
            name,
            product_url,
            flush=True,
        )
        return None

    # -----------------------
    # PREZZO
    # -----------------------

    price = ""

    # 1. Prima scelta: metadata strutturati della scheda.
    price_selectors = [
        'meta[property="product:price:amount"]',
        'meta[itemprop="price"]',
        '[itemprop="price"]',
    ]

    for selector in price_selectors:
        element = soup.select_one(selector)

        if not element:
            continue

        value = (
            element.get("content")
            or element.get("value")
            or element.get_text(" ", strip=True)
        )

        price = _format_price(value)

        if price:
            break

    # 2. JSON-LD: spesso contiene prezzo e disponibilità reali.
    if not price:
        for script in soup.find_all(
            "script",
            attrs={"type": "application/ld+json"}
        ):
            raw = script.string or script.get_text()

            if not raw:
                continue

            # Cerchiamo price nel JSON senza dipendere
            # dalla struttura esatta.
            matches = re.findall(
                r'"price"\s*:\s*"?(\d{1,4}(?:[.,]\d{1,2})?)"?',
                raw,
                re.I,
            )

            for value in matches:
                price = _format_price(value)

                if price:
                    break

            if price:
                break

    # 3. Fallback finale: cerca prezzi vicino alla zona prodotto.
    if not price:
        price_matches = list(PRICE_RE.finditer(page_text))

        # Non prendiamo più "l'ultimo prezzo della pagina".
        # Accettiamo il primo prezzo plausibile della scheda.
        for match in price_matches:
            value = match.group(1) or match.group(2)
            candidate = _format_price(value)

            if candidate:
                price = candidate
                break

    if not price:
        print(
            "NOTINO REJECT NO PRICE:",
            name,
            product_url,
            flush=True,
        )
        return None

    print(
        "NOTINO PRODUCT ACCEPT:",
        name,
        "| PRICE:",
        price,
        "| URL:",
        final_url,
        flush=True,
    )

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": final_url,
    }


def _search_pages(session, query):
    urls = [
        BASE_URL + "/search.asp?exps=" + quote_plus(query),
        BASE_URL + "/search?query=" + quote_plus(query),
    ]

    for url in urls:
        try:
            response = session.get(
                url,
                headers=HEADERS,
                timeout=15,
                allow_redirects=True,
            )

            response.raise_for_status()

        except requests.RequestException as error:
            print("NOTINO SEARCH ERROR:", error, flush=True)
            continue

        if response.text:
            yield response.text


def search(query):
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    results = []
    seen = set()

    for html in _search_pages(session, query):

        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a", href=True):

            href = _clean(link.get("href"))

            if not href:
                continue

            product_url = urljoin(
                BASE_URL,
                href
            ).split("?")[0]

            if "notino.fr" not in product_url.lower():
                continue

            path = product_url.replace(
                BASE_URL,
                ""
            ).strip("/").lower()

            if not path:
                continue

            # Escludiamo pagine generiche.
            if any(
                bad in path
                for bad in (
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
                    "marques",
                    "parfums",
                )
            ):
                continue

            if product_url in seen:
                continue

            # Il link stesso deve identificare il prodotto.
            link_text = _clean(
                link.get("title")
                or link.get("aria-label")
                or link.get_text(" ", strip=True)
            )

            if not _matches(link_text, query):
                continue

            seen.add(product_url)

            print(
                "NOTINO FOUND PRODUCT URL:",
                product_url,
                "| LINK:",
                link_text,
                flush=True,
            )

            # QUI È LA CORREZIONE:
            # niente prezzo dalla pagina ricerca.
            # Apriamo la scheda prodotto.
            product = _extract_product(
                session,
                product_url,
                query,
            )

            if product:
                results.append(product)

            if len(results) >= 10:
                return results

        if results:
            return results

    return results


if __name__ == "__main__":
    print(search("Hawas Ice"))
