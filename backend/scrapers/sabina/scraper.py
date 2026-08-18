import json
import re
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
SEARCH_PATH = "/es/buscar"
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

PRODUCT_PATH_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl)/[^/]+/(\d+)-[^/]+\.html$",
    re.I,
)

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "for", "by", "ml", "pour",
}

NON_PRODUCT_TERMS = {
    "gift set", "set regalo", "coffret", "bundle", "kit",
    "deodorant", "deo spray", "shower gel", "body lotion",
    "after shave", "aftershave", "travel set", "discovery set",
    "body mist", "hand cream", "handcreme",
}

PACKAGING_RULES = (
    ("gift_set", ("gift set", "set regalo", "coffret", "gift box")),
    ("discovery_set", ("discovery set", "discoveryset")),
    ("bundle", ("bundle", "duo", "trio", "pack")),
    ("tester", ("tester",)),
    ("sample", ("sample", "muestra", "échantillon", "campione")),
    ("decant", ("decant",)),
)

CONCENTRATION_RULES = (
    ("Extrait de Parfum", (r"\bextrait\s+(?:de\s+)?parfum\b", r"\bextrait\b")),
    ("Eau de Parfum", (r"\beau\s+de\s+parfum\b", r"\bedp\b")),
    ("Eau de Toilette", (r"\beau\s+de\s+toilette\b", r"\bedt\b")),
    ("Eau de Cologne", (r"\beau\s+de\s+cologne\b", r"\bedc\b")),
    ("Parfum", (r"\bparfum\b",)),
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def query_tokens(query):
    return [
        token for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS
    ]


def query_matches(text, query):
    tokens = query_tokens(query)
    normalized = norm(text)
    return bool(tokens) and all(token in normalized for token in tokens)


def is_product_url(url):
    path = urlparse(url).path
    return bool(PRODUCT_PATH_RE.match(path))


def product_id_from_url(url):
    match = PRODUCT_PATH_RE.match(urlparse(url).path)
    return match.group(1) if match else None


def money_to_float(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    text = re.sub(r"[^\d,.\-]", "", text)

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def extract_size_ml(*texts):
    combined = " ".join(str(x or "") for x in texts)
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:ml|millilitros?|milliliters?)\b",
        combined,
        re.I,
    )
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return int(value) if value.is_integer() else value


def extract_size_from_product_data(product, offer):
    """
    Prefer structured product data over the complete page text.

    Sabina can contain unrelated volume values elsewhere on the product
    page. The JSON-LD product name / offer name is the authoritative
    product-level source when present.
    """
    structured_texts = []

    if isinstance(product, dict):
        structured_texts.extend([
            product.get("name"),
            product.get("description"),
        ])

    if isinstance(offer, dict):
        structured_texts.extend([
            offer.get("name"),
        ])

    size = extract_size_ml(*structured_texts)
    if size is not None:
        return size, "sabina_jsonld"

    return None, None


def extract_concentration(*texts):
    normalized = norm(" ".join(str(x or "") for x in texts))
    for label, patterns in CONCENTRATION_RULES:
        for pattern in patterns:
            if re.search(pattern, normalized, re.I):
                return label, "product_text"
    return None, None


def extract_gender(*texts):
    normalized = norm(" ".join(str(x or "") for x in texts))
    if re.search(
        r"\b(?:hombre|hombres|man|men|masculino|male|pour homme|homme|uomo)\b",
        normalized,
    ):
        return "men", "product_text"
    if re.search(
        r"\b(?:mujer|mujeres|woman|women|femenino|female|pour femme|femme|donna)\b",
        normalized,
    ):
        return "women", "product_text"
    if re.search(r"\b(?:unisex|unisexe|unisexes)\b", normalized):
        return "unisex", "product_text"
    return "unknown", None


def extract_packaging_type(*texts):
    normalized = norm(" ".join(str(x or "") for x in texts))
    for packaging_type, terms in PACKAGING_RULES:
        for term in terms:
            if re.search(r"\b" + re.escape(norm(term)) + r"\b", normalized):
                return packaging_type, "product_text"
    return "product", "default"


def first_jsonld_product(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue

        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            if item.get("@graph"):
                stack.extend(item["@graph"])
                continue

            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(t).lower() == "product" for t in types):
                return item
    return None


