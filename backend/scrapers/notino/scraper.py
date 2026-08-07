import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

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
    "rupture de stock",
    "en rupture",
    "indisponible",
    "temporairement indisponible",
    "épuisé",
    "epuise",
    "out of stock",
)


def _clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _price(text):
    m = re.search(
        r"(?:de\s+)?(\d{1,4}[,.]\d{2})\s*€",
        _clean(text),
        re.I,
    )
    return (m.group(1).replace(".", ",") + "€") if m else ""


def _is_out_of_stock(text):
    low = _clean(text).lower()
    return any(marker in low for marker in OUT_OF_STOCK)


def _valid_product_url(url):
    low = _clean(url).lower()

    if not low.startswith("https://www.notino.fr/"):
        return False

    blocked = (
        "/search.asp",
        "/panier",
        "/cart",
        "/wishlist",
        "/mynotino",
        "/livraison",
        "/contact",
        "/conditions",
        "/magazine",
    )

    return not any(part in low for part in blocked)


def _product_available(product_url):
    try:
        r = requests.get(
            product_url,
            headers=HEADERS,
            timeout=8,
            allow_redirects=True,
        )

        if r.status_code != 200:
            return None

        text = _clean(
            BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        )

        if _is_out_of_stock(text):
            return False

        return True

    except requests.RequestException:
        return None


def _direct(query):
    url = SEARCH_URL + quote_plus(query)

    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=12,
            allow_redirects=True,
        )

        if r.status_code != 200:
            return []

    except requests.RequestException:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    words = [w.lower() for w in query.split() if len(w) >= 2]

    out = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = _clean(a.get("href"))

        if not href:
            continue

        product_url = urljoin(BASE_URL, href)

        if not _valid_product_url(product_url):
            continue

        if product_url in seen:
            continue

        parent = a

        for _ in range(7):
            txt = _clean(parent.get_text(" ", strip=True))

            if "€" in txt or _is_out_of_stock(txt):
                break

            if parent.parent is None:
                break

            parent = parent.parent

        txt = _clean(parent.get_text(" ", strip=True))
        low = txt.lower()

        if words and not all(w in low for w in words):
            continue

        if _is_out_of_stock(txt):
            continue

        price = _price(txt)

        if not price:
            continue

        availability = _product_available(product_url)

        if availability is False:
            continue

        title = _clean(
            a.get("title")
            or a.get("aria-label")
            or a.get_text(" ", strip=True)
        )

        if len(title) < 3:
            title = query

        seen.add(product_url)

        out.append({
            "store": STORE,
            "name": title,
            "price": price,
            "url": product_url,
        })

        if len(out) >= 10:
            break

    return out


def _bing(query):
    q = f'site:notino.fr "{query}"'
    url = "https://www.bing.com/search?q=" + quote_plus(q)

    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()

    except requests.RequestException as e:
        print("NOTINO FALLBACK ERROR:", e)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    words = [w.lower() for w in query.split() if len(w) >= 2]

    out = []
    seen = set()

    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")

        if not a:
            continue

        href = _clean(a.get("href"))
        title = _clean(a.get_text(" ", strip=True))
        snippet = _clean(li.get_text(" ", strip=True))
        low = (title + " " + snippet).lower()

        if not _valid_product_url(href):
            continue

        if words and not all(w in low for w in words):
            continue

        if _is_out_of_stock(low):
            continue

        price = _price(snippet)

        if not price:
            continue

        if href in seen:
            continue

        availability = _product_available(href)

        if availability is not True:
            continue

        seen.add(href)

        out.append({
            "store": STORE,
            "name": title,
            "price": price,
            "url": href,
        })

        if len(out) >= 10:
            break

    return out


def search(query):
    query = _clean(query)

    if not query:
        return []

    results = _direct(query)

    if results:
        return results

    return _bing(query)


if __name__ == "__main__":
    items = search("Rasasi Hawas Ice")
    print("RISULTATI:", len(items))

    for item in items:
        print(item)
