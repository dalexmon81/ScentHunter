import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin, urlparse

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

def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def _price(text):
    m = re.search(r"(?:de\s+)?(\d{1,4}[,.]\d{2})\s*€", text, re.I)
    return (m.group(1).replace(".", ",") + "€") if m else ""

def _clean_title(title):
    title = _clean(title)
    title = re.sub(
        r"^(?:livraison\s+offerte\s+)?(?:promo\s+)?cadeaux?\s+offerts?\s+",
        "",
        title,
        flags=re.I,
    )
    title = re.sub(r"^(?:promo|promotion)\s+", "", title, flags=re.I)
    title = re.sub(
        r"\s+\d[,.]\d\s*\(\s*\d+\s*\)\s+de\s+\d{1,4}[,.]\d{2}\s*€.*$",
        "",
        title,
        flags=re.I,
    )
    title = re.sub(
        r"\s+de\s+\d{1,4}[,.]\d{2}\s*€.*$",
        "",
        title,
        flags=re.I,
    )
    return _clean(title)

def _single_perfume(title):
    low = _clean(title).lower()
    blocked = (
        "coffret", "gift set", "set cadeau", "coffret cadeau",
        "miniature", "échantillon", "sample", "discovery set",
        "lot de ", "pack de ", "duo ", "trio ",
        "gel douche", "shower gel", "déodorant", "deodorant",
        "lotion corps", "body lotion", "crème corps", "body cream",
        "après-rasage", "after shave", "aftershave",
        "spray corps", "body spray", "brume", "hair mist",
    )
    return not any(x in low for x in blocked)

def _is_product_url(url, query):
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.netloc.lower() not in ("www.notino.fr", "notino.fr"):
        return False

    path = parsed.path.lower().rstrip("/")

    # Questi sono percorsi generici di Notino e NON sono prodotti.
    blocked = (
        "/search.asp", "/cart", "/wishlist", "/mynotino", "/livraison",
        "/avis", "/contact", "/magazine", "/marques", "/parfums",
        "/cosmetiques", "/cheveux", "/dentaire", "/homme", "/femme",
        "/offres-speciales", "/emballages-cadeaux",
    )

    if not path:
        return False

    if any(path == x or path.startswith(x + "/") for x in blocked):
        return False

    # Notino usa normalmente URL prodotto con /p-123456/.
    # Accettiamo SOLO questo formato quando ci sono 3 segmenti:
    # /marca/nome-prodotto/p-123456
    parts = [p for p in path.split("/") if p]

    if len(parts) == 3:
        if not re.fullmatch(r"p-\d+", parts[-1]):
            return False
        slug = "-".join(parts[:-1])
    elif len(parts) == 2:
        # Vecchio formato prodotto: /marca/nome-prodotto
        slug = "-".join(parts)
    else:
        return False

    # Evita pagine generiche: il prodotto deve contenere
    # almeno una parola significativa della query.
    words = [
        re.sub(r"[^a-z0-9]", "", w.lower())
        for w in query.split()
        if len(w) >= 3
    ]

    if not words:
        return False

    return any(w and w in slug for w in words)

def _direct(query):
    url = SEARCH_URL + quote_plus(query)

    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return []
    except requests.RequestException:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    words = [w.lower() for w in query.split() if len(w) >= 2]
    out, seen = [], set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not href:
            continue

        product_url = urljoin(BASE_URL, href)

        # FILTRO URL PRIMA di analizzare la card.
        if not _is_product_url(product_url, query):
            continue

        parent = a

        for _ in range(7):
            txt = _clean(parent.get_text(" ", strip=True))

            if "€" in txt or "rupture de stock" in txt.lower():
                break

            if parent.parent is None:
                break

            parent = parent.parent

        txt = _clean(parent.get_text(" ", strip=True))
        low = txt.lower()

        if words and not all(w in low for w in words):
            continue

        price = _price(txt)

        if not price and "rupture de stock" in low:
            price = "En rupture de stock"

        if not price:
            continue

        product_url = product_url.split("#")[0].split("?")[0].rstrip("/")

        if product_url in seen:
            continue

        title = _clean_title(a.get_text(" ", strip=True))

        if len(title) < 3:
            title = _clean_title(query)

        if not _single_perfume(title):
            continue

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
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        print("NOTINO FALLBACK ERROR:", e)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    words = [w.lower() for w in query.split() if len(w) >= 2]
    out, seen = [], set()

    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")

        if not a:
            continue

        href = a.get("href", "")
        title = _clean_title(a.get_text(" ", strip=True))
        snippet = _clean(li.get_text(" ", strip=True))
        low = (title + " " + snippet).lower()

        if not _is_product_url(href, query):
            continue

        if not _single_perfume(title):
            continue

        if words and not all(w in low for w in words):
            continue

        price = _price(snippet)

        if not price and "rupture de stock" in low:
            price = "En rupture de stock"

        if not price:
            continue

        href = href.split("#")[0].split("?")[0].rstrip("/")

        if href in seen:
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
    items = search("Liquid Brun")

    print("RISULTATI:", len(items))

    for item in items:
        print(item)
