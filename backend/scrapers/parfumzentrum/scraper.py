import re
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

    def _is_old_price(node):
        for _ in range(8):
            if not node:
                break
            attrs = (" ".join(node.get("class", [])) + " " + str(node.get("id", ""))).lower() if getattr(node, "attrs", None) is not None else ""
            if node.name in {"del", "s", "strike"}:
                return True
            if any(x in attrs for x in (
                "old-price", "oldprice", "previous-price", "reference-price",
                "regular-price", "uvp", "durchgestrichen", "was-price", "compare-price"
            )):
                return True
            node = node.parent
        return False

    price_matches = []
    price_re = re.compile(r"(\d{1,4}[.,]\d{2})\s*€")

    for node in soup.find_all(string=price_re):
        if _is_old_price(node.parent):
            continue

        raw = str(node)
        m = price_re.search(raw)
        if not m:
            continue

        # Ignore unit prices such as 809,80 €/l.
        after = raw[m.end():].lstrip()
        if after.startswith("/"):
            continue

        score = 0
        context = ""
        parent = node.parent
        for _ in range(5):
            if not parent:
                break
            context += " " + parent.get_text(" ", strip=True)
            parent = parent.parent

        context_low = context.lower()
        if "preis inkl. code" in context_low or "inkl. code" in context_low:
            score += 100
        if "inkl. mwst." in context_low:
            score += 50
        if "versandbereit" in context_low:
            score += 20

        price_matches.append((score, m.group(1).replace(".", ",") + "€"))

    if price_matches:
        # Highest score wins; for equal scores the later price in the DOM wins.
        price = sorted(enumerate(price_matches), key=lambda x: (x[1][0], x[0]))[-1][1][1]
    else:
        # Last fallback: use the last price tied to the product text, never the
        # first one. This avoids the common crossed-out/reference-price case.
        matches = list(re.finditer(r"(\d{1,4}[.,]\d{2})\s*€", product_text, re.I))
        price = matches[-1].group(1).replace(".", ",") + "€" if matches else ""

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
