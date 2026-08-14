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
        if "." in number:
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", ".")
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


def _url_matches_query(url, query):
    url_tokens = set(_tokens(url))
    wanted = {x for x in _tokens(query) if x not in STOPWORDS}

    # Sitemap slugs are a discovery hint only. Require at least the
    # distinctive non-generic query terms, but do not require every word:
    # store slugs can omit brand words or reorder them.
    distinctive = {
        token for token in wanted
        if token not in {"jean", "paul", "gaultier", "eau", "toilette", "parfum"}
    }

    if distinctive:
        return any(token in url_tokens for token in distinctive)

    return bool(wanted.intersection(url_tokens))


def _product_header_text(soup):
    h1 = soup.find("h1")
    if not h1:
        return ""

    # The important product block is between the H1 and the product
    # description. This keeps unrelated recommendation/footer prices out.
    container = h1.parent
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

    if "produktbeschreibung" in text.lower():
        text = text[:text.lower().find("produktbeschreibung")]

    return text


def _price_for_size_from_header(header_text, size_ml):
    """
    ParfumZentrum exposes the available size/price pairs in the product
    header, e.g. '125 ml 67,95 € 75 ml 50,95 €', followed by the active
    price and Grundpreis.

    We use the size/price pair belonging to the page's own size. This is
    generic and works for any product with multiple bottle sizes.
    """
    if size_ml is None:
        return None

    number = re.escape(str(int(size_ml))) if float(size_ml).is_integer() else re.escape(str(size_ml).replace(".", ","))

    pattern = re.compile(
        rf"(?<![\d.,]){number}\s*ml\s+"
        rf"(\d{{1,5}}(?:[.,]\d{{2}}))\s*€",
        re.I,
    )

    match = pattern.search(header_text)
    if match:
        return _parse_price(match.group(1))

    # Alternate order used by some themes: price then size.
    reverse = re.compile(
        rf"(\d{{1,5}}(?:[.,]\d{{2}}))\s*€\s*"
        rf"{number}\s*ml",
        re.I,
    )
    match = reverse.search(header_text)
    if match:
        return _parse_price(match.group(1))

    return None


def _active_price_from_header(header_text, size_ml):
    # First and strongest source: the size/price pair.
    price = _price_for_size_from_header(header_text, size_ml)
    if price is not None:
        return price

    # Fallback only when the page exposes a single size. We take the first
    # purchase-price-looking amount before Grundpreis, never a crossed price.
    before_base = re.split(
        r"\bgrundpreis\b",
        header_text,
        maxsplit=1,
        flags=re.I,
    )[0]

    candidates = []
    for match in re.finditer(r"(?<![\d.,])(\d{1,5}(?:[.,]\d{2}))\s*€", before_base):
        value = _parse_price(match.group(1))
        if value is None:
            continue

        context = before_base[max(0, match.start()-80):match.end()+30].lower()
        if "code" in context or "coupon" in context:
            continue

        candidates.append(value)

    return candidates[-1] if candidates else None


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

    size_match = re.search(
        r"(?<!\d)(\d{1,4}(?:[.,]\d+)?)\s*ml\b",
        name,
        re.I,
    )
    size_ml = None
    if size_match:
        size_ml = float(size_match.group(1).replace(",", "."))

    concentration = ""
    if _concentration(name) == "edt":
        concentration = "Eau de Toilette"
    elif _concentration(name) == "edp":
        concentration = "Eau de Parfum"
    elif _concentration(name) == "extrait":
        concentration = "Extrait de Parfum"

    header = _product_header_text(soup)
    price = _active_price_from_header(header, size_ml)

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": f"{price:.2f}€" if price is not None else None,
        "url": url,
        "size_ml": size_ml,
        "concentration": concentration,
    }


def _candidate_score(url, query):
    query_tokens = {
        x for x in _tokens(query)
        if x not in STOPWORDS
    }
    url_tokens = set(_tokens(url))
    return sum(10 for token in query_tokens if token in url_tokens)


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

    for url in candidates[:40]:
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
