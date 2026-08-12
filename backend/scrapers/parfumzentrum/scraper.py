import re
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote

BASE_URL = "https://www.parfum-zentrum.de"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

SESSION = requests.Session()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

IGNORED_MATCH_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "spray", "ml", "pour", "for",
    "woman", "man", "men", "women",
}


def _tokens(text: str):
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(text))
        if len(x) > 1
    ]


def _all_tokens_match(text: str, query: str) -> bool:
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


def _xml_urls(xml_text: str):
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


def _extract_number(text: str):
    m = re.search(r"(\d{1,4}[.,]\d{2})\s*€", text)
    if not m:
        return None
    return m.group(1).replace(".", ",")


def _has_strike(element) -> bool:
    node = element

    for _ in range(12):
        if node is None or not hasattr(node, "name"):
            break

        if node.name in ("s", "del", "strike"):
            return True

        style = (node.get("style", "") or "").replace(" ", "").lower()
        if "line-through" in style:
            return True

        classes = " ".join(node.get("class", []) or []).lower()
        if any(
            x in classes
            for x in (
                "strike",
                "strikethrough",
                "old-price",
                "oldprice",
                "list-price",
                "was-price",
                "crossed",
            )
        ):
            return True

        node = node.parent

    return False


def _nearest_size_ancestor(element):
    node = element

    for _ in range(10):
        if node is None or not hasattr(node, "get_text"):
            break

        text = node.get_text(" ", strip=True)
        sizes = list(
            dict.fromkeys(
                re.findall(r"(\d{1,4})\s*ml\b", text, re.I)
            )
        )

        if len(sizes) == 1:
            return node, sizes[0]

        node = node.parent

    return None, None


def _is_coupon_between(price_element, size_box) -> bool:
    node = price_element

    while node is not None:
        text = node.get_text(" ", strip=True).lower()

        if (
            "preis inkl. code" in text
            or "rabattcode" in text
            or "gutschein" in text
        ):
            return True

        if node is size_box:
            break

        node = node.parent

    return False


def _extract_variants(soup: BeautifulSoup):
    """
    Legge il prezzo dal nodo che contiene realmente il prezzo.
    Non usa il testo aggregato del contenitore, perché il contenitore
    può contenere sia il prezzo corrente sia quello barrato.
    """
    variants_by_size = {}

    price_nodes = soup.find_all(
        string=re.compile(r"\d{1,4}[.,]\d{2}\s*€")
    )

    for price_node in price_nodes:
        price_element = price_node.parent

        if _has_strike(price_element):
            continue

        price = _extract_number(str(price_node))
        if not price:
            continue

        size_box, size_ml = _nearest_size_ancestor(price_element)
        if not size_box or not size_ml:
            continue

        if _is_coupon_between(price_element, size_box):
            continue

        numeric_price = float(price.replace(",", "."))

        existing = variants_by_size.get(size_ml)

        if existing is None:
            variants_by_size[size_ml] = {
                "size_ml": size_ml,
                "price": price + "€",
            }
        else:
            existing_value = float(
                existing["price"]
                .replace("€", "")
                .replace(",", ".")
            )

            if numeric_price < existing_value:
                variants_by_size[size_ml] = {
                    "size_ml": size_ml,
                    "price": price + "€",
                }

    variants = list(variants_by_size.values())
    variants.sort(key=lambda x: int(x["size_ml"]))

    return variants


def _extract_product(url: str, query: str):
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

    unavailable_phrases = (
        "leider nicht lieferbar",
        "nicht lieferbar",
        "nicht vorrätig",
        "ausverkauft",
    )

    chunks = []
    node = h1

    for _ in range(8):
        if not node:
            break

        txt = node.get_text(" ", strip=True)

        if txt:
            chunks.append(txt)

        node = node.parent

    page_near_h1 = " ".join(chunks[:5]).lower()

    if any(x in page_near_h1 for x in unavailable_phrases):
        return None

    variants = _extract_variants(soup)

    if not variants:
        product_text = min(
            (
                x
                for x in chunks
                if len(x) >= len(name) and "€" in x
            ),
            key=len,
            default="",
        )

        price = ""

        for text_node in soup.find_all(
            string=re.compile(r"\d{1,4}[.,]\d{2}\s*€")
        ):
            parent = text_node.parent

            if _has_strike(parent):
                continue

            num = _extract_number(str(text_node))

            if num:
                price = num + "€"
                break

        if not price:
            patterns = [
                r"(\d{1,4}[.,]\d{2})\s*€\s*inkl\.",
                r"Versandbereit\s*(\d{1,4}[.,]\d{2})\s*€",
                r"(\d{1,4}[.,]\d{2})\s*€",
            ]

            for pattern in patterns:
                m = re.search(pattern, product_text, re.I)

                if m:
                    price = m.group(1).replace(".", ",") + "€"
                    break

        if not price:
            return None

        variants = [{"size_ml": None, "price": price}]

    main_variant = min(
        variants,
        key=lambda v: float(
            v["price"].split("€")[0].replace(",", ".")
        ),
    )

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": main_variant["price"],
        "url": url,
        "variants": variants,
    }


def search(query: str):
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
                key = (item["name"].lower(), item["url"])

                if key not in seen:
                    seen.add(key)
                    results.append(item)
    finally:
        SESSION.close()

    return results


if __name__ == "__main__":
    results = search("Versace Eros pour Femme Eau de Toilette")
    print("RISULTATI:", len(results))

    for item in results[:10]:
        print(item)
