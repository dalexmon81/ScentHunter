import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

STORE = "Bplatz"
BASE = "https://en.bplatz.de"
URL = BASE + "/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "en-US,en;q=0.9"
}

def _norm(v):
    v = str(v or "").lower()
    v = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", v)
    v = re.sub(r"[^a-z0-9]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()

def _match(a, b):
    return all(x in _norm(a) for x in _norm(b).split())

def _price(t):
    if not t:
        return None
    m = re.search(r"€\s*(\d{1,4}(?:[.,]\d{2})?)|(\d{1,4}(?:[.,]\d{2})?)\s*€", t)
    if not m:
        return None
    v = m.group(1) or m.group(2)
    return v.replace(".", ",") + "€"

def search(query):
    out = []
    seen_names = set()
    try:
        r = requests.get(URL, params={"s": query}, headers=HEADERS, timeout=12)
        r.raise_for_status()
    except requests.RequestException:
        return out

    soup = BeautifulSoup(r.text, "html.parser")

    for a in soup.find_all("a", href=True):
        name = " ".join(a.stripped_strings).strip()
        if not name or not _match(name, query):
            continue

        key = _norm(name)
        if key in seen_names:
            continue

        link = urljoin(BASE, a["href"])
        container = a
        price = None

        for _ in range(10):
            if container is None:
                break
            money = container.select_one(".hdt-money")
            if money:
                price = _price(money.get_text(" ", strip=True))
                if price:
                    break
            container = container.parent

        if not price:
            continue

        seen_names.add(key)
        out.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": link
        })

        if len(out) >= 10:
            break

    return out