def extract_product_page(session, url):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None

    if response.status_code >= 400:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    product = first_jsonld_product(soup)

    title = clean(
        (product or {}).get("name")
        or (
            soup.select_one("h1").get_text(" ", strip=True)
            if soup.select_one("h1") else ""
        )
    )

    if not title:
        return None

    brand = None
    if isinstance((product or {}).get("brand"), dict):
        brand = clean((product["brand"].get("name")))
    elif (product or {}).get("brand"):
        brand = clean(product["brand"])

    # IMPORTANT:
    # Sabina's JSON-LD can expose an empty/invalid SKU. Never derive a SKU
    # from arbitrary page text: doing so previously produced the false value
    # "s". Only accept a real structured SKU.
    raw_sku = clean((product or {}).get("sku"))
    sku = raw_sku if raw_sku and len(raw_sku) >= 2 else None

    mpn = clean((product or {}).get("mpn")) or None
    gtin = (
        clean(
            (product or {}).get("gtin13")
            or (product or {}).get("gtin12")
            or (product or {}).get("gtin14")
            or (product or {}).get("gtin")
        )
        or None
    )

    image = (product or {}).get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    image = urljoin(response.url, image) if image else None

    offers = (product or {}).get("offers")
    if isinstance(offers, list):
        offer = offers[0] if offers else {}
    elif isinstance(offers, dict):
        offer = offers
    else:
        offer = {}

    price = money_to_float(offer.get("price"))
    currency = clean(offer.get("priceCurrency")) or "EUR"

    availability_raw = clean(offer.get("availability")).lower()
    if "instock" in availability_raw:
        availability = "in_stock"
    elif "outofstock" in availability_raw or "soldout" in availability_raw:
        availability = "out_of_stock"
    elif "preorder" in availability_raw:
        availability = "preorder"
    else:
        page_text = norm(soup.get_text(" ", strip=True))
        if (
            "fecha de disponibilidad" in page_text
            or "date de disponibilite" in page_text
        ):
            availability = "out_of_stock"
        else:
            availability = "unknown"

    page_text = soup.get_text(" ", strip=True)

    # IMPORTANT:
    # Size is read from product-level JSON-LD first. The complete page text
    # is deliberately NOT used as the first source because it can contain
    # unrelated sizes from recommendations, navigation or other products.
    size_ml, size_source = extract_size_from_product_data(product, offer)

    # If structured product data has no size, fall back to the product title
    # only. Do not scan the whole page for an arbitrary volume.
    if size_ml is None:
        size_ml = extract_size_ml(title)
        if size_ml is not None:
            size_source = "product_title"

    concentration, concentration_source = extract_concentration(
        title,
        page_text,
    )
    gender, gender_source = extract_gender(title, page_text)
    packaging_type, packaging_source = extract_packaging_type(
        title,
        page_text,
    )

    product_id = product_id_from_url(response.url)

    raw_data = {
        "product_url": response.url,
        "status_code": response.status_code,
        "jsonld_product": product,
    }

    return {
        "store": STORE,
        "source": {
            "url": response.url,
            "name": title,
            "brand": brand,
            "image": image,
        },
        "identity": {
            "gtin": (
                {"value": gtin, "source": "sabina_jsonld"}
                if gtin else None
            ),
            "mpn": (
                {"value": mpn, "source": "sabina_jsonld"}
                if mpn else None
            ),
            "sku": (
                {"value": sku, "source": "sabina_jsonld"}
                if sku else None
            ),
            "store_product_id": (
                {"value": product_id, "source": "product_url"}
                if product_id else None
            ),
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": (
                {"value": size_ml, "source": size_source}
                if size_ml is not None else None
            ),
            "concentration": (
                {"value": concentration, "source": concentration_source}
                if concentration else None
            ),
            "gender": (
                {"value": gender, "source": gender_source}
                if gender_source else {"value": "unknown", "source": "default"}
            ),
            "packaging_type": {
                "value": packaging_type,
                "source": packaging_source,
            },
        },
        "offer": {
            "price": price,
            "currency": currency,
            "availability": availability,
        },
        "provenance": {
            "name": "sabina_jsonld_or_h1",
            "brand": "sabina_jsonld" if brand else None,
            "price": "sabina_jsonld",
            "availability": "sabina_jsonld_or_page_text",
            "image": "sabina_jsonld" if image else None,
            "store_product_id": "product_url" if product_id else None,
            "store_variant_id": None,
            "sku": "sabina_jsonld" if sku else None,
            "gtin": "sabina_jsonld" if gtin else None,
            "mpn": "sabina_jsonld" if mpn else None,
            "size_ml": size_source,
            "concentration": concentration_source,
            "gender": gender_source,
            "packaging_type": packaging_source,
        },
        "raw_data": raw_data,

        # Backward-compatible fields for the current main.py.
        "name": title,
        "brand": brand,
        "price": (
            f"{price:.2f}".replace(".", ",") + " €"
            if price is not None else ""
        ),
        "url": response.url,
        "available": availability == "in_stock",
    }


