import re
import requests
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin

STORE = "Bplatz"
BASE = "https://en.bplatz.de"
CATALOG_URL = BASE + "/collections/produkte"
TIMEOUT = 4

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def _norm(v):
    v = str(v or "").lower()
    v = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", v)
    v = re.sub(r"[^a-z0-9]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()

def _match(text, query):
    words = _norm(query).split()
    hay = _norm(text)
    return bool(words) and all(w in hay for w in words)

def _price(text):
    if not text:
        return None

    # Prefer "retail price", which is the actual selling price on Bplatz cards.
    patterns = [
        r"retail\s+price\s*€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"sale\s+price\s*€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"(\d{1,4}(?:[.,]\d{2})?)\s*€",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            value = m.group(1).replace(".", ",")
            try:
                if float(value.replace(",", ".")) <= 0:
                    continue
            except ValueError:
                continue
            return value + " €"
    return None

def _product_card(a):
    node = a
    best = a
    for _ in range(8):
        parent = node.parent
        if not isinstance(parent, Tag):
            break
        text = " ".join(parent.stripped_strings)
        if len(text) > 1500:
            break
        best = parent
        if "€" in text and ("Add to" in text or "Wishlist" in text or "retail price" in text.lower()):
            return parent
        node = parent
    return best

def _extract_page(html, query):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"]).split("#")[0]
        path = href.lower()

        # Bplatz is Shopify: real product URLs use /products/ (case-insensitive).
        if "/products/" not in path:
            continue

        name = " ".join(a.stripped_strings).strip()
        title = (a.get("title") or "").strip()

        card = _product_card(a)
        card_text = " ".join(card.stripped_strings).strip()

        # Product name can be in the anchor, title, image alt or card.
        img = card.find("img")
        img_alt = (img.get("alt") or "").strip() if img else ""

        candidates = [name, title, img_alt]
        product_name = next((x for x in candidates if x and _match(x, query)), None)

        if not product_name:
            # Find a nearby link in the same card whose text is the product title.
            for pa in card.find_all("a", href=True):
                txt = " ".join(pa.stripped_strings).strip()
                phref = urljoin(BASE, pa["href"])
                if "/products/" in phref.lower() and txt and _match(txt, query):
                    product_name = txt
                    href = phref.split("#")[0]
                    break

        if not product_name:
            continue

        price = _price(card_text)
        if not price:
            continue

        key = (href, _norm(product_name))
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "store": STORE,
            "name": product_name,
            "price": price,
            "url": href,
        })

    return out

def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    session = requests.Session()
    results = []
    seen_urls = set()

    # Important: the old scraper used homepage ?s=query.
    # Bplatz does not expose useful search results that way.
    # Its real catalogue is /collections/produkte.
    # Page 1 currently contains products such as Rasasi Hawas.
    for page in range(1, 31):
        try:
            r = session.get(
                CATALOG_URL,
                params={"page": page},
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            if r.status_code != 200:
                break
        except requests.RequestException:
            break

        page_results = _extract_page(r.text, query)

        for item in page_results:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            results.append(item)

        # For a specific perfume query, a few matches are enough.
        if results and len(_norm(query).split()) >= 2:
            break

        # Stop when Shopify returns an empty catalogue page.
        soup = BeautifulSoup(r.text, "html.parser")
        if not any("/products/" in urljoin(BASE, a.get("href", "")).lower()
                   for a in soup.find_all("a", href=True)):
            break

    results.sort(key=lambda x: (len(_norm(x["name"])), x["name"]))
    return results[:20]

if __name__ == "__main__":
    for q in ("Rasasi Hawas", "Armaf Club de Nuit", "Riiffs"):
        print("\n" + "=" * 60)
        print("QUERY:", q)
        items = search(q)
        print("RISULTATI:", len(items))
        for item in items:
            print(item)
