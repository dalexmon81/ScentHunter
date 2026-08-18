import json
import re
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.nl"
SEARCH_PATH = "/zoeken.html"
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

PRODUCT_RE = re.compile(
    r"/product/(\d+)/",
    re.I,
)

IGNORED_QUERY_WORDS = {
    "eau",
    "de",
    "parfum",
    "perfume",
    "edp",
    "edt",
    "extrait",
    "spray",
    "for",
    "by",
}

NON_PRODUCT_TERMS = {
    "gift set",
    "set regalo",
    "coffret",
    "bundle",
    "deodorant",
    "deo spray",
    "shower gel",
    "body lotion",
    "after shave",
    "aftershave",
    "travel set",
    "discovery set",
    "kit",
    "body mist",
    "handcreme",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    value = value.lower()

    value = re.sub(
        r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)",
        " ",
        value,
    )

    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def same_host(url):
    try:
        host = urlparse(url).netloc.lower()
        return host == "deloox.nl" or host.endswith(".deloox.nl")
    except Exception:
        return False


def product_url(url):
    return PRODUCT_RE.search(url or "") is not None


def query_tokens(query):
    return [
        token
        for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS
    ]


def explicit_size(query):
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*ml\b",
        norm(query),
        re.I,
    )
    if not match:
        return None

    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None

    return int(value) if value.is_integer() else value


def extract_size_ml(*texts):
    combined = " ".join(str(value or "") for value in texts)

    matches = re.findall(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*ml\b",
        combined,
        re.I,
    )

    for value in matches:
        try:
            number = float(value.replace(",", "."))
        except ValueError:
            continue

        return int(number) if number.is_integer() else number

    return None


def extract_concentration(*texts):
    value = norm(" ".join(str(x or "") for x in texts))

    rules = (
        ("Extrait de Parfum", r"\bextrait de parfum\b"),
        ("Eau de Parfum", r"\beau de parfum\b"),
        ("Eau de Toilette", r"\beau de toilette\b"),
        ("Eau de Cologne", r"\beau de cologne\b"),
        ("Parfum", r"\bparfum\b"),
    )

    for label, pattern in rules:
        if re.search(pattern, value, re.I):
            return label

    return None


def extract_gender(*texts):
    value = norm(" ".join(str(x or "") for x in texts))

    if re.search(
        r"\b(men|male|heren|homme|pour homme)\b",
        value,
        re.I,
    ):
        return "men"

    if re.search(
        r"\b(women|female|dames|femme|pour femme)\b",
        value,
        re.I,
    ):
        return "women"

    if "unisex" in value or "unisexe" in value:
        return "unisex"

    return "unknown"


def extract_price(soup, json_ld=None):
    candidates = []

    if isinstance(json_ld, dict):
        offers = json_ld.get("offers")

        if isinstance(offers, dict):
            candidates.append(offers.get("price"))

        elif isinstance(offers, list):
            for offer in offers:
                if isinstance(offer, dict):
                    candidates.append(offer.get("price"))

    for selector in (
        'meta[itemprop="price"]',
        'meta[property="product:price:amount"]',
        '[data-price]',
    ):
        for node in soup.select(selector):
            candidates.append(
                node.get("content")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )

    text = soup.get_text(" ", strip=True)

    # Generic fallback for the site's visible euro price.
    for match in re.finditer(
        r"(?:€\s*)?(\d{1,4}[.,]\d{2})(?:\s*€)?",
        text,
    ):
        try:
            number = float(match.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            continue

        if 0 < number < 10000:
            candidates.append(number)

    for value in candidates:
        if value in (None, ""):
            continue

        try:
            number = float(
                str(value)
                .replace("€", "")
                .replace(" ", "")
                .replace(",", ".")
            )
        except ValueError:
            continue

        if 0 < number < 10000:
            return round(number, 2)

    return None


def extract_json_ld(soup):
    objects = []

    for script in soup.find_all(
        "script",
        attrs={"type": re.compile(r"application/ld\+json", re.I)},
    ):
        raw = script.string or script.get_text()
        raw = raw.strip()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue

        if isinstance(data, list):
            objects.extend(
                item for item in data
                if isinstance(item, dict)
            )
        elif isinstance(data, dict):
            objects.append(data)

    for data in objects:
        if str(data.get("@type", "")).lower() == "product":
            return data

    return None


def visible_product_name(soup, json_ld=None):
    if isinstance(json_ld, dict):
        name = clean(json_ld.get("name"))
        if name:
            return name

    for selector in (
        "h1",
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
    ):
        node = soup.select_one(selector)

        if node:
            value = (
                node.get("content")
                if node.name == "meta"
                else node.get_text(" ", strip=True)
            )

            value = clean(value)

            if value:
                return value

    if soup.title:
        return clean(soup.title.get_text(" ", strip=True))

    return ""


def visible_brand(soup, json_ld=None):
    if isinstance(json_ld, dict):
        brand = json_ld.get("brand")

        if isinstance(brand, dict):
            brand = brand.get("name")

        brand = clean(brand)

        if brand:
            return brand

    return ""


def query_matches_product(
    name,
    query,
    brand="",
    size_ml=None,
    url="",
):
    name_n = norm(name)
    brand_n = norm(brand)
    query_n = norm(query)

    if not name_n or not query_n:
        return False

    # A product URL must be a real Deloox product URL.
    if not product_url(url):
        return False

    # Every meaningful query token must be present in the product identity.
    tokens = query_tokens(query)

    if not tokens:
        return False

    identity = norm(" ".join((name, brand)))

    if not all(token in identity for token in tokens):
        return False

    # Explicit size requests must match the product size when available.
    requested_size = explicit_size(query)

    if requested_size is not None and size_ml is not None:
        if float(requested_size) != float(size_ml):
            return False

    # Generic packaging/product-type protection.
    name_only = norm(name)

    for phrase in NON_PRODUCT_TERMS:
        if norm(phrase) in name_only and norm(phrase) not in query_n:
            return False

    return True


def extract_search_candidates(soup, page_url):
    candidates = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))

        if not href:
            continue

        url = urljoin(page_url, href).split("#", 1)[0]

        if not same_host(url) or not product_url(url):
            continue

        url = url.split("?", 1)[0]

        if url in seen:
            continue

        seen.add(url)

        text = clean(
            anchor.get("title")
            or anchor.get("aria-label")
            or anchor.get_text(" ", strip=True)
        )

        # Search result cards sometimes keep the product name in an
        # image alt/title even when the anchor text is mostly price.
        image = anchor.find("img")
        if image:
            text = clean(
                " ".join(
                    value
                    for value in (
                        text,
                        image.get("alt"),
                        image.get("title"),
                    )
                    if value
                )
            )

        candidates.append(
            {
                "url": url,
                "text": text,
            }
        )

    return candidates