def search_result_urls(session, query):
    urls = []
    seen = set()

    search_urls = (
        BASE_URL + SEARCH_PATH + "?controller=search&s=" + quote_plus(query),
        BASE_URL + "/es/buscar?s=" + quote_plus(query),
    )

    for search_url in search_urls:
        try:
            response = session.get(
                search_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if response.status_code >= 400:
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        for anchor in soup.find_all("a", href=True):
            absolute = urljoin(response.url, anchor["href"]).split("#")[0]
            if not is_product_url(absolute):
                continue

            path = urlparse(absolute).path
            if path in seen:
                continue

            text = clean(
                anchor.get("title")
                or anchor.get("aria-label")
                or anchor.get_text(" ", strip=True)
            )

            if not query_matches(text, query):
                parent = anchor
                for _ in range(5):
                    parent = parent.parent if parent is not None else None
                    if parent is None:
                        break
                    candidate_text = clean(parent.get_text(" ", strip=True))
                    if query_matches(candidate_text, query):
                        text = candidate_text
                        break

            if not query_matches(text, query):
                continue

            normalized = norm(text)
            if any(term in normalized for term in NON_PRODUCT_TERMS):
                continue

            seen.add(path)
            urls.append(absolute)

    return urls


def brand_page_urls(session, query):
    """
    Secondary generic discovery path.

    Sabina exposes brand pages such as /es/630_rayhaan. When normal site
    search misses a product, discover brand/category links from the search
    page and inspect their product links. No brand is hard-coded here.
    """
    urls = []
    seen = set()

    search_url = (
        BASE_URL + SEARCH_PATH + "?controller=search&s=" + quote_plus(query)
    )

    try:
        response = session.get(
            search_url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return urls

    if response.status_code >= 400:
        return urls

    soup = BeautifulSoup(response.text, "html.parser")

    candidate_pages = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(response.url, anchor["href"]).split("#")[0]
        path = urlparse(href).path

        if re.search(r"/(?:es|it|fr|en|de|nl)/\d+_[^/]+/?$", path, re.I):
            text = clean(anchor.get_text(" ", strip=True))
            if text and query_matches(text, query):
                candidate_pages.append(href)

    for page_url in candidate_pages[:4]:
        try:
            page = session.get(
                page_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if page.status_code >= 400:
            continue

        page_soup = BeautifulSoup(page.text, "html.parser")
        for anchor in page_soup.find_all("a", href=True):
            absolute = urljoin(page.url, anchor["href"]).split("#")[0]
            path = urlparse(absolute).path
            if not is_product_url(absolute) or path in seen:
                continue

            text = clean(
                anchor.get("title")
                or anchor.get("aria-label")
                or anchor.get_text(" ", strip=True)
            )
            if query_matches(text, query):
                seen.add(path)
                urls.append(absolute)

    return urls


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    urls = []
    seen_urls = set()

    for url in search_result_urls(session, query):
        if url not in seen_urls:
            seen_urls.add(url)
            urls.append(url)

    for url in brand_page_urls(session, query):
        if url not in seen_urls:
            seen_urls.add(url)
            urls.append(url)

    results = []
    seen_products = set()

    for url in urls[:12]:
        product = extract_product_page(session, url)
        if not product:
            continue

        if not query_matches(product.get("name", ""), query):
            continue

        packaging = product.get("attributes", {}).get("packaging_type") or {}
        packaging_value = (
            packaging.get("value")
            if isinstance(packaging, dict)
            else packaging
        )
        if packaging_value == "tester":
            continue

        key = (
            product["identity"].get("store_product_id", {}).get("value")
            if isinstance(product["identity"].get("store_product_id"), dict)
            else None
        ) or product["url"]

        if key in seen_products:
            continue

        seen_products.add(key)
        results.append(product)

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generic Sabina scraper")
    parser.add_argument("query", help="Search query supplied at runtime")
    args = parser.parse_args()

    for item in search(args.query):
        print(json.dumps(item, ensure_ascii=False, indent=2))
