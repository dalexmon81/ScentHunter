import json
import re
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
SEARCH_URL = BASE_URL + "/es/buscar"
TIMEOUT = 10
MAX_CANDIDATES = 20

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
    "Referer": BASE_URL + "/es/",
}

PRODUCT_PATH_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl|pt)/[^/]+/(\d+)-[^/]+\.html$",
    re.I,
)

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "for", "by", "ml", "pour",
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


def query_tokens(query):
    return [
        token
        for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS
    ]


def query_matches(text, query):
    tokens = query_tokens(query)
    normalized = norm(text)
    return bool(tokens) and all(token in normalized for token in tokens)


def normalise_url(url, base_url=BASE_URL):
    if not url:
        return None

    url = clean(url).replace("\\/", "/")
    url = url.replace("\\u002F", "/")

    absolute = urljoin(base_url, url)
    parsed = urlparse(absolute)

    if parsed.scheme not in {"http", "https"}:
        return None

    host = parsed.netloc.lower()
    if host not in {"sabina.com", "www.sabina.com"}:
        return None

    return (
        f"{parsed.scheme}://{parsed.netloc}"
        f"{parsed.path.rstrip('/')}"
    )


def is_product_url(url):
    if not url:
        return False
    return bool(
        PRODUCT_PATH_RE.match(
            urlparse(url).path
        )
    )


def product_id_from_url(url):
    match = PRODUCT_PATH_RE.match(
        urlparse(url).path
    )
    return match.group(1) if match else None


def money_to_float(value):
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = re.sub(
        r"[^\d,.\-]",
        "",
        str(value),
    )

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "")
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def extract_size_ml(*texts):
    combined = " ".join(
        str(text or "")
        for text in texts
    )

    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*"
        r"(?:ml|millilitros?|milliliters?)\b",
        combined,
        re.I,
    )

    if not match:
        return None

    value = float(
        match.group(1).replace(",", ".")
    )

    return int(value) if value.is_integer() else value


CONCENTRATION_RULES = (
    (
        "Extrait de Parfum",
        (
            r"\bextrait\s+(?:de\s+)?parfum\b",
            r"\bextrait\b",
        ),
    ),
    (
        "Eau de Parfum",
        (
            r"\beau\s+de\s+parfum\b",
            r"\bedp\b",
        ),
    ),
    (
        "Eau de Toilette",
        (
            r"\beau\s+de\s+toilette\b",
            r"\bedt\b",
        ),
    ),
    (
        "Eau de Cologne",
        (
            r"\beau\s+de\s+cologne\b",
            r"\bedc\b",
        ),
    ),
    ("Parfum", (r"\bparfum\b",)),
)


def extract_concentration(*texts):
    normalized = norm(
        " ".join(str(text or "") for text in texts)
    )

    for label, patterns in CONCENTRATION_RULES:
        for pattern in patterns:
            if re.search(
                pattern,
                normalized,
                re.I,
            ):
                return label, "product_text"

    return None, None


def extract_gender(*texts):
    normalized = norm(
        " ".join(str(text or "") for text in texts)
    )

    if re.search(
        r"\b(?:hombre|hombres|man|men|masculino|male|"
        r"pour homme|homme|uomo)\b",
        normalized,
    ):
        return "men", "product_text"

    if re.search(
        r"\b(?:mujer|mujeres|woman|women|femenino|female|"
        r"pour femme|femme|donna)\b",
        normalized,
    ):
        return "women", "product_text"

    if re.search(
        r"\b(?:unisex|unisexe|unisexes)\b",
        normalized,
    ):
        return "unisex", "product_text"

    return "unknown", None


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)

    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def first_jsonld_product(soup):
    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        for item in walk_json(data):
            if not isinstance(item, dict):
                continue

            item_type = item.get("@type")
            types = (
                item_type
                if isinstance(item_type, list)
                else [item_type]
            )

            if any(
                str(item_type_value).lower() == "product"
                for item_type_value in types
            ):
                return item

    return None


