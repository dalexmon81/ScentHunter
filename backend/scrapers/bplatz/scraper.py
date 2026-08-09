import re
import time
import requests
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin

STORE = "Bplatz"
BASE = "https://en.bplatz.de"
CATALOG_URL = BASE + "/collections/produkte"
TIMEOUT = 4
MAX_PAGES = 20
PAGE_DELAY = 0.20

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

        if (
            "€" in text
            and (
                "Add to" in text
                or "Wishlist" in text
                or "retail price" in text.lower()
            )
        ):
            return parent

        node = parent

    return best

def _extract_page(html, query):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    has_products = False

    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"]).split("#")[0]
        path = href.lower()

        if "/products/" not in path:
            continue

        has_products = True

        name = " ".join(a.stripped_strings).strip()
        title = (a.get("title") or "").strip()

        card = _product_card(a)
        card_text = " ".join(card.stripped_strings).strip()

        img = card.find("img")
        img_alt = (img.get("alt") or "").strip() if img else ""

        candidates = [name, title, img_alt]
        product_name = next(
            (x for x in candidates if x and _match(x, query)),
            None,
        )

        if not product_name:
            for pa in card.find_all("a", href=True):
                txt = " ".join(pa.stripped_strings).strip()
                phref = urljoin(BASE, pa["href"])

                if (
                    "/products/" in phref.lower()
                    and txt
                    and _match(txt, query)
                ):
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

    return out, has_products

def search(query):
    query = str(query or "").strip()

    if not query:
        return []

    results = []
    seen_urls = set()

    with requests.Session() as session:
        session.headers.update(HEADERS)

        # PRIMARY: use Shopify's native product search.
        # This avoids depending on where a product happens to sit in the
        # generic catalogue pagination.
        try:
            response = session.get(
                BASE + "/search",
                params={"q": query, "type": "product"},
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            response = None

        if response is not None:
            status = response.status_code

            if status == 200:
                html = response.text
                response.close()

                page_results, _ = _extract_page(html, query)

                for item in page_results:
                    if item["url"] in seen_urls:
                        continue

                    seen_urls.add(item["url"])
                    results.append(item)
            else:
                response.close()

        # FALLBACK: keep the existing catalogue scan for stores/themes where
        # the native Shopify search is unavailable or returns no usable match.
        if not results:
            for page in range(1, MAX_PAGES + 1):
                try:
                    response = session.get(
                        CATALOG_URL,
                        params={"page": page},
                        timeout=TIMEOUT,
                        allow_redirects=True,
                    )
                except requests.RequestException:
                    break

                status = response.status_code

                if status in (403, 429):
                    response.close()
                    break

                if status != 200:
                    response.close()
                    break

                html = response.text
                response.close()

                page_results, has_products = _extract_page(html, query)

                for item in page_results:
                    if item["url"] in seen_urls:
                        continue

                    seen_urls.add(item["url"])
                    results.append(item)

                if not has_products:
                    break

                if page < MAX_PAGES:
                    time.sleep(PAGE_DELAY)

    results.sort(
        key=lambda x: (
            len(_norm(x["name"])),
            x["name"].lower(),
        )
    )

    return results[:20]

if __name__ == "__main__":
    for q in ("Rasasi Hawas", "Armaf Club de Nuit", "Riiffs"):
        print("\n" + "=" * 60)
        print("QUERY:", q)
        items = search(q)
        print("RISULTATI:", len(items))

        for item in items:
            print(item)
