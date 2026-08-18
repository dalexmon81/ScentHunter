import json
import re
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_PATH = "/search.asp"
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

PRODUCT_ID_RE = re.compile(r"/p-(\d+)/?(?:$|[?#])", re.I)

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
    "brume parfumee",
    "brume parfumée",
}

IGNORED_QUERY_WORDS = {
    "eau",
    "de",
    "parfum",
    "perfume",
    "edp",
    "edt",
    "extrait",
    "spray",
    "pour",
    "homme",
    "femme",
    "mixte",
    "men",
    "women",
    "for",
    "by",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def same_host(url):
    try:
        host = urlparse(url).netloc.lower()
        return host == "notino.fr" or host.endswith(".notino.fr")
    except Exception:
        return False


def explicit_size(query):
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*ml\b", norm(query), re.I)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def extract_size_ml(*texts):
    combined = " ".join(str(value or "") for value in texts)
    for value in re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*ml\b", combined, re.I):
        try:
            number = float(value.replace(",", "."))
        except ValueError:
            continue
        return int(number) if number.is_integer() else number
    return None


def extract_concentration(*texts):
    rules = (
        ("Extrait de Parfum", r"\bextrait de parfum\b|\bextrait\b"),
        ("Eau de Parfum", r"\beau de parfum\b"),
        ("Eau de Toilette", r"\beau de toilette\b"),
        ("Eau de Cologne", r"\beau de cologne\b"),
        ("Parfum", r"\bparfum\b"),
    )
    for text in texts:
        value = norm(text)
        if not value:
            continue
        for label, pattern in rules:
            if re.search(pattern, value, re.I):
                return label
    return None


def extract_gender(*texts):
    value = norm(" ".join(str(x or "") for x in texts))
    if re.search(r"\b(homme|men|male|pour homme)\b", value, re.I):
        return "men"
    if re.search(r"\b(femme|women|female|pour femme)\b", value, re.I):
        return "women"
    if re.search(r"\b(mixte|unisex|unisexe)\b", value, re.I):
        return "unisex"
    return "unknown"


def parse_price_value(value):
    if value in (None, ""):
        return None
    text = clean(value).replace("€", "").replace("\u00a0", " ").strip()
    text = re.sub(r"[^0-9,.]", "", text)
    if not text:
        return None
    # French prices are normally 25,50. Avoid treating 1.234,56 as 1.23.
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return round(number, 2) if 0 < number < 10000 else None


def extract_price(soup, json_ld=None):
    candidates = []

    if isinstance(json_ld, dict):
        offers = json_ld.get("offers")
        if isinstance(offers, dict):
            candidates.extend((offers.get("price"), offers.get("lowPrice")))
        elif isinstance(offers, list):
            for offer in offers:
                if isinstance(offer, dict):
                    candidates.extend((offer.get("price"), offer.get("lowPrice")))

    for selector in (
        'meta[itemprop="price"]',
        'meta[property="product:price:amount"]',
        '[data-price]',
        '[data-testid*="price" i]',
    ):
        for node in soup.select(selector):
            candidates.append(
                node.get("content")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )

    for value in candidates:
        parsed = parse_price_value(value)
        if parsed is not None:
            return parsed

    # Last generic fallback: use euro amounts from the product page, preferring
    # values near the purchase/price area rather than arbitrary review numbers.
    for node in soup.select("[class*='price' i], [id*='price' i], [data-price]"):
        parsed = parse_price_value(node.get_text(" ", strip=True))
        if parsed is not None:
            return parsed

    return None


def extract_json_ld_objects(soup):
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
            objects.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            objects.append(data)
    return objects


def extract_product_json_ld(soup):
    for data in extract_json_ld_objects(soup):
        data_type = data.get("@type")
        types = data_type if isinstance(data_type, list) else [data_type]
        if any(str(value).lower() == "product" for value in types):
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
        if not node:
            continue
        value = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
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

    for selector in (
        '[itemprop="brand"]',
        '[data-testid*="brand" i]',
    ):
        node = soup.select_one(selector)
        if node:
            value = clean(node.get("content") or node.get_text(" ", strip=True))
            if value:
                return value
    return ""


def visible_image(soup, json_ld=None):
    if isinstance(json_ld, dict):
        value = json_ld.get("image")
        if isinstance(value, list):
            for item in value:
                if clean(item):
                    return clean(item)
        elif clean(value):
            return clean(value)

    for selector in (
        'meta[property="og:image"]',
        'meta[name="twitter:image"]',
        'link[rel="image_src"]',
    ):
        node = soup.select_one(selector)
        if node:
            value = clean(node.get("content") or node.get("href"))
            if value:
                return urljoin(BASE_URL, value)

    return ""


def extract_sku(json_ld=None, soup=None):
    if isinstance(json_ld, dict):
        for key in ("sku", "mpn", "gtin", "gtin13", "gtin12", "gtin14"):
            value = clean(json_ld.get(key))
            if value:
                return key, value
    if soup is not None:
        for selector in (
            '[itemprop="sku"]',
            '[itemprop="gtin13"]',
            '[itemprop="gtin"]',
        ):
            node = soup.select_one(selector)
            if node:
                value = clean(node.get("content") or node.get_text(" ", strip=True))
                if value:
                    return selector, value
    return None, None


def extract_availability(soup, json_ld=None):
    values = []
    if isinstance(json_ld, dict):
        offers = json_ld.get("offers")
        if isinstance(offers, dict):
            values.append(offers.get("availability"))
        elif isinstance(offers, list):
            values.extend(
                offer.get("availability")
                for offer in offers
                if isinstance(offer, dict)
            )

    values.extend(
        node.get("content") or node.get_text(" ", strip=True)
        for node in soup.select(
            '[itemprop="availability"], [data-testid*="availability" i]'
        )
    )

    joined = norm(" ".join(str(value or "") for value in values))
    if "instock" in joined or "en stock" in joined or "disponible" in joined:
        return "in_stock"
    if "outofstock" in joined or "rupture" in joined or "indisponible" in joined:
        return "out_of_stock"

    # The visible product page uses "En stock" for the purchasable state.
    text = norm(soup.get_text(" ", strip=True))
    if "en stock" in text:
        return "in_stock"
    if "en rupture de stock" in text or "rupture de stock" in text:
        return "out_of_stock"
    return "unknown"


def query_tokens(query):
    tokens = []
    for token in norm(query).split():
        if token in IGNORED_QUERY_WORDS:
            continue
        if len(token) <= 1:
            continue
        tokens.append(token)
    return tokens


def query_matches_product(name, query, brand="", size_ml=None, url=""):
    name_n = norm(name)
    query_n = norm(query)
    if not name_n or not query_n or not same_host(url):
        return False

    tokens = query_tokens(query)
    if not tokens:
        return False

    identity = norm(" ".join((name, brand)))
    if not all(token in identity for token in tokens):
        return False

    requested_size = explicit_size(query)
    if requested_size is not None and size_ml is not None:
        if float(requested_size) != float(size_ml):
            return False

    name_only = norm(name)
    query_norm = norm(query)
    for phrase in NON_PRODUCT_TERMS:
        phrase_norm = norm(phrase)
        if phrase_norm and phrase_norm in name_only and phrase_norm not in query_norm:
            return False

    return True


def candidate_from_url(url, text=""):
    url = url.split("#", 1)[0]
    if not same_host(url):
        return None

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    if not path or path == "/search.asp":
        return None

    segments = [segment for segment in path.split("/") if segment]

    # Notino exposes product pages in two valid forms:
    #   /brand/product-slug/
    #   /brand/product-slug/p-123456/
    # The p-ID is therefore optional. The search page is the discovery
    # authority and the real product page performs the final validation.
    product_id_match = PRODUCT_ID_RE.search(path + "/")
    product_id = product_id_match.group(1) if product_id_match else None

    if product_id is None:
        # Canonical product URLs have at least brand + product slug.
        # Broad category/filter roots are rejected before opening them.
        if len(segments) < 2:
            return None

        if segments[0].lower() in {
            "search.asp",
            "parfums",
            "maquillage",
            "cheveux",
            "visage",
            "corps",
            "homme",
            "femme",
            "marques",
            "promotions",
        }:
            return None

    return {
        "url": url.split("?", 1)[0],
        "text": clean(text),
        "product_id": product_id,
    }


def extract_search_candidates(soup, page_url):
    candidates = []
    seen = set()

    def add(url, text=""):
        candidate = candidate_from_url(urljoin(page_url, url), text)
        if not candidate:
            return
        key = candidate["url"].lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(candidate)

    # Normal result cards.
    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if not href:
            continue
        text_parts = [
            anchor.get("title"),
            anchor.get("aria-label"),
            anchor.get_text(" ", strip=True),
        ]
        image = anchor.find("img")
        if image:
            text_parts.extend((image.get("alt"), image.get("title")))
        add(href, " ".join(clean(value) for value in text_parts if clean(value)))

    # JSON-LD can expose product URLs even if the visible card anchor is
    # wrapped or assembled differently.
    for data in extract_json_ld_objects(soup):
        items = data.get("itemListElement")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                value = item.get("item")
                if isinstance(value, dict):
                    add(value.get("url", ""), value.get("name", ""))
                elif isinstance(value, str):
                    add(value, item.get("name", ""))

        if str(data.get("@type", "")).lower() == "product":
            add(data.get("url", ""), data.get("name", ""))

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
        if not response.ok or not same_host(response.url):
            return None
        return response
    except requests.RequestException:
        return None


def parse_product_page(response, query):
    soup = BeautifulSoup(response.text, "html.parser")
    json_ld = extract_product_json_ld(soup)

    name = visible_product_name(soup, json_ld)
    brand = visible_brand(soup, json_ld)
    text = soup.get_text(" ", strip=True)
    size_ml = extract_size_ml(name, text)
    concentration = extract_concentration(name)
    gender = extract_gender(name, text)
    price = extract_price(soup, json_ld)
    availability = extract_availability(soup, json_ld)
    image = visible_image(soup, json_ld)
    id_key, id_value = extract_sku(json_ld, soup)

    url = response.url.split("?", 1)[0]
    product_id_match = PRODUCT_ID_RE.search(url.rstrip("/") + "/")
    product_id = product_id_match.group(1) if product_id_match else None

    if not query_matches_product(name, query, brand=brand, size_ml=size_ml, url=url):
        return None

    identity = {
        "gtin": None,
        "mpn": None,
        "sku": None,
        "store_product_id": product_id,
        "store_variant_id": None,
    }
    if id_key in {"gtin", "gtin13", "gtin12", "gtin14"}:
        identity["gtin"] = id_value
    elif id_key == "mpn":
        identity["mpn"] = id_value
    elif id_key == "sku":
        identity["sku"] = id_value

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand or None,
            "url": url,
            "image": image or None,
        },
        "identity": identity,
        "attributes": {
            "size_ml": {"value": size_ml, "source": "product_page"},
            "concentration": {"value": concentration, "source": "product_page"},
            "gender": {"value": gender, "source": "product_page"},
            "packaging_type": {"value": "product", "source": "default"},
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
        "name": name,
        "brand": brand,
        "price": f"{price:.2f}".replace(".", ",") + " €" if price is not None else "",
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
        response = fetch(
            session,
            urljoin(BASE_URL, SEARCH_PATH),
            params={"exps": query},
        )
        if response is None:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        candidates = extract_search_candidates(soup, response.url)

        results = []
        seen = set()
        for candidate in candidates:
            url = candidate["url"]
            if url in seen:
                continue
            seen.add(url)

            product_response = fetch(session, url)
            if product_response is None:
                continue

            product = parse_product_page(product_response, query)
            if product is None:
                continue

            key = (product["url"].lower(), norm(product["name"]))
            if key in seen:
                continue
            seen.add(key)
            results.append(product)

        return results
    finally:
        session.close()


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
