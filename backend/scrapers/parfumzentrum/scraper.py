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

    def _is_excluded(node):
        """Reject reference/list prices and coupon-price elements."""
        current = node
        for _ in range(6):
            if not current:
                break

            if getattr(current, "name", "") in {"del", "s", "strike"}:
                return True

            attrs = getattr(current, "attrs", {}) or {}
            blob = " ".join(
                str(attrs.get(k, ""))
                for k in ("class", "id", "data-testid", "data-test")
            ).lower()
            style = str(attrs.get("style", "")).lower()

            bad_words = (
                "old-price", "old_price", "oldprice",
                "previous-price", "previous_price",
                "regular-price", "regular_price", "list-price",
                "list_price", "uvp", "strike", "strikethrough",
                "crossed", "code-price", "code_price", "rabattcode",
                "gutschein", "coupon", "discount-code",
            )

            if any(word in blob for word in bad_words):
                return True

            if "line-through" in style or "linethrough" in style:
                return True

            current = current.parent

        return False

    def _price_score(node, value):
        """Score visible prices: current selling price beats reference data."""
        if _is_excluded(node):
            return -10000

        score = 0
        current = node

        for _ in range(5):
            if not current:
                break

            attrs = getattr(current, "attrs", {}) or {}
            blob = " ".join(
                str(attrs.get(k, ""))
                for k in ("class", "id", "data-testid", "data-test")
            ).lower()
            text = current.get_text(" ", strip=True).lower() if hasattr(current, "get_text") else ""

            if any(x in blob for x in ("current-price", "current_price", "sale-price", "sale_price", "selling-price", "selling_price", "product-price", "product_price")):
                score += 100
            elif "price" in blob:
                score += 20

            if "inkl. mwst." in text and "/l" not in text:
                score += 40

            if "grundpreis" in text or "/l" in text:
                score -= 80

            if "preis inkl. code" in text or "rabattcode" in text:
                score -= 100

            current = current.parent

        return score

    price = ""
    visible_candidates = []

    # IMPORTANT: the shop can expose the crossed/reference price through
    # itemprop or JSON-LD. Therefore visible, non-crossed prices are checked
    # FIRST. This is the critical fix for Parfum-Zentrum.
    for text_node in soup.find_all(string=re.compile(r"\d{1,4}[.,]\d{2}\s*€")):
        value = _normalize_price(text_node)
        if not value or _is_excluded(text_node.parent):
            continue
        visible_candidates.append((_price_score(text_node.parent, value), value))

    if visible_candidates:
        visible_candidates.sort(key=lambda x: x[0], reverse=True)
        price = visible_candidates[0][1]

    # Only if no safe visible selling price exists, inspect structured data.
    if not price:
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

    # Final structured/meta fallback.
    if not price:
        for node in soup.select(
            'meta[property="product:price:amount"], '
            'meta[name="price"], meta[itemprop="price"]'
        ):
            if _is_excluded(node):
                continue
            candidate = _normalize_price(node.get("content") or node.get_text(" ", strip=True))
            if candidate:
                price = candidate
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
