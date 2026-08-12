import re
import json
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote

BASE_URL = "https://www.parfum-zentrum.de"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

SESSION = requests.Session()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

IGNORED_MATCH_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "spray", "ml", "pour", "for",
}

def _tokens(text):
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(text))
        if len(x) > 1
    ]

def _all_tokens_match(text, query):
    text_tokens = set(_tokens(text))
    query_tokens = {
        token
        for token in _tokens(query)
        if token not in IGNORED_MATCH_WORDS
    }

    if not query_tokens:
        query_tokens = set(_tokens(query))

    if not query_tokens:
        return False

    return query_tokens.issubset(text_tokens)

def _xml_urls(xml_text):
    root = ET.fromstring(xml_text)
    return [
        el.text.strip()
        for el in root.iter()
        if el.tag.endswith("loc") and el.text
    ]

def _get_sitemap_urls():
    r = SESSION.get(SITEMAP_URL, headers=HEADERS, timeout=4)

    if r.status_code in (403, 429):
        print(f"PARFUMZENTRUM BLOCKED: HTTP {r.status_code}")
        r.close()
        return []

    r.raise_for_status()
    xml_text = r.text
    r.close()
    urls = _xml_urls(xml_text)

    child_maps = [
        u for u in urls
        if "sitemap" in u.lower()
        and u.lower().endswith((".xml", ".xml.gz"))
    ]

    if not child_maps:
        return urls

    out = []

    for sm in child_maps:
        try:
            rr = SESSION.get(sm, headers=HEADERS, timeout=4)

            if rr.status_code in (403, 429):
                print(f"PARFUMZENTRUM SITEMAP BLOCKED: HTTP {rr.status_code}")
                rr.close()
                break

            if rr.status_code == 200:
                xml_text = rr.text
                rr.close()
                out.extend(_xml_urls(xml_text))
            else:
                rr.close()
        except Exception:
            pass

    return out

def _extract_product(url, query):
    r = SESSION.get(url, headers=HEADERS, timeout=4)

    if r.status_code in (403, 429):
        print(f"PARFUMZENTRUM PRODUCT BLOCKED: HTTP {r.status_code}")
        r.close()
        return None

    if r.status_code != 200:
        r.close()
        return None

    html = r.text
    r.close()

    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")

    if not h1:
        return None

    name = " ".join(h1.stripped_strings)

    if not _all_tokens_match(name, query):
        return None

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

    unavailable_phrases = (
        "leider nicht lieferbar",
        "nicht lieferbar",
        "nicht vorrätig",
        "ausverkauft",
    )

    page_near_h1 = " ".join(chunks[:5]).lower()

    if any(x in page_near_h1 for x in unavailable_phrases):
        return None

    def _normalize_price(value):
        if value is None:
            return ""
        value = str(value).strip().replace("\xa0", " ")
        m = re.search(r"(\d{1,4}(?:[.,]\d{2})?)", value)
        if not m:
            return ""
        return m.group(1).replace(".", ",") + "€"

    # 1) FIRST CHOICE: JSON-LD Product/Offer price.
    #    This is the selling price of the requested product page.
    #    Parfum-Zentrum can keep the old/crossed price in visible
    #    price nodes, so those must not win over the structured offer.
    price = ""

    for script in soup.select('script[type="application/ld+json"]'):
        raw_json = script.string or script.get_text()
        try:
            data = json.loads(raw_json)
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            obj = stack.pop()

            if isinstance(obj, list):
                stack.extend(obj)
                continue

            if not isinstance(obj, dict):
                continue

            offers = obj.get("offers")
            if isinstance(offers, dict):
                stack.append(offers)
            elif isinstance(offers, list):
                stack.extend(offers)

            if "price" in obj:
                candidate = _normalize_price(obj.get("price"))
                if candidate:
                    price = candidate
                    break

        if price:
            break

    # 2) Visible selling price. We deliberately do NOT use
    #    "Preis inkl. Code": that is a coupon price, not the normal
    #    shop price shown by ScentHunter.
    if not price:
        m = re.search(
            r"(\d{1,4}[.,]\d{2})\s*€\s*inkl\.\s*MwSt\.",
            product_text,
            re.I,
        )
        if m:
            price = _normalize_price(m.group(1))

    # 3) Explicit price nodes, only after the two safer methods above.
    if not price:
        price_nodes = soup.select(
            '[itemprop="price"], '
            'meta[property="product:price:amount"], '
            'meta[name="price"], '
            'meta[itemprop="price"]'
        )

        for node in price_nodes:
            raw = node.get("content") or node.get_text(" ", strip=True)
            candidate = _normalize_price(raw)
            if candidate:
                price = candidate
                break

    if not price:
        # Last fallback: collect only visible prices that are not inside
        # crossed-out/reference-price elements and use the first one.
        visible_prices = []
        for node in soup.find_all(string=re.compile(r"\d{1,4}[.,]\d{2}\s*€")):
            parent = node.parent
            if parent and parent.name in {"del", "s", "strike"}:
                continue
            candidate = _normalize_price(node)
            if candidate:
                visible_prices.append(candidate)

        if visible_prices:
            price = visible_prices[0]

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

    candidates = []

    for url in urls:
        if re.search(r"_z\d+/?$", url) and _all_tokens_match(url, query):
            candidates.append(url)

    results = []
    seen = set()

    try:
        for url in candidates[:6]:
            try:
                item = _extract_product(url, query)
            except Exception:
                item = None

            if item:
                key = (item["name"].lower(), item["price"])

                if key not in seen:
                    seen.add(key)
                    results.append(item)
    finally:
        SESSION.close()

    return results

if __name__ == "__main__":
    results = search("Rasasi Hawas For Him")
    print("RISULTATI:", len(results))

    for item in results[:10]:
        print(item)
