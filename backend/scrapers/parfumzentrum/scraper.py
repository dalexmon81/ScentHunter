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

STOPWORDS = {
    "eau", "de", "the", "for", "and", "spray", "ml",
    "man", "woman", "men", "women", "herren", "damen",
}


def _tokens(text):
    return [
        token.lower()
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(str(text or "")))
        if len(token) > 1
    ]


def _concentration(text):
    value = unquote(str(text or ""))
    if re.search(r"\beau\s+de\s+toilette\b|\bedt\b", value, re.I):
        return "edt"
    if re.search(r"\beau\s+de\s+parfum\b|\bedp\b", value, re.I):
        return "edp"
    if re.search(r"\bextrait(?:\s+de\s+parfum)?\b", value, re.I):
        return "extrait"
    return ""


def _matches_query(name, query):
    name_tokens = set(_tokens(name))
    wanted = {token for token in _tokens(query) if token not in STOPWORDS}

    if not wanted:
        return False

    # A product page must contain every meaningful query token.
    # This is deliberately generic: no brand/product names and no exceptions.
    if not wanted.issubset(name_tokens):
        return False

    requested = _concentration(query)
    return not requested or _concentration(name) == requested


def _parse_price(value):
    raw = str(value or "").strip().replace("\xa0", " ")
    raw = raw.replace("€", "").strip()

    match = re.search(r"\d{1,5}(?:[.,]\d{2})", raw)
    if not match:
        return None

    number = match.group(0)

    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    elif number.count(".") > 1:
        number = number.replace(".", "")

    try:
        price = float(number)
    except ValueError:
        return None

    return price if 0 < price < 10000 else None


def _xml_urls(xml_text):
    root = ET.fromstring(xml_text)
    return [
        node.text.strip()
        for node in root.iter()
        if node.tag.endswith("loc") and node.text
    ]