def fetch(session, url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if not response.ok:
            return None

        if not same_host(response.url):
            return None

        return response

    except requests.RequestException:
        return None


def parse_product_page(response, query):
    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    json_ld = extract_json_ld(soup)

    name = visible_product_name(
        soup,
        json_ld,
    )

    brand = visible_brand(
        soup,
        json_ld,
    )

    text = soup.get_text(
        " ",
        strip=True,
    )

    size_ml = extract_size_ml(
        name,
        text,
    )

    concentration = extract_concentration(
        name,
        text,
    )

    gender = extract_gender(
        name,
        text,
    )

    price = extract_price(
        soup,
        json_ld,
    )

    availability = "unknown"

    if isinstance(json_ld, dict):
        offers = json_ld.get("offers")

        if isinstance(offers, dict):
            availability_value = norm(
                offers.get("availability")
            )

            if "instock" in availability_value:
                availability = "in_stock"
            elif "outofstock" in availability_value:
                availability = "out_of_stock"

    if not availability:
        availability = "unknown"

    url = response.url.split("?", 1)[0]

    if not query_matches_product(
        name,
        query,
        brand=brand,
        size_ml=size_ml,
        url=url,
    ):
        return None

    image = ""

    if isinstance(json_ld, dict):
        image_value = json_ld.get("image")

        if isinstance(image_value, list):
            image = clean(image_value[0]) if image_value else ""
        else:
            image = clean(image_value)

    if not image:
        node = soup.select_one(
            'meta[property="og:image"]'
        )

        if node:
            image = clean(node.get("content"))

    product_id_match = PRODUCT_RE.search(url)
    product_id = (
        product_id_match.group(1)
        if product_id_match
        else None
    )

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand or None,
            "url": url,
            "image": image or None,
        },
        "identity": {
            "gtin": None,
            "mpn": None,
            "sku": None,
            "store_product_id": product_id,
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {
                "value": size_ml,
                "source": "product_page",
            },
            "concentration": {
                "value": concentration,
                "source": "product_page",
            },
            "gender": {
                "value": gender,
                "source": "product_page",
            },
            "packaging_type": {
                "value": "product",
                "source": "default",
            },
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": availability,
        },
        "provenance": {
            "source_page": url,
            "name_source": "product_page",
            "brand_source": "product_page",
            "price_source": "product_page",
            "product_source": "product_page",
        },
        "raw_data": {
            "name": name,
            "brand": brand,
            "size_ml": size_ml,
            "concentration": concentration,
            "gender": gender,
        },

        # Backward-compatible fields used by the current backend/frontend.
        "name": name,
        "price": (
            f"{price:.2f}".replace(".", ",") + " €"
            if price is not None
            else ""
        ),
        "url": url,
        "image": image,
        "available": availability == "in_stock",
    }


def search(query):
    query = clean(query)

    if not query:
        return []

    session = requests.Session()

    try:
        # The site's own search form is /zoeken.html?q=...
        # We deliberately do not crawl categories or generic internal links.
        response = fetch(
            session,
            urljoin(BASE_URL, SEARCH_PATH),
            params={"q": query},
        )

        if response is None:
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        candidates = extract_search_candidates(
            soup,
            response.url,
        )

        results = []
        seen = set()

        # The search page is the only discovery source.
        # Each discovered product is validated on its own product page.
        for candidate in candidates:
            url = candidate["url"]

            if url in seen:
                continue

            seen.add(url)

            product_response = fetch(
                session,
                url,
            )

            if product_response is None:
                continue

            product = parse_product_page(
                product_response,
                query,
            )

            if product is None:
                continue

            key = (
                product["url"].lower(),
                norm(product["name"]),
            )

            if key in seen:
                continue

            seen.add(key)
            results.append(product)

        return results

    except Exception:
        return []

    finally:
        session.close()


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
