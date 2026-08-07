import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urlparse, parse_qs

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_PROXY = "https://www.google.com/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}

OUT_OF_STOCK_WORDS = (
    "rupture de stock",
    "en rupture",
    "épuisé",
    "epuise",
    "indisponible",
    "out of stock",
)

NON_PRODUCT_PATHS = (
    "/marques/",
    "/conseils/",
    "/article/",
    "/blog/",
    "/contact/",
)


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _norm(text):
    text = _clean(text).lower()
    text = re.sub(r"[^a-z0-9à-ÿ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_notino_url(href):
    href = href or ""

    # URL Notino diretto
    m = re.search(
        r"https?://(?:www\.)?notino\.fr/[^\s&\"']+",
        href,
        re.I,
    )
    if m:
        return m.group(0)

    # URL Google del tipo /url?q=https://www.notino.fr/...
    if href.startswith("/url?"):
        query = parse_qs(urlparse(href).query)
        target = (query.get("q") or query.get("url") or [""])[0]
        if "notino.fr/" in target:
            return target

    return ""


def _looks_like_product_url(url):
    if not url:
        return False

    low = url.lower()

    if any(path in low for path in NON_PRODUCT_PATHS):
        return False

    return "notino.fr/" in low


def _query_words(query):
    ignored = {
        "eau", "de", "parfum", "perfume", "edp", "edt",
        "spray", "ml", "pour", "homme", "femme",
    }

    return [
        word
        for word in _norm(query).split()
        if len(word) >= 2 and word not in ignored
    ]


def _matches_query(text, query):
    low = _norm(text)
    words = _query_words(query)

    if not words:
        return False

    return all(word in low for word in words)


def _extract_price(text):
    # Accetta 39,95 €, 39.95 €, 39,95€, ecc.
    matches = re.findall(
        r"(?<!\d)(\d{1,4}[,.]\d{2})\s*€",
        text or "",
    )

    if not matches:
        return ""

    # Evitiamo prezzi palesemente non realistici per un profumo.
    values = []

    for raw in matches:
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue

        if 5 <= value <= 2000:
            values.append((value, raw))

    if not values:
        return ""

    values.sort(key=lambda item: item[0])
    return values[0][1].replace(".", ",") + " €"


def _google_search(query):
    params = {
        "q": query,
        "num": 20,
        "filter": 0,
    }

    response = requests.get(
        SEARCH_PROXY,
        params=params,
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def search(query):
    query = _clean(query)

    if not query:
        return []

    # Facciamo più tentativi. Il secondo favorisce risultati che
    # espongono un prezzo nello snippet Google.
    search_queries = [
        f'site:notino.fr "{query}"',
        f'site:notino.fr "{query}" "€"',
    ]

    results = []
    seen = set()

    for google_query in search_queries:
        try:
            soup = _google_search(google_query)
        except requests.RequestException as error:
            print("NOTINO SEARCH ERROR:", error)
            continue

        # Usiamo i blocchi che contengono un titolo h3:
        # sono molto più affidabili dei generici "div".
        for title in soup.select("h3"):
            link_tag = title.find_parent("a", href=True)

            if not link_tag:
                continue

            url = _extract_notino_url(link_tag.get("href", ""))

            if not _looks_like_product_url(url):
                continue

            block = title

            # Risaliamo qualche livello per includere titolo, prezzo e snippet.
            for _ in range(4):
                parent = block.parent
                if parent is None:
                    break
                block = parent

            text = _clean(block.get_text(" ", strip=True))
            name = _clean(title.get_text(" ", strip=True))

            combined = f"{name} {text}"

            if not _matches_query(combined, query):
                continue

            low = combined.lower()

            # IMPORTANTE:
            # non restituiamo più a ScentHunter i risultati Google
            # esplicitamente marcati come esauriti. In questo modo
            # Notino non compare con una falsa "offerta".
            if any(word in low for word in OUT_OF_STOCK_WORDS):
                print("NOTINO SKIP OUT OF STOCK:", name, url)
                continue

            price = _extract_price(combined)

            # Senza prezzo non possiamo considerarlo un'offerta valida.
            if not price:
                print("NOTINO SKIP NO PRICE:", name, url)
                continue

            key = url.lower()

            if key in seen:
                continue

            seen.add(key)

            print(
                "NOTINO VALID OFFER:",
                name,
                "|",
                price,
                "|",
                url,
            )

            results.append({
                "store": STORE,
                "name": name or query,
                "price": price,
                "url": url,
                "available": True,
                "stock_status": "in_stock",
            })

            if len(results) >= 10:
                return results

    return results


if __name__ == "__main__":
    items = search("Rasasi Hawas Ice")
    print("RISULTATI:", len(items))

    for item in items:
        print(item)
