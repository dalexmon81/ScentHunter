import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}

def _clean(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()

def _tokens(x):
    return [w for w in re.findall(r"[a-z0-9]+", x.lower()) if len(w) > 2]

def _matches(name, query):
    n = set(_tokens(name))
    return all(w in n for w in _tokens(query))

def _price(text):
    text = _clean(text)
    patterns = [
        r"€\s*(\d{1,4})[.,](\d{2})",
        r"(\d{1,4})[.,](\d{2})\s*€",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return f"{m.group(1)},{m.group(2)}€"
    return None

def search(query):
    query = _clean(query)
    if not query:
        return []

    s = requests.Session()
    s.headers.update(HEADERS)

    # Deloox espone un indice completo dei brand nella pagina prodotto/home.
    # Troviamo il brand dalla query e apriamo la sua pagina categoria.
    r = s.get(BASE_URL, timeout=8)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    qwords = _tokens(query)
    brand_link = None

    # Preferisci un link brand il cui testo è contenuto nella query.
    for a in soup.find_all("a", href=True):
        txt = _clean(a.get_text(" ", strip=True))
        if not txt:
            continue
        tw = _tokens(txt)
        if tw and all(w in qwords for w in tw):
            href = a["href"]
            if "categorie" in href.lower() or "category" in href.lower():
                brand_link = urljoin(BASE_URL, href)
                break

    # fallback specifico: ricerca link che contenga il primo token (es. Rasasi)
    if not brand_link and qwords:
        for a in soup.find_all("a", href=True):
            if qwords[0] in _clean(a.get_text()).lower():
                brand_link = urljoin(BASE_URL, a["href"])
                break

    if not brand_link:
        return []

    r = s.get(brand_link, timeout=8)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    results = []
    seen = set()

    # Le pagine categoria Deloox contengono link diretti /product/...html
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/product/" not in href or ".html" not in href:
            continue

        product_url = urljoin(BASE_URL, href)
        name = _clean(a.get_text(" ", strip=True) or a.get("title", ""))

        # Se il testo del link non contiene il nome completo, leggiamo il prodotto.
        if not name or not _matches(name, query):
            try:
                pr = s.get(product_url, timeout=8)
                if pr.status_code != 200:
                    continue
                ps = BeautifulSoup(pr.text, "html.parser")
                h1 = ps.find("h1")
                name = _clean(h1.get_text(" ", strip=True)) if h1 else name
                if not _matches(name, query):
                    continue
                price = _price(ps.get_text(" ", strip=True))
            except requests.RequestException:
                continue
        else:
            # Il contenitore della card di solito contiene anche il prezzo.
            parent = a
            for _ in range(5):
                if parent.parent:
                    parent = parent.parent
                p = _price(parent.get_text(" ", strip=True))
                if p:
                    break
            else:
                p = None
            price = p

            if not price:
                try:
                    pr = s.get(product_url, timeout=8)
                    ps = BeautifulSoup(pr.text, "html.parser")
                    price = _price(ps.get_text(" ", strip=True))
                except requests.RequestException:
                    price = None

        if not price:
            continue

        key = product_url.split("?")[0]
        if key in seen:
            continue
        seen.add(key)

        results.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": product_url,
        })

    return results

if __name__ == "__main__":
    print(search("Rasasi Hawas for Him"))
