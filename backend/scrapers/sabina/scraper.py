from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
TIMEOUT = int(os.getenv("SABINA_TIMEOUT_S", "20"))
LOGGER = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL + "/es/",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

# Sabina product URLs observed by the generic diagnostic have this shape:
# /<locale>/<category>/<numeric-id>-<slug>.html
PRODUCT_PATH_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl)/[^/]+/(\d+)-[^/]+\.html$",
    re.I,
)

PRODUCT_URL_IN_HTML_RE = re.compile(
    r"(?:https?:)?//(?:www\.)?sabina\.com"
    r"/(?:es|it|fr|en|de|nl)/[^\"'<>\\\s]+?/"
    r"\d+-[^\"'<>\\\s]+?\.html",
    re.I,
)

RELATIVE_PRODUCT_URL_IN_HTML_RE = re.compile(
    r"/(?:es|it|fr|en|de|nl)/[^\"'<>\\\s]+?/"
    r"\d+-[^\"'<>\\\s]+?\.html",
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
    ("Extrait de Parfum", (
        r"\bextrait\s+(?:de\s+)?parfum\b",
        r"\bextrait\b",
    )),
    ("Eau de Parfum", (
        r"\beau\s+de\s+parfum\b",
        r"\bedp\b",
    )),
    ("Eau de Toilette", (
        r"\beau\s+de\s+toilette\b",
        r"\bedt\b",
    )),
    ("Eau de Cologne", (
        r"\beau\s+de\s+cologne\b",
        r"\bedc\b",
    )),
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
    return {
        token
        for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS and len(token) > 1
    }


def query_matches(text, query):
    wanted = query_tokens(query)
    available = set(norm(text).split())
    return bool(wanted) and wanted.issubset(available)


def normalize_url(page_url, href):
    if not href:
        return None

    href = clean(href).replace("\\/", "/")
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(page_url, href)

    parsed = urlparse(href)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in {"sabina.com", "www.sabina.com"}:
        return None

    path = parsed.path.rstrip("/")
    if not path:
        return None

    return f"https://www.sabina.com{path}"


def is_product_url(url):
    try:
        return bool(PRODUCT_PATH_RE.match(urlparse(url).path))
    except Exception:
        return False


def product_id_from_url(url):
    match = PRODUCT_PATH_RE.match(urlparse(url).path)
    return match.group(1) if match else None


def money_to_float(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)

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
        return round(float(text), 2)
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
            if re.search(
                r"\b" + re.escape(norm(term)) + r"\b",
                normalized,
            ):
                return packaging_type, "product_text"

    return "product", "default"


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def first_jsonld_product(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        for item in walk_json(data):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(t).lower() == "product" for t in types):
                return item

    return {}


def extract_image(product, soup, page_url):
    image = product.get("image")

    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")

    if not image:
        meta = soup.select_one(
            'meta[property="og:image"], meta[name="twitter:image"]'
        )
        image = meta.get("content") if meta else None

    return urljoin(page_url, image) if image else None


def extract_brand(product):
    brand = product.get("brand")
    if isinstance(brand, dict):
        return clean(brand.get("name"))
    return clean(brand) or None


def extract_offer(product):
    offers = product.get("offers")

    if isinstance(offers, list):
        offers = [x for x in offers if isinstance(x, dict)]
        return offers[0] if offers else {}
    if isinstance(offers, dict):
        return offers

    return {}


def extract_availability(offer, soup):
    raw = clean(offer.get("availability")).lower()

    if "instock" in raw or "in stock" in raw:
        return "in_stock"
    if (
        "outofstock" in raw
        or "out of stock" in raw
        or "soldout" in raw
    ):
        return "out_of_stock"
    if "preorder" in raw:
        return "preorder"

    page_text = norm(soup.get_text(" ", strip=True))
    if (
        "fecha de disponibilidad" in page_text
        or "date de disponibilite" in page_text
    ):
        return "out_of_stock"

    return "unknown"


def extract_sku_from_page(text):
    match = re.search(
        r"(?:referencia|reference|référence|riferimento)"
        r"\s*[:#]?\s*([A-Z0-9_-]+)",
        text,
        re.I,
    )
    return match.group(1) if match else None


def extract_product_page(session, url, query):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        LOGGER.debug("Sabina product request failed %s: %s", url, exc)
        return None

    if response.status_code >= 400:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    product = first_jsonld_product(soup)

    h1 = soup.select_one("h1")
    h1_name = clean(h1.get_text(" ", strip=True)) if h1 else ""
    jsonld_name = clean(product.get("name"))
    title = h1_name or jsonld_name

    # Final validation happens on the REAL product page.
    # Discovery itself never depends on the anchor/card text.
    if not title or not query_matches(title, query):
        return None

    brand = extract_brand(product)
    offer = extract_offer(product)

    price = money_to_float(offer.get("price"))
    currency = clean(offer.get("priceCurrency")) or "EUR"
    availability = extract_availability(offer, soup)

    gtin = clean(
        product.get("gtin13")
        or product.get("gtin12")
        or product.get("gtin14")
        or product.get("gtin")
    ) or None

    mpn = clean(product.get("mpn")) or None
    sku = clean(product.get("sku")) or None

    page_text = soup.get_text(" ", strip=True)

    if not sku:
        sku = extract_sku_from_page(page_text)

    size_ml = extract_size_ml(title, page_text)
    concentration, concentration_source = extract_concentration(
        title,
        page_text,
    )
    gender, gender_source = extract_gender(title, page_text)
    packaging_type, packaging_source = extract_packaging_type(
        title,
        page_text,
    )

    product_url = normalize_url(response.url, response.url) or response.url
    product_id = product_id_from_url(product_url)
    image = extract_image(product, soup, product_url)

    return {
        "store": STORE,
        "source": {
            "url": product_url,
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
                {
                    "value": sku,
                    "source": "sabina_jsonld_or_reference",
                }
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
                {"value": size_ml, "source": "product_text"}
                if size_ml is not None else None
            ),
            "concentration": (
                {
                    "value": concentration,
                    "source": concentration_source,
                }
                if concentration else None
            ),
            "gender": (
                {"value": gender, "source": gender_source}
                if gender_source
                else {"value": "unknown", "source": "default"}
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
            "image": "sabina_jsonld_or_og",
            "store_product_id": (
                "product_url" if product_id else None
            ),
            "store_variant_id": None,
            "sku": (
                "sabina_jsonld_or_reference" if sku else None
            ),
            "gtin": "sabina_jsonld" if gtin else None,
            "mpn": "sabina_jsonld" if mpn else None,
            "size_ml": (
                "product_text" if size_ml is not None else None
            ),
            "concentration": concentration_source,
            "gender": gender_source,
            "packaging_type": packaging_source,
        },
        "raw_data": {
            "product_url": response.url,
            "status_code": response.status_code,
            "jsonld_product": product,
        },

        # Backward compatibility with current main.py.
        "name": title,
        "brand": brand,
        "price": (
            f"{price:.2f}".replace(".", ",") + " €"
            if price is not None else ""
        ),
        "url": product_url,
        "available": availability == "in_stock",
    }


def discover_product_urls(session, query):
    """
    Generic Sabina discovery.

    IMPORTANT:
    The diagnostic proved that Sabina's search HTML already contains real
    product URLs, but the old scraper discarded them because it required the
    query to be present in the anchor/card text.

    This function deliberately does NOT validate the query against the
    search-card text. Every structurally valid product URL is a candidate;
    the real product page performs the query validation.
    """
    search_urls = (
        BASE_URL + "/es/buscar?search_query=" + quote_plus(query),
        BASE_URL + "/es/buscar_old?s=" + quote_plus(query),
        BASE_URL + "/es/buscar_old?controller=search&s=" + quote_plus(query),
        BASE_URL + "/es/buscar?s=" + quote_plus(query),
    )

    found = []
    seen = set()

    for search_url in search_urls:
        try:
            response = session.get(
                search_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            LOGGER.debug("Sabina search request failed %s: %s", search_url, exc)
            continue

        if response.status_code >= 400:
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        # 1. Normal anchors.
        for anchor in soup.find_all("a", href=True):
            absolute = normalize_url(response.url, anchor.get("href"))
            if not absolute or not is_product_url(absolute):
                continue

            if absolute not in seen:
                seen.add(absolute)
                found.append(absolute)

        # 2. Product URLs embedded in raw HTML / scripts.
        raw_html = response.text.replace("\\/", "/")

        for match in PRODUCT_URL_IN_HTML_RE.finditer(raw_html):
            absolute = normalize_url(response.url, match.group(0))
            if absolute and is_product_url(absolute) and absolute not in seen:
                seen.add(absolute)
                found.append(absolute)

        for match in RELATIVE_PRODUCT_URL_IN_HTML_RE.finditer(raw_html):
            absolute = normalize_url(response.url, match.group(0))
            if absolute and is_product_url(absolute) and absolute not in seen:
                seen.add(absolute)
                found.append(absolute)

    return found


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()

    urls = discover_product_urls(session, query)

    results = []
    seen_products = set()

    # Candidate discovery is deliberately separate from product validation.
    # This is the critical difference from the previous Sabina scraper.
    for url in urls[:30]:
        product = extract_product_page(session, url, query)
        if not product:
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
            product.get("identity", {})
            .get("store_product_id", {})
            .get("value")
        ) or product.get("url")

        if key in seen_products:
            continue

        seen_products.add(key)
        results.append(product)

    return results


# Generic loader compatibility used by ScentHunter.
def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generic Sabina scraper")
    parser.add_argument("query", help="Runtime search query")
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
