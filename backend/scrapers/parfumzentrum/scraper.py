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

        value = str(value).replace("\xa0", " ").strip()
        m = re.search(r"\d{1,4}[.,]\d{2}", value)

        if not m:
            return ""

        return m.group(0).replace(".", ",") + "€"

    def _excluded_node(node):
        """True for old/list prices and code/coupon prices."""
        if not node:
            return True

        current = node
        for _ in range(6):
            if not current:
                break

            if getattr(current, "name", "") in {"del", "s", "strike"}:
                return True

            attrs = getattr(current, "attrs", {}) or {}
            blob = " ".join(
                str(attrs.get(key, ""))
                for key in ("class", "id", "data-testid", "data-test")
            ).lower()

            excluded_words = (
                "old-price", "old_price", "oldprice",
                "previous-price", "previous_price",
                "regular-price", "regular_price",
                "list-price", "list_price",
                "uvp", "strike", "strikethrough", "crossed",
                "code-price", "code_price", "rabattcode",
                "gutschein", "coupon", "discount-code",
            )

            if any(word in blob for word in excluded_words):
                return True

            text = current.get_text(" ", strip=True).lower()
            if "preis inkl. code" in text or "rabattcode" in text:
                return True

            current = current.parent

        return False

    def _candidate_score(node):
        """Higher score = more likely to be the actual selling price."""
        if _excluded_node(node):
            return -1000

        attrs = getattr(node, "attrs", {}) or {}
        blob = " ".join(
            str(attrs.get(key, ""))
            for key in ("class", "id", "data-testid", "data-test", "itemprop")
        ).lower()

        score = 0

        for word in (
            "current-price", "current_price", "currentprice",
            "product-price", "product_price", "productprice",
            "selling-price", "selling_price", "sellingprice",
            "sale-price", "sale_price", "saleprice",
            "price-current", "price_current",
        ):
            if word in blob:
                score += 100

        if "price" in blob:
            score += 20

        if "itemprop" in blob and "price" in blob:
            score += 40

        return score

    price = ""
    candidates = []

    # IMPORTANT: do not use JSON-LD as the first source. Some shops expose
    # the list/reference price there even when the visible selling price is lower.
    selectors = (
        '[itemprop="price"]',
        '[data-testid*="price"]',
        '[data-test*="price"]',
        '[data-price]',
        '[data-product-price]',
        '[class*="current-price"]',
        '[class*="product-price"]',
        '[class*="selling-price"]',
        '[class*="sale-price"]',
        '[class*="price-current"]',
        '[class*="price_current"]',
    )

    seen_nodes = set()

    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen_nodes:
                continue
            seen_nodes.add(marker)

            if _excluded_node(node):
                continue

            raw = (
                node.get("content")
                or node.get("data-price")
                or node.get("data-product-price")
                or node.get_text(" ", strip=True)
            )
            value = _normalize_price(raw)

            if value:
                candidates.append((_candidate_score(node), value))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        price = candidates[0][1]

    # Fallback specifically for the layout shown by ParfumZentrum:
    # current price is followed by a crossed/reference price such as
    # "53,92 € inkl. MwSt.". The reference price must never win.
    if not price:
        product_node = h1
        for _ in range(5):
            if product_node and product_node.parent:
                product_node = product_node.parent

        if product_node:
            work = BeautifulSoup(str(product_node), "html.parser")

            for bad in work.find_all(["del", "s", "strike"]):
                bad.decompose()

            for bad in work.find_all(
                class_=re.compile(
                    r"(old[-_ ]price|previous[-_ ]price|regular[-_ ]price|uvp|code[-_ ]price|rabattcode|gutschein|coupon)",
                    re.I,
                )
            ):
                bad.decompose()

            for text_node in work.find_all(string=True):
                parent = text_node.parent
                if parent and _excluded_node(parent):
                    text_node.extract()

            text = work.get_text(" ", strip=True)
            matches = re.findall(r"\d{1,4}[.,]\d{2}\s*€", text)

            if matches:
                price = _normalize_price(matches[0])

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
