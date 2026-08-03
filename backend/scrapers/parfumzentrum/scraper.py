import re
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote

BASE_URL = "https://www.parfum-zentrum.de"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

def _tokens(text):
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(text))
        if len(x) > 1
    ]

def _all_tokens_match(text, query):
    low = unquote(text).lower().replace("-", " ")
    return all(t in low for t in _tokens(query))

def _xml_urls(xml_text):
    root = ET.fromstring(xml_text)
    return [
        el.text.strip()
        for el in root.iter()
        if el.tag.endswith("loc") and el.text
    ]

def _get_sitemap_urls():
    r = requests.get(SITEMAP_URL, headers=HEADERS, timeout=25)
    r.raise_for_status()
    urls = _xml_urls(r.text)

    # If sitemap.xml is an index, open its child sitemaps.
    child_maps = [u for u in urls if "sitemap" in u.lower() and u.lower().endswith((".xml", ".xml.gz"))]
    if not child_maps:
        return urls

    out = []
    for sm in child_maps:
        try:
            rr = requests.get(sm, headers=HEADERS, timeout=25)
            if rr.status_code == 200:
                out.extend(_xml_urls(rr.text))
        except Exception:
            pass
    return out

def _extract_product(url, query):
    r = requests.get(url, headers=HEADERS, timeout=25)
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None

    name = " ".join(h1.stripped_strings)
    if not _all_tokens_match(name, query):
        return None

    # Work only around the actual product heading, avoiding prices from
    # navigation/recommendations elsewhere on the page.
    chunks = []
    node = h1
    for _ in range(8):
        if not node:
            break
        txt = node.get_text(" ", strip=True)
        if txt:
            chunks.append(txt)
        node = node.parent

    product_text = min(
        (x for x in chunks if len(x) >= len(name) and "€" in x),
        key=len,
        default=""
    )

    # Parfum-Zentrum marks unavailable items with this message.
    unavailable_phrases = (
        "leider nicht lieferbar",
        "nicht lieferbar",
        "nicht vorrätig",
        "ausverkauft",
    )
    page_near_h1 = " ".join(chunks[:5]).lower()
    if any(x in page_near_h1 for x in unavailable_phrases):
        return None

    # Prefer a selling price followed by VAT/shipping text. This avoids
    # Grundpreis (price per litre) and recommendation prices.
    patterns = [
        r"(\d{1,4}[.,]\d{2})\s*€\s*inkl\.",
        r"Versandbereit\s*(\d{1,4}[.,]\d{2})\s*€",
        r"(\d{1,4}[.,]\d{2})\s*€",
    ]

    price = ""
    for pattern in patterns:
        m = re.search(pattern, product_text, re.I)
        if m:
            price = m.group(1).replace(".", ",") + "€"
            break

    if not price:
        return None

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": price,
        "url": url,
    }

def search(query):
    try:
        urls = _get_sitemap_urls()
    except Exception as e:
        print("ERRORE SITEMAP:", e)
        return []

    # Product pages use an article code in the slug: ..._z123456/
    candidates = []
    for url in urls:
        if re.search(r"_z\d+/?$", url) and _all_tokens_match(url, query):
            candidates.append(url)

    results = []
    seen = set()

    for url in candidates[:30]:
        try:
            item = _extract_product(url, query)
        except Exception:
            item = None

        if item:
            key = (item["name"].lower(), item["price"])
            if key not in seen:
                seen.add(key)
                results.append(item)

    return results

if __name__ == "__main__":
    # Available product used to verify the scraper.
    results = search("Rasasi Hawas For Him")
    print("RISULTATI:", len(results))
    for item in results[:10]:
        print(item)
