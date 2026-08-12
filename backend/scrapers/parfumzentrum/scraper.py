import re
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote

BASE_URL = "https://www.parfum-zentrum.de"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

REQUEST_TIMEOUT = 4
MAX_CANDIDATES = 8

SESSION = requests.Session()

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
    r = SESSION.get(SITEMAP_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    urls = _xml_urls(r.text)

    # If sitemap.xml is an index, open its child sitemaps.
    child_maps = [u for u in urls if "sitemap" in u.lower() and u.lower().endswith((".xml", ".xml.gz"))]
    if not child_maps:
        return urls

    out = []
    for sm in child_maps:
        try:
            rr = SESSION.get(sm, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if rr.status_code == 200:
                out.extend(_xml_urls(rr.text))
        except Exception:
            pass
    return out

def _extract_product(url, query):
    r = SESSION.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
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

    # IMPORTANT: Parfum-Zentrum can show an old/list price and the real
    # selling price in the same product block. Never let the first generic
    # "XX,XX € inkl." match win when a current selling price is available.
    # The storefront commonly labels the live price with "Versandbereit".
    price_patterns = [
        r"Versandbereit\s*(\d{1,4}[.,]\d{2})\s*€",
        r"(?:sale|special|current|final|aktionspreis|angebotspreis|sonderpreis)[^0-9]{0,80}(\d{1,4}[.,]\d{2})\s*€",
    ]

    price = ""
    for pattern in price_patterns:
        m = re.search(pattern, product_text, re.I)
        if m:
            price = m.group(1).replace(".", ",") + "€"
            break

    # Prefer structured product data when the visible selling-price label was
    # not found. This is safer than taking the first euro amount in the page.
    if not price:
        def _walk_json(obj):
            if isinstance(obj, dict):
                yield obj
                for value in obj.values():
                    yield from _walk_json(value)
            elif isinstance(obj, list):
                for value in obj:
                    yield from _walk_json(value)

        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text(" ", strip=True)
            if not raw:
                continue
            try:
                data = __import__("json").loads(raw)
            except Exception:
                continue
            for obj in _walk_json(data):
                offers = obj.get("offers") if isinstance(obj, dict) else None
                offer_list = offers if isinstance(offers, list) else [offers]
                for offer in offer_list:
                    if not isinstance(offer, dict):
                        continue
                    raw_price = offer.get("price")
                    if raw_price is None:
                        continue
                    m = re.search(r"(\d{1,4}(?:[.,]\d{2})?)", str(raw_price))
                    if m:
                        price = m.group(1).replace(".", ",") + "€"
                        break
                if price:
                    break
            if price:
                break

    # Final fallback: use the last selling-looking euro amount in the
    # product block, not the first one (which may be the crossed/list price).
    if not price:
        amounts = re.findall(r"(\d{1,4}[.,]\d{2})\s*€", product_text)
        if amounts:
            price = amounts[-1].replace(".", ",") + "€"

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

    for url in candidates[:MAX_CANDIDATES]:
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