def _get_sitemap_urls():
    response = SESSION.get(SITEMAP_URL, headers=HEADERS, timeout=15)
    response.raise_for_status()
    urls = _xml_urls(response.text)
    response.close()

    children = [
        url for url in urls
        if "sitemap" in url.lower() and url.lower().endswith(".xml")
    ]

    if not children:
        return urls

    result = []
    for sitemap in children:
        try:
            response = SESSION.get(sitemap, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                result.extend(_xml_urls(response.text))
            response.close()
        except requests.RequestException:
            continue

    return result


def _query_terms(query):
    return {
        token
        for token in _tokens(query)
        if token not in STOPWORDS
    }


def _url_matches_query(url, query):
    wanted = _query_terms(query)
    if not wanted:
        return False

    url_tokens = set(_tokens(url))

    # Discovery is now strict instead of "any token".
    # This prevents generic words such as "le" or "beau" from filling
    # the candidate pool and pushing relevant variants out of the limit.
    return wanted.issubset(url_tokens)


def _candidate_score(url, query):
    wanted = _query_terms(query)
    url_tokens = set(_tokens(url))

    return (
        len(wanted.intersection(url_tokens)),
        -len(url_tokens),
    )


def _product_header_text(soup):
    h1 = soup.find("h1")
    if not h1:
        return ""

    container = h1
    best = h1

    for _ in range(6):
        if container is None:
            break

        text = container.get_text(" ", strip=True)
        low = text.lower()

        if "produktbeschreibung" in low or "in den warenkorb" in low:
            best = container
            break

        if len(text) < 12000:
            best = container

        container = container.parent

    text = best.get_text(" ", strip=True)

    marker = text.lower().find("produktbeschreibung")
    if marker >= 0:
        text = text[:marker]

    return text


def _size_from_name(name):
    match = re.search(
        r"(?<!\d)(\d{1,4}(?:[.,]\d+)?)\s*ml\b",
        name,
        re.I,
    )
    if not match:
        return None

    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _is_old_or_non_purchase_node(node):
    if node.name in {"del", "s", "strike"}:
        return True

    marker = (
        " ".join(node.get("class", [])).lower()
        + " "
        + str(node.get("id", "")).lower()
    )

    return any(word in marker for word in (
        "old-price", "old_price", "compare-price", "compare_price",
        "list-price", "list_price", "regular-price", "regular_price",
        "coupon", "voucher", "gutschein", "rabattcode",
        "discount", "promo", "grundpreis", "base-price", "base_price",
    ))


def _local_price_for_size(soup, size_ml):
    if size_ml is None:
        return None

    size_text = str(int(size_ml)) if float(size_ml).is_integer() else str(size_ml)
    size_re = re.compile(
        rf"(?<![\d.,]){re.escape(size_text)}\s*ml\b",
        re.I,
    )
    price_re = re.compile(r"(?<![\d.,])(\d{1,5}(?:[.,]\d{2}))\s*€")

    # Look at the smallest useful DOM block containing the requested size.
    # Prices inside del/s/old-price blocks are explicitly excluded.
    for text_node in soup.find_all(string=size_re):
        node = text_node.parent

        for _ in range(5):
            if node is None:
                break

            local_text = node.get_text(" ", strip=True)
            if len(local_text) > 1200:
                node = node.parent
                continue

            if size_re.search(local_text):
                prices = []

                for price_node in node.find_all(string=price_re):
                    parent = price_node.parent
                    if _is_old_or_non_purchase_node(parent):
                        continue

                    # Exclude Grundpreis/coupon text locally.
                    context = node.get_text(" ", strip=True).lower()
                    if "grundpreis" in context and "warenkorb" not in context:
                        # Keep searching upward for the actual purchase block.
                        pass

                    match = price_re.search(str(price_node))
                    if match:
                        value = _parse_price(match.group(1))
                        if value is not None:
                            prices.append(value)

                if prices:
                    # In a normal variant card the first non-barrato price
                    # is the active selling price.
                    return prices[0]

            node = node.parent

    return None


def _fallback_single_price(soup, size_ml):
    header = _product_header_text(soup)

    if size_ml is not None:
        match = re.search(
            rf"(?<![\d.,]){re.escape(str(int(size_ml)))}\s*ml\b"
            rf".{{0,160}}?(\d{{1,5}}(?:[.,]\d{{2}}))\s*€",
            header,
            re.I,
        )
        if match:
            return _parse_price(match.group(1))

    before_base = re.split(r"\bgrundpreis\b", header, maxsplit=1, flags=re.I)[0]

    for match in re.finditer(
        r"(?<![\d.,])(\d{1,5}(?:[.,]\d{2}))\s*€",
        before_base,
    ):
        value = _parse_price(match.group(1))
        if value is not None:
            return value

    return None


def _extract_product(url, query):
    try:
        response = SESSION.get(url, headers=HEADERS, timeout=15)
    except requests.RequestException:
        return None

    if response.status_code != 200:
        response.close()
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    response.close()

    h1 = soup.find("h1")
    if not h1:
        return None

    name = " ".join(h1.stripped_strings)

    if not _matches_query(name, query):
        return None

    size_ml = _size_from_name(name)

    concentration = ""
    concentration_code = _concentration(name)
    if concentration_code == "edt":
        concentration = "Eau de Toilette"
    elif concentration_code == "edp":
        concentration = "Eau de Parfum"
    elif concentration_code == "extrait":
        concentration = "Extrait de Parfum"

    price = _local_price_for_size(soup, size_ml)

    if price is None:
        price = _fallback_single_price(soup, size_ml)

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": f"{price:.2f}€" if price is not None else None,
        "url": url,
        "size_ml": size_ml,
        "concentration": concentration,
    }


def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    try:
        urls = _get_sitemap_urls()
    except Exception as error:
        print("PARFUMZENTRUM SITEMAP ERROR:", error)
        return []

    candidates = [
        url for url in urls
        if re.search(r"_z\d+/?$", url)
        and _url_matches_query(url, query)
    ]

    candidates.sort(
        key=lambda url: _candidate_score(url, query),
        reverse=True,
    )

    results = []
    seen = set()

    # The old logic used "any distinctive token" and then [:40].
    # That was the reason broad searches lost valid variants.
    for url in candidates[:100]:
        try:
            item = _extract_product(url, query)
        except Exception as error:
            print("PARFUMZENTRUM PRODUCT ERROR:", repr(error))
            item = None

        if not item:
            continue

        key = (
            item["name"].lower(),
            item["size_ml"],
            item["concentration"].lower(),
        )

        if key in seen:
            continue

        seen.add(key)
        results.append(item)

    SESSION.close()
    return results
