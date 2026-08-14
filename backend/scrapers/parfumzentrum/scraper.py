import json
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
    "eau", "de", "the", "for", "and", "spray", "ml", "man", "woman",
    "men", "women", "herren", "damen",
}


def _tokens(text):
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(str(text or "")))
        if len(x) > 1
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
    wanted = {x for x in _tokens(query) if x not in STOPWORDS}

    if not wanted or not wanted.issubset(name_tokens):
        return False

    requested_concentration = _concentration(query)
    return (
        not requested_concentration
        or _concentration(name) == requested_concentration
    )


def _parse_price(value):
    if value is None:
        return None

    raw = str(value).strip().replace("\xa0", " ")
    raw = raw.replace("€", "").strip()

    # JSON-LD normally supplies a plain decimal number.
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        number = float(raw)
        return number if 0 < number < 10000 else None

    match = re.search(r"\d{1,5}(?:[.,]\d{2})", raw)
    if not match:
        return None

    number = match.group(0)

    if "," in number:
        if "." in number:
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", ".")
    elif number.count(".") > 1:
        number = number.replace(".", "")

    try:
        result = float(number)
    except ValueError:
        return None

    return result if 0 < result < 10000 else None


def _xml_urls(xml_text):
    root = ET.fromstring(xml_text)
    return [
        node.text.strip()
        for node in root.iter()
        if node.tag.endswith("loc") and node.text
    ]


def _get_sitemap_urls():
    response = SESSION.get(SITEMAP_URL, headers=HEADERS, timeout=10)
    response.raise_for_status()
    urls = _xml_urls(response.text)
    response.close()

    child_maps = [
        url for url in urls
        if "sitemap" in url.lower()
        and url.lower().endswith(".xml")
    ]

    if not child_maps:
        return urls

    output = []
    for sitemap in child_maps:
        try:
            child = SESSION.get(sitemap, headers=HEADERS, timeout=10)
            if child.status_code == 200:
                output.extend(_xml_urls(child.text))
            child.close()
        except requests.RequestException:
            continue

    return output


def _jsonld_offer_prices(soup):
    prices = []

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        queue = [data]
        while queue:
            item = queue.pop(0)

            if isinstance(item, list):
                queue.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            offers = item.get("offers")
            if isinstance(offers, dict):
                offers = [offers]

            if isinstance(offers, list):
                for offer in offers:
                    if not isinstance(offer, dict):
                        continue
                    price = _parse_price(offer.get("price"))
                    if price is not None:
                        prices.append(price)

            for value in item.values():
                if isinstance(value, (dict, list)):
                    queue.append(value)

    return prices


def _meta_price(soup):
    # These are product-level price fields, not arbitrary page text.
    selectors = [
        ('meta[property="product:price:amount"]', "content"),
        ('meta[itemprop="price"]', "content"),
        ('meta[name="price"]', "content"),
        ('[itemprop="price"]', "content"),
    ]

    for selector, attribute in selectors:
        for node in soup.select(selector):
            value = node.get(attribute) if node.has_attr(attribute) else node.get_text(" ", strip=True)
            price = _parse_price(value)
            if price is not None:
                return price

    return None


def _node_price(node):
    if node is None:
        return None

    # Prefer semantic price attributes.
    for attr in ("content", "data-price", "data-product-price", "value"):
        if node.has_attr(attr):
            price = _parse_price(node.get(attr))
            if price is not None:
                return price

    return _parse_price(node.get_text(" ", strip=True))


def _is_bad_price_context(node):
    current = node

    for _ in range(8):
        if current is None:
            break

        text = current.get_text(" ", strip=True).lower()
        marker = (
            " ".join(current.get("class", [])).lower()
            + " "
            + str(current.get("id", "")).lower()
        )

        if any(word in text for word in (
            "grundpreis", "pro liter", "per liter", "€/l",
            "preis inkl. code", "preis inkl code",
        )):
            return True

        if any(word in marker for word in (
            "coupon", "voucher", "gutschein", "rabattcode",
            "discount", "promo", "recommend", "related",
            "cross-sell", "upsell",
        )):
            return True

        current = current.parent

    return False


def _is_struck(node):
    if node.find_parent(["del", "s", "strike"]):
        return True

    current = node
    for _ in range(6):
        if current is None:
            break

        marker = (
            " ".join(current.get("class", [])).lower()
            + " "
            + str(current.get("id", "")).lower()
        )

        if any(word in marker for word in (
            "old-price", "old_price", "regular-price", "list-price",
            "list_price", "strike", "strikethrough", "was-price",
            "compare-price", "crossed",
        )):
            return True

        current = current.parent

    return False


