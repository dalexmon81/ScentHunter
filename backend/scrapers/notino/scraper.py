import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin, urlparse

STORE = "Notino"
BASE_URL = "https://www.notino.fr/"
SEARCH_URL = "https://www.notino.fr/search.asp?exps="

# Questo scraper prova prima Notino direttamente.
# Se Notino blocca l'IP di GitHub Codespaces con 403,
# usa la copia testuale indicizzata da Bing per recuperare
# nome/prezzo/link Notino senza inventare risultati.
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
    # 24,70€ / 24,70 € / de 34,10€
    m = re.search(r"(?:de\s+)?(\d{1,4}[,.]\d{2})\s*€", text, re.I)
    return (m.group(1).replace(".", ",") + "€") if m else ""



def _is_product_url(url, query):
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.netloc not in ("www.notino.fr", "notino.fr"):
        return False
    path = parsed.path.lower().rstrip("/")
    blocked = (
        "/search.asp", "/cart", "/wishlist", "/mynotino", "/livraison",
        "/avis", "/contact", "/magazine", "/marques", "/parfums",
        "/cosmetiques", "/cheveux", "/dentaire", "/homme", "/femme"
    )
    if not path or any(path == x or path.startswith(x + "/") for x in blocked):
        return False
    parts = [p for p in path.split("/") if p]
    # Le schede prodotto Notino hanno normalmente almeno 2 segmenti:
    # /marca/slug-prodotto/
    if len(parts) != 2:
        return False
    slug = "-".join(parts)
    words = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in query.split() if len(w) >= 3]
    return bool(words) and sum(1 for w in words if w and w in slug) >= min(2, len(words))

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

        product_url = urljoin(BASE_URL, href)
        if not _is_product_url(product_url, query) or product_url in seen:
            continue

        title = _clean(a.get_text(" ", strip=True))
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
    # Bing HTML è accessibile da molti datacenter dove Notino restituisce 403.
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
        title = _clean(a.get_text(" ", strip=True))
        snippet = _clean(li.get_text(" ", strip=True))
        low = (title + " " + snippet).lower()

        if not _is_product_url(href, query):
            continue
        if words and not all(w in low for w in words):
            continue

        price = _price(snippet)
        if not price and "rupture de stock" in low:
            price = "En rupture de stock"
        if not price:
            continue

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
    items = search("Rasasi Hawas Ice")
    print("RISULTATI:", len(items))
    for item in items:
        print(item)
