
# TEST DIAGNOSTICO 2 — NON È UNA CORREZIONE DELLO SCRAPER
# Serve solo a vedere cosa contiene realmente la pagina di ricerca Sabina
# e perché i 190 link presenti non vengono trasformati in parsed_rows.

import re
import sys
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
TIMEOUT = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/it/",
}

PRODUCT_URL_RE = re.compile(
    r"^https?://(?:www\.)?sabina\.com/(?:it|fr|en|es|de|pt)/"
    r"(?!content|ricerca|ricerca_old|marchi|negozi|contatto|faq|"
    r"carrello|ordine|stato-ordine|il-mio-conto|module)",
    re.I,
)

PRICE_RE = re.compile(
    r"(?:€|\$|£)\s*(\d{1,4}(?:[.,]\d{2}))|"
    r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*(?:€|\$|£)",
    re.I,
)

def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()

q = " ".join(sys.argv[1:]).strip() or "Liquid brun"
url = BASE + "/it/ricerca_old?s=" + quote_plus(q)

print("SABINA_TEST2 query:", q)
print("SABINA_TEST2 url:", url)

try:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    print("SABINA_TEST2 response:", r.status_code, r.url, r.headers.get("content-type"), len(r.content))
    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    links = soup.find_all("a", href=True)
    print("SABINA_TEST2 total_links:", len(links))

    candidates = []
    product_url_count = 0
    ancestor_price_count = 0

    for a in links:
        href = urljoin(BASE, a.get("href", ""))
        if not PRODUCT_URL_RE.match(href):
            continue

        product_url_count += 1
        label = clean(a.get("title") or a.get("aria-label") or a.get_text(" ", strip=True))

        container = a
        price_found = False
        price_container_level = None
        container_text = ""

        for level in range(8):
            parent = getattr(container, "parent", None)
            if not parent:
                break
            container = parent
            container_text = clean(container.get_text(" ", strip=True))
            if PRICE_RE.search(container_text):
                price_found = True
                price_container_level = level + 1
                ancestor_price_count += 1
                break

        if len(candidates) < 30:
            candidates.append({
                "href": href,
                "label": label[:180],
                "price_found": price_found,
                "price_level": price_container_level,
                "text": container_text[:500],
                "class": " ".join(container.get("class", [])) if hasattr(container, "get") else "",
                "tag": getattr(container, "name", ""),
            })

    print("SABINA_TEST2 product_url_matches:", product_url_count)
    print("SABINA_TEST2 product_urls_with_ancestor_price:", ancestor_price_count)
    print("SABINA_TEST2 SAMPLE_START")

    for i, c in enumerate(candidates, 1):
        print(f"SABINA_TEST2 LINK {i}")
        print("  href:", c["href"])
        print("  label:", c["label"])
        print("  price_found:", c["price_found"], "level:", c["price_level"])
        print("  container_tag:", c["tag"], "class:", c["class"])
        print("  container_text:", c["text"])

    print("SABINA_TEST2 SAMPLE_END")

    # Cerca anche pattern comuni nei link/classi per capire la struttura reale.
    for term in ("product", "item", "price", "product-name", "product-title", "name"):
        print(f"SABINA_TEST2 html_term_{term}:", html.lower().count(term))

except Exception as e:
    print("SABINA_TEST2 ERROR:", type(e).__name__, str(e))