def discover_product_urls(session, query):
    """
    The only primary discovery path used by the real scraper.

    The query is supplied at runtime. No product, brand, SKU or URL
    is hard-coded here.
    """
    try:
        response = session.get(
            SEARCH_URL,
            params={"search_query": query},
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return []

    if response.status_code >= 400:
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    urls = []
    seen = set()

    def add(raw):
        absolute = normalise_url(
            raw,
            response.url,
        )

        if not absolute:
            return

        if not is_product_url(absolute):
            return

        if absolute in seen:
            return

        seen.add(absolute)
        urls.append(absolute)

    # First source: normal product links.
    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        add(anchor.get("href"))

    # Second source: product URLs embedded in the returned HTML/JSON.
    decoded = (
        response.text
        .replace("\\/", "/")
        .replace("\\u002F", "/")
    )

    for match in re.finditer(
        r'https?://(?:www\.)?sabina\.com/'
        r'(?:es|it|fr|en|de|nl|pt)/'
        r'[^"\'<>\s\\]+',
        decoded,
        re.I,
    ):
        add(match.group(0))

    for match in re.finditer(
        r'/(?:es|it|fr|en|de|nl|pt)/'
        r'[^"\'<>\s\\]+',
        decoded,
        re.I,
    ):
        add(match.group(0))

    return urls[:MAX_CANDIDATES]


def extract_product_page(session, url, query):
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

    final_url = normalise_url(response.url)

    if not final_url or not is_product_url(final_url):
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    product = first_jsonld_product(soup)

    h1 = soup.select_one("h1")
    h1_text = (
        clean(h1.get_text(" ", strip=True))
        if h1
        else ""
    )

    title = clean(
        (product or {}).get("name")
        or h1_text
    )

    if not title:
        return None

    # Validation is deliberately generic and based on the real product
    # identity, not on search-card text.
    brand = None
    raw_brand = (product or {}).get("brand")

    if isinstance(raw_brand, dict):
        brand = clean(
            raw_brand.get("name")
        ) or None

    elif raw_brand:
        brand = clean(raw_brand)

    if not query_matches(
        f"{title} {brand or ''}",
        query,
    ):
        return None

    offers = (product or {}).get("offers")

    if isinstance(offers, list):
        offer = offers[0] if offers else {}

    elif isinstance(offers, dict):
        offer = offers

    else:
        offer = {}

    price = money_to_float(
        offer.get("price")
    )

    currency = clean(
        offer.get("priceCurrency")
    ) or "EUR"

    availability_raw = clean(
        offer.get("availability")
    ).lower()

    if "instock" in availability_raw:
        availability = "in_stock"

    elif (
        "outofstock" in availability_raw
        or "soldout" in availability_raw
        or "unavailable" in availability_raw
    ):
        availability = "out_of_stock"

    elif "preorder" in availability_raw:
        availability = "preorder"

    else:
        page_text_normalized = norm(
            soup.get_text(" ", strip=True)
        )

        if (
            "fecha de disponibilidad"
            in page_text_normalized
            or "date de disponibilite"
            in page_text_normalized
        ):
            availability = "out_of_stock"
        else:
            availability = "unknown"

    image = (product or {}).get("image")

    if isinstance(image, list):
        image = image[0] if image else None

    if isinstance(image, dict):
        image = (
            image.get("url")
            or image.get("contentUrl")
        )

    if image:
        image = urljoin(
            response.url,
            image,
        )

    gtin = clean(
        (product or {}).get("gtin13")
        or (product or {}).get("gtin12")
        or (product or {}).get("gtin14")
        or (product or {}).get("gtin")
    ) or None

    mpn = clean(
        (product or {}).get("mpn")
    ) or None

    sku = clean(
        (product or {}).get("sku")
    ) or None

    page_text = soup.get_text(
        " ",
        strip=True,
    )

    if not sku:
        reference_match = re.search(
            r"(?:referencia|reference|référence|riferimento)"
            r"\s*[:#]?\s*([A-Z0-9_-]+)",
            page_text,
            re.I,
        )

        if reference_match:
            sku = reference_match.group(1)

    product_id = product_id_from_url(
        final_url
    )

    # The product title comes from the verified Product JSON-LD / H1.
    # Do not scan the whole page: related products can contain other sizes.
    size_ml = extract_size_ml(
        title,
    )

    concentration, concentration_source = (
        extract_concentration(
            title,
            page_text,
        )
    )

    gender, gender_source = extract_gender(
        title,
        page_text,
    )

    return {
        "store": STORE,

        "source": {
            "url": final_url,
            "name": title,
            "brand": brand,
            "image": image,
        },

        "identity": {
            "gtin": (
                {
                    "value": gtin,
                    "source": "sabina_jsonld",
                }
                if gtin
                else None
            ),

            "mpn": (
                {
                    "value": mpn,
                    "source": "sabina_jsonld",
                }
                if mpn
                else None
            ),

            "sku": (
                {
                    "value": sku,
                    "source": "sabina_jsonld_or_reference",
                }
                if sku
                else None
            ),

            "store_product_id": (
                {
                    "value": product_id,
                    "source": "product_url",
                }
                if product_id
                else None
            ),
        },

        "attributes": {
            "size_ml": (
                {
                    "value": size_ml,
                    "source": "product_text",
                }
                if size_ml is not None
                else None
            ),

            "concentration": (
                {
                    "value": concentration,
                    "source": concentration_source,
                }
                if concentration
                else None
            ),

            "gender": (
                {
                    "value": gender,
                    "source": gender_source,
                }
                if gender_source
                else {
                    "value": "unknown",
                    "source": "default",
                }
            ),

            "packaging_type": {
                "value": "product",
                "source": "default",
            },
        },

        "offer": {
            "price": price,
            "currency": currency,
            "availability": availability,
        },

        "provenance": {
            "name": "sabina_jsonld_or_h1",
            "brand": (
                "sabina_jsonld"
                if brand
                else None
            ),
            "price": "sabina_jsonld",
            "availability": (
                "sabina_jsonld_or_page_text"
            ),
            "image": (
                "sabina_jsonld"
                if image
                else None
            ),
            "store_product_id": (
                "product_url"
                if product_id
                else None
            ),
            "sku": (
                "sabina_jsonld_or_reference"
                if sku
                else None
            ),
            "gtin": (
                "sabina_jsonld"
                if gtin
                else None
            ),
            "mpn": (
                "sabina_jsonld"
                if mpn
                else None
            ),
            "size_ml": (
                "product_text"
                if size_ml is not None
                else None
            ),
            "concentration": concentration_source,
            "gender": gender_source,
            "packaging_type": "default",
        },

        "raw_data": {
            "product_url": final_url,
            "status_code": response.status_code,
            "jsonld_product": product,
        },

        # Backward-compatible fields expected by main.py.
        "name": title,
        "brand": brand,
        "price": (
            f"{price:.2f}".replace(".", ",")
            + " €"
            if price is not None
            else ""
        ),
        "url": final_url,
        "available": availability == "in_stock",
    }


def search(query):
    query = clean(query)

    if not query:
        return []

    session = requests.Session()

    try:
        candidate_urls = discover_product_urls(
            session,
            query,
        )

        results = []
        seen = set()

        for url in candidate_urls:
            product = extract_product_page(
                session,
                url,
                query,
            )

            if not product:
                continue

            product_id = (
                product.get("identity", {})
                .get("store_product_id", {})
                .get("value")
            )

            key = product_id or product.get("url")

            if key in seen:
                continue

            seen.add(key)
            results.append(product)

        return results

    finally:
        session.close()


# Compatibility with the generic main.py interface.
scrape = search


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generic Sabina scraper"
    )
    parser.add_argument(
        "query",
        help="Search query supplied at runtime",
    )

    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
