# name: Parfumzentrum_github.py
import re
import json
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote, urljoin

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


def _log(msg):
    print(f"PARFUMZENTRUM: {msg}")


def _tokens(text):
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(text or ""))
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
    r = SESSION.get(SITEMAP_URL, headers=HEADERS, timeout=6)

    if r.status_code in (403, 429):
        _log(f"SITEMAP BLOCKED: HTTP {r.status_code}")
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
            rr = SESSION.get(sm, headers=HEADERS, timeout=6)

            if rr.status_code in (403, 429):
                _log(f"SITEMAP CHILD BLOCKED: HTTP {rr.status_code} -> {sm}")
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


# Helper: normalize price-like string to format "xx,yy €"
def _extract_price_from_text(text):
    if not text:
        return None
    # Find euro amounts like 1.234,56 or 1234.56 or 1234,56 or 1234 € etc.
    m = re.search(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\s*€", text)
    if not m:
        return None
    val = m.group(1)
    # If both . and , present, assume dot thousand separator and comma decimal (e.g. 1.234,56)
    if "." in val and "," in val:
        val = val.replace(".", "")
    # Normalize decimal to comma
    val = val.replace(".", ",")
    # Ensure trailing space before euro symbol
    return val + " €"


# Helper: detect coupon indicators near a node
def _node_has_coupon_indicator(node):
    try:
        texts = []
        anc = node
        for _ in range(3):  # check node and up to 2 ancestors
            if anc is None:
                break
            texts.append(anc.get_text(" ", strip=True) or "")
            anc = getattr(anc, "parent", None)
        text = " ".join(texts).lower()
    except Exception:
        text = ""
    for kw in ("sale5de", "sale", "coupon", "code", "gutschein", "rabatt", "aktion", "promo", "voucher"):
        if kw in text:
            return True
    return False


# Helper: check if element or its ancestors indicate "old price" or "compare"
def _node_is_old_price(node):
    if node is None:
        return False
    # tag-based
    if node.name in ("del", "s", "strike"):
        return True
    # class-based heuristics
    cls = " ".join(node.get("class") or [])
    if cls and re.search(r"(old|was|strike|compare|cross|uvp|vorher|statt|list-price)", cls, re.I):
        return True
    # textual hints
    txt = (node.get_text(" ", strip=True) or "").lower()
    if any(k in txt for k in ("statt", "uvp", "vorher", "was", "original", "list price")):
        return True
    return False


def _extract_product(url, query):
    """
    Robust extraction for product page:
    - Extract product title (H1)
    - Verify token match against title
    - Extract prices using priority:
        1) JSON-LD offers.price
        2) itemprop="price"
        3) data-price / data-product-price etc.
        4) elements with class containing 'price' but excluding 'old/was/compare'
        5) fallback scanning near H1 excluding <del> and coupon-related nodes
    - Map prices to formats (30/50/100 ml) searching nodes that mention 'ml'
    """

    r = SESSION.get(url, headers=HEADERS, timeout=6)

    if r.status_code in (403, 429):
        _log(f"PRODUCT BLOCKED: HTTP {r.status_code} -> {url}")
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
        _log(f"NO_H1 -> {url}")
        return None

    name = " ".join(h1.stripped_strings).strip()

    if not _all_tokens_match(name, query):
        # try a looser match: allow compact substring match (to avoid false negatives on accents)
        compact_query = re.sub(r"[^0-9a-z]+", "", "".join(_tokens(query)))
        compact_title = re.sub(r"[^0-9a-z]+", "", name.lower())
        if not compact_query or compact_query not in compact_title:
            _log(f"TITLE_MISMATCH name={name!r} query={query!r}")
            return None

    # Build list of chunks near H1 for fallback scanning
    chunks = []
    node = h1
    for _ in range(8):
        if not node:
            break
        txt = node.get_text(" ", strip=True)
        if txt:
            chunks.append(txt)
        node = node.parent

    # 1) JSON-LD offers.price (highest priority)
    price = None
    price_source = None
    try:
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text(" ", strip=True)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if not isinstance(obj, dict):
                    continue
                offers = obj.get("offers")
                if isinstance(offers, dict):
                    offers = [offers]
                if isinstance(offers, list):
                    for offer in offers:
                        if isinstance(offer, dict):
                            candidate = offer.get("price") or (offer.get("priceSpecification") or {}).get("price")
                            if candidate:
                                p = _extract_price_from_text(str(candidate) + " €")
                                if p:
                                    price = p
                                    price_source = "json-ld"
                                    break
                    if price:
                        break
            if price:
                break
    except Exception:
        price = None

    # 2) itemprop="price"
    if not price:
        el = soup.find(attrs={"itemprop": "price"})
        if el:
            candidate = el.get("content") or el.get_text(" ", strip=True)
            p = _extract_price_from_text(candidate)
            if p:
                price = p
                price_source = "itemprop"

    # 3) data-price-like attributes
    if not price:
        for attr in ("data-price", "data-product-price", "data-final-price", "data-price-amount", "data-priceamount"):
            el = soup.find(attrs={attr: True})
            if el:
                candidate = el.get(attr) or el.get_text(" ", strip=True)
                p = _extract_price_from_text(candidate)
                if p and not _node_has_coupon_indicator(el) and not _node_is_old_price(el):
                    price = p
                    price_source = f"attr:{attr}"
                    break

    # 4) class-based price elements (prefer current price classes, exclude old/compare)
    if not price:
        # search for elements whose class suggests current price
        for el in soup.find_all(True):
            if el.name in ("del", "s", "strike"):
                continue
            cls = " ".join(el.get("class") or [])
            if not cls:
                continue
            # candidate classes for current price
            if re.search(r"(price|product-price|final-price|price--|price_now|price-current|price--now|price-normal)", cls, re.I):
                # skip if class indicates old price
                if re.search(r"(old|was|strike|compare|cross|uvp|vorher|statt)", cls, re.I):
                    continue
                txt = el.get("content") or el.get_text(" ", strip=True)
                if not txt or "€" not in txt:
                    continue
                if _node_has_coupon_indicator(el) or _node_is_old_price(el):
                    continue
                p = _extract_price_from_text(txt)
                if p:
                    price = p
                    price_source = f"class:{cls.split()[0] if cls.split() else 'price'}"
                    break

    # 5) fallback: scan chunks near H1 but FILTER OUT coupon/old price indicators and <del> fragments
    if not price:
        # prefer longer pieces to capture context
        for piece in sorted(chunks, key=len, reverse=True):
            if "€" not in piece:
                continue
            piece_low = piece.lower()
            # skip chunks mentioning coupon or promo codes
            if any(k in piece_low for k in ("sale5de", "coupon", "gutschein", "rabatt", "aktion", "promo", "code")):
                continue
            # prefer pieces that do NOT mention UVP, 'statt', 'vorher', 'was' which often indicate old price
            if any(k in piece_low for k in ("uvp", "statt", "vorher", "was", "original", "list price")):
                # still check if there's a later price in piece that's not preceded by these keywords;
                # but by default skip to avoid picking the struck price
                continue
            m = re.search(r"(\d{1,4}[.,]\d{2})\s*€", piece)
            if m:
                candidate_val = m.group(1)
                price = candidate_val.replace(".", ",") + " €"
                price_source = "fallback-text"
                break

    if not price:
        _log(f"NO_PRICE_FOUND url={url} title={name!r}")
        return None

    # Map formats (e.g., 50ml, 100ml) to prices where possible
    format_map = {}
    try:
        # find nodes that contain something like '100 ml' or '100ml'
        for text_node in soup.find_all(string=re.compile(r"\b\d{1,3}\s?ml\b", re.I)):
            # the text_node can be NavigableString; get parent to inspect
            parent = getattr(text_node, "parent", None)
            if parent is None:
                continue
            try_parents = [parent, getattr(parent, "parent", None), getattr(parent, "parent", None) and parent.parent.parent]
            found_price = None
            found_format = None
            for anc in try_parents:
                if anc is None:
                    continue
                # detect the format text
                fmt_match = re.search(r"(\d{1,3}\s?ml)", text_node, re.I)
                if fmt_match:
                    found_format = fmt_match.group(1).replace(" ", "")
                # look for price elements within this ancestor
                # prefer data-attributes / itemprop / class candidates
                # 1) itemprop inside anc
                el_price = anc.find(attrs={"itemprop": "price"})
                if el_price:
                    if not _node_is_old_price(el_price) and not _node_has_coupon_indicator(el_price):
                        p = _extract_price_from_text(el_price.get("content") or el_price.get_text(" ", strip=True))
                        if p:
                            found_price = p
                            break
                # 2) data-price attrs inside anc
                for attr in ("data-price", "data-product-price", "data-final-price", "data-price-amount", "data-priceamount"):
                    el = anc.find(attrs={attr: True})
                    if el:
                        if not _node_is_old_price(el) and not _node_has_coupon_indicator(el):
                            p = _extract_price_from_text(el.get(attr) or el.get_text(" ", strip=True))
                            if p:
                                found_price = p
                                break
                if found_price:
                    break
                # 3) class-based candidate inside anc
                for el in anc.find_all(True):
                    if el.name in ("del", "s", "strike"):
                        continue
                    cls = " ".join(el.get("class") or [])
                    if cls and re.search(r"(price|product-price|final-price|price--|price_now|price-current)", cls, re.I):
                        if _node_is_old_price(el) or _node_has_coupon_indicator(el):
                            continue
                        txt = el.get("content") or el.get_text(" ", strip=True)
                        if "€" in (txt or ""):
                            p = _extract_price_from_text(txt)
                            if p:
                                found_price = p
                                break
                if found_price:
                    break
                # 4) last resort: find any visible price string in anc but exclude del/old/coupon
                for el in anc.find_all(string=re.compile(r"\d{1,3}[.,]\d{2}\s*€")):
                    parent_of_price = getattr(el, "parent", None)
                    if parent_of_price and (_node_is_old_price(parent_of_price) or _node_has_coupon_indicator(parent_of_price)):
                        continue
                    # extract price
                    p = _extract_price_from_text(str(el))
                    if p:
                        found_price = p
                        break
                if found_price:
                    break
            if found_format and found_price:
                format_map[found_format] = found_price
    except Exception:
        pass

    # If format_map is empty, but we have a general price, we still return the general price,
    # but mapping per-format will be empty (caller can display general price or leave per-format empty).
    # Final assembly: prefer format-specific mapping for multi-format products.
    result = {
        "store": "ParfumZentrum",
        "name": name,
        "price": price,
        "url": url,
        "formats": format_map  # may be empty
    }

    _log(f"PARSED: name={name!r} price={price} source={price_source} formats={format_map}")
    return result


def search(query):
    try:
        urls = _get_sitemap_urls()
    except Exception as e:
        _log(f"ERRORE SITEMAP: {e}")
        return []

    candidates = []

    # Use sitemap urls to find likely product pages (contains '/produkt' or product structure)
    for url in urls:
        # simple heuristic: product pages often contain '/produkt' or '/product' or '/p/'
        if re.search(r"/product|/produkt|/produkte|/products|/p/", url, re.I):
            # optionally filter with token match on url to reduce checks
            if _all_tokens_match(url, query):
                candidates.append(url)

    # As a fallback, also include direct matches of pattern _z\d+ (as original)
    for url in urls:
        if re.search(r"_z\d+/?$", url) and _all_tokens_match(url, query):
            candidates.append(url)

    # Deduplicate candidates preserving order
    seen_urls = set()
    filtered_candidates = []
    for u in candidates:
        if u not in seen_urls:
            seen_urls.add(u)
            filtered_candidates.append(u)

    results = []
    seen = set()

    try:
        # limit number of product pages checked to avoid long runs
        for url in filtered_candidates[:20]:
            try:
                item = _extract_product(url, query)
            except Exception as e:
                _log(f"EXTRACT_ERROR url={url} err={e}")
                item = None

            if item:
                # For consistency with ScentHunter, choose per-format price if available
                # If formats mapping contains the exact format from query (e.g., '100ml'), use that price
                key = (item["name"].lower(), item["price"])
                if key not in seen:
                    seen.add(key)
                    results.append(item)
    finally:
        try:
            SESSION.close()
        except Exception:
            pass

    return results


if __name__ == "__main__":
    # Esempio rapido di test
    queries = [
        "Versace Eros pour Femme",
        "Rasasi Hawas For Him",
    ]
    for q in queries:
        _log(f"SEARCHING: {q}")
        res = search(q)
        _log(f"RISULTATI: {len(res)}")
        for it in res[:10]:
            print(it)