def _visible_product_price(soup):
    """
    Last-resort visible-price extraction.

    It is deliberately restricted to semantic product-price elements and
    their immediate product/purchase containers. It never scans arbitrary
    page text for the first euro amount.
    """
    selectors = [
        '[itemprop="price"]',
        '[data-price]',
        '[data-product-price]',
        '.product-price',
        '.product_price',
        '.price--current',
        '.price-current',
        '.current-price',
        '.current_price',
        '.final-price',
        '.final_price',
        '.sale-price',
        '.sale_price',
    ]

    candidates = []

    for selector in selectors:
        for node in soup.select(selector):
            if _is_struck(node) or _is_bad_price_context(node):
                continue

            price = _node_price(node)
            if price is None:
                continue

            score = 0
            marker = (
                " ".join(node.get("class", [])).lower()
                + " "
                + str(node.get("id", "")).lower()
            )
            if "product" in marker:
                score += 20
            if "current" in marker or "final" in marker or "sale" in marker:
                score += 15

            parent_text = ""
            if node.parent:
                parent_text = node.parent.get_text(" ", strip=True).lower()

            if "in den warenkorb" in parent_text:
                score += 40
            if "inkl. mwst" in parent_text:
                score += 10

            candidates.append((score, price))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return candidates[0][1]


def _extract_price(soup):
    # 1. Product structured data is the strongest generic source.
    structured = _jsonld_offer_prices(soup)
    if structured:
        return structured[0]

    # 2. Product meta/semantic price.
    meta = _meta_price(soup)
    if meta is not None:
        return meta

    # 3. Semantic visible product-price elements.
    return _visible_product_price(soup)


def _extract_product(url, query):
    try:
        response = SESSION.get(url, headers=HEADERS, timeout=10)
    except requests.RequestException:
        return None

    if response.status_code != 200:
        response.close()
        return None

    html = response.text
    response.close()

    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    if not h1:
        return None

    name = " ".join(h1.stripped_strings)

    if not _matches_query(name, query):
        return None

    size_match = re.search(
        r"(?<!\d)(\d{1,4}(?:[.,]\d+)?)\s*ml\b",
        name,
        re.I,
    )
    size_ml = None
    if size_match:
        try:
            size_ml = float(size_match.group(1).replace(",", "."))
        except ValueError:
            pass

    concentration = ""
    if re.search(r"\beau\s+de\s+toilette\b|\bedt\b", name, re.I):
        concentration = "Eau de Toilette"
    elif re.search(r"\beau\s+de\s+parfum\b|\bedp\b", name, re.I):
        concentration = "Eau de Parfum"
    elif re.search(r"\bextrait(?:\s+de\s+parfum)?\b", name, re.I):
        concentration = "Extrait de Parfum"

    page_text = soup.get_text(" ", strip=True).lower()
    if any(x in page_text for x in (
        "nicht lieferbar", "nicht vorrätig", "ausverkauft",
    )):
        return None

    price = _extract_price(soup)
    if price is None:
        return None

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": f"{price:.2f}€",
        "url": url,
        "size_ml": size_ml,
        "concentration": concentration,
    }


def _candidate_score(url, query):
    query_tokens = [
        token for token in _tokens(query)
        if token not in STOPWORDS
    ]
    url_tokens = _tokens(url)

    score = sum(10 for token in query_tokens if token in url_tokens)

    if query_tokens and all(token in url_tokens for token in query_tokens):
        score += 30

    requested = _concentration(query)
    if requested == "edt" and ("toilette" in url_tokens or "edt" in url_tokens):
        score += 40
    elif requested == "edp" and ("parfum" in url_tokens or "edp" in url_tokens):
        score += 40
    elif requested == "extrait" and "extrait" in url_tokens:
        score += 40

    return score


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
        and _matches_query(url, query)
    ]

    candidates.sort(
        key=lambda url: _candidate_score(url, query),
        reverse=True,
    )

    results = []
    seen = set()

    for url in candidates[:24]:
        try:
            item = _extract_product(url, query)
        except Exception as error:
            print("PARFUMZENTRUM PRODUCT ERROR:", repr(error))
            item = None

        if not item:
            continue

        key = (
            item["name"].lower(),
            item["price"],
            item["size_ml"],
        )

        if key in seen:
            continue

        seen.add(key)
        results.append(item)

    SESSION.close()
    return results
