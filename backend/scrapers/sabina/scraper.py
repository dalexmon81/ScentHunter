import json
import re
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
SEARCH_URL = BASE_URL + "/es/buscar"
TIMEOUT = 20
MAX_CANDIDATES = 40
MAX_SITEMAPS = 80
SITEMAP_INDEX_URL = BASE_URL + "/sitemap_index_shop_1.xml"

# Generic discovery sources proven by the Sabina diagnostic.
# The runtime query is always supplied dynamically.
SEARCH_ENDPOINTS = (
    (SEARCH_URL, {"search_query": "QUERY"}),
    (SEARCH_URL, {"s": "QUERY"}),
    (SEARCH_URL, {"controller": "search", "s": "QUERY"}),
    (BASE_URL + "/es/buscar_old", {"s": "QUERY"}),
    (BASE_URL + "/es/buscar_old", {"controller": "search", "s": "QUERY"}),
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

PRODUCT_PATH_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl)/[^/]+/(\d+)-[^/]+\.html$",
    re.I,
)

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
    "spray", "for", "by", "ml", "pour", "the", "el", "la",
    "un", "una",
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

NON_PRODUCT_TERMS = {
    "gift set", "set regalo", "coffret", "bundle", "kit",
    "deodorant", "deo spray", "shower gel", "body lotion",
    "after shave", "aftershave", "travel set", "discovery set",
    "body mist", "hand cream", "handcreme",
}


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
        if token not in IGNORED_QUERY_WORDS and len(token) > 1
    ]


def query_matches(text, query):
    wanted = query_tokens(query)
    words = set(norm(text).split())
    return bool(wanted) and all(token in words for token in wanted)


def normalise_url(href, base=BASE_URL):
    if not href:
        return None
    href = clean(href).replace("\\/", "/").replace("\\u002F", "/")
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(base, href)
    parsed = urlparse(href)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = parsed.netloc.lower()
    if host != "sabina.com" and not host.endswith(".sabina.com"):
        return None
    path = parsed.path.rstrip("/")
    if not path or path == "/":
        return None
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def is_product_url(url):
    return bool(url and PRODUCT_PATH_RE.match(urlparse(url).path))


def product_id_from_url(url):
    match = PRODUCT_PATH_RE.match(urlparse(url).path)
    return match.group(1) if match else None


def money_to_float(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d,.\-]", "", str(value))
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
    text = " ".join(str(x or "") for x in texts)
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:ml|millilitros?|milliliters?)\b",
        text, re.I,
    )
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return int(value) if value.is_integer() else value


def extract_concentration(*texts):
    text = norm(" ".join(str(x or "") for x in texts))
    for label, patterns in CONCENTRATION_RULES:
        for pattern in patterns:
            if re.search(pattern, text, re.I):
                return label, "product_text"
    return None, None


def extract_gender(*texts):
    text = norm(" ".join(str(x or "") for x in texts))
    if re.search(r"\b(?:hombre|hombres|man|men|masculino|male|pour homme|homme|uomo)\b", text):
        return "men", "product_text"
    if re.search(r"\b(?:mujer|mujeres|woman|women|femenino|female|pour femme|femme|donna)\b", text):
        return "women", "product_text"
    if re.search(r"\b(?:unisex|unisexe|unisexes)\b", text):
        return "unisex", "product_text"
    return "unknown", None


def extract_packaging_type(*texts):
    text = norm(" ".join(str(x or "") for x in texts))
    for packaging_type, terms in PACKAGING_RULES:
        for term in terms:
            if re.search(r"\b" + re.escape(norm(term)) + r"\b", text):
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
            data = json.loads(raw.strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for item in walk_json(data):
            if not isinstance(item, dict):
                continue
            types = item.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(str(t).lower() == "product" for t in types):
                return item
    return None


def extract_search_product_urls(html, base_url=BASE_URL):
    """Extract structurally valid Sabina product URLs from a search response.

    Discovery and identity validation are intentionally separate: a URL only
    becomes a product result after its own product page is fetched and
    validated. No product name, brand, ID or URL is hard-coded here.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    found, seen = [], set()

    def add(raw):
        url = normalise_url(raw, base_url)
        if url and is_product_url(url) and url not in seen:
            seen.add(url)
            found.append(url)

    # 1. Normal links and common data attributes.
    for anchor in soup.find_all("a", href=True):
        add(anchor.get("href"))

    for node in soup.find_all(True):
        for attr in ("data-href", "data-url", "data-product-url", "data-link"):
            add(node.get(attr))

    # 2. Product URLs embedded in raw HTML, JSON or JavaScript.
    decoded = (html or "").replace("\\/", "/").replace("\\u002F", "/")
    patterns = (
        r'https?://(?:www\\.)?sabina\\.com/(?:es|it|fr|en|de|nl)/[^"\'<>\\s\\]+',
        r'/(?:es|it|fr|en|de|nl)/[^"\'<>\\s\\]+',
    )
    for pattern in patterns:
        for match in re.finditer(pattern, decoded, re.I):
            add(match.group(0))

    # 3. JSON-LD can contain product/@id URLs even when the anchor is absent.
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for obj in walk_json(data):
            if isinstance(obj, dict):
                add(obj.get("url"))
                add(obj.get("@id"))

    return found


def xml_urls(text):
    """Return <loc> URLs from a sitemap/index, with regex fallback."""
    if not text:
        return []
    urls = []
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text)
        for element in root.iter():
            if element.tag.lower().endswith("loc") and element.text:
                urls.append(clean(element.text))
    except Exception:
        urls = re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.I | re.S)
        urls = [clean(value) for value in urls]
    return list(dict.fromkeys(urls))


def discover_from_search(session, query):
    """Run Sabina's generic HTTP search endpoints and collect candidates."""
    found, seen = [], set()

    for endpoint, raw_params in SEARCH_ENDPOINTS:
        params = {
            key: (query if value == "QUERY" else value)
            for key, value in raw_params.items()
        }
        response = fetch(session, endpoint, params)
        if response is None or response.status_code >= 400:
            continue

        for url in extract_search_product_urls(response.text, response.url):
            if url in seen:
                continue
            seen.add(url)
            found.append(url)
            if len(found) >= MAX_CANDIDATES:
                return found

    return found


def discover_from_sitemap(session, query):
    """Fallback discovery through Sabina's generic product sitemap index."""
    response = fetch(session, SITEMAP_INDEX_URL)
    if response is None or response.status_code >= 400:
        return []

    sitemap_urls = [
        url for url in xml_urls(response.text)
        if url.startswith("http")
    ]

    wanted = set(query_tokens(query))
    if not wanted:
        return []

    candidates, seen = [], set()

    for sitemap_url in sitemap_urls[:MAX_SITEMAPS]:
        child = fetch(session, sitemap_url)
        if child is None or child.status_code >= 400:
            continue

        for url in xml_urls(child.text):
            normalized = normalise_url(url)
            if not normalized or not is_product_url(normalized):
                continue

            slug_text = norm(urlparse(normalized).path)
            if not all(token in slug_text for token in wanted):
                continue

            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(normalized)
            if len(candidates) >= MAX_CANDIDATES:
                return candidates

        # Once this sitemap has produced usable candidates, there is no need
        # to crawl unrelated child sitemaps.
        if candidates:
            break

    return candidates


def fetch(session, url, params=None):
    try:
        return session.get(
            url, params=params, headers=HEADERS,
            timeout=TIMEOUT, allow_redirects=True,
        )
    except requests.RequestException:
        return None


def extract_product_page(session, url, query):
    response = fetch(session, url)
    if response is None or response.status_code >= 400:
        return None

    final_url = normalise_url(response.url) or url
    if not is_product_url(final_url):
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    product = first_jsonld_product(soup)
    h1_node = soup.select_one("h1")
    h1 = clean(h1_node.get_text(" ", strip=True)) if h1_node else ""
    title = clean((product or {}).get("name")) or h1
    if not title:
        return None

    raw_brand = (product or {}).get("brand")
    brand = (
        clean(raw_brand.get("name"))
        if isinstance(raw_brand, dict)
        else clean(raw_brand)
    ) or None

    # Validation is done on the actual product page, never on the search card.
    # Include H1 and all JSON-LD Product names because Sabina can expose the
    # same product identity in different page fields.
    jsonld_names = []
    for item in walk_json(product or {}):
        if isinstance(item, dict) and str(item.get("@type", "")).lower() == "product":
            name_value = clean(item.get("name"))
            if name_value:
                jsonld_names.append(name_value)

    identity_text = " ".join(
        x for x in (title, h1, brand, *jsonld_names) if x
    )
    if not query_matches(identity_text, query):
        return None

    raw_sku = clean((product or {}).get("sku"))
    sku = raw_sku if len(raw_sku) >= 2 else None
    mpn = clean((product or {}).get("mpn")) or None
    gtin = clean(
        (product or {}).get("gtin13")
        or (product or {}).get("gtin12")
        or (product or {}).get("gtin14")
        or (product or {}).get("gtin")
    ) or None

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
        availability = (
            "out_of_stock"
            if "fecha de disponibilidad" in page_text
            or "date de disponibilite" in page_text
            else "unknown"
        )

    structured_text = " ".join(str(x or "") for x in (
        title, (product or {}).get("description"), offer.get("name")
    ))
    size_ml = extract_size_ml(title, offer.get("name"))
    if size_ml is None:
        size_ml = extract_size_ml((product or {}).get("description"))
    size_source = "sabina_jsonld" if size_ml is not None else None

    concentration, concentration_source = extract_concentration(structured_text)
    gender, gender_source = extract_gender(structured_text)
    packaging_type, packaging_source = extract_packaging_type(structured_text)
    product_id = product_id_from_url(final_url)

    return {
        "store": STORE,
        "source": {
            "url": final_url,
            "name": title,
            "brand": brand,
            "image": image,
        },
        "identity": {
            "gtin": {"value": gtin, "source": "sabina_jsonld"} if gtin else None,
            "mpn": {"value": mpn, "source": "sabina_jsonld"} if mpn else None,
            "sku": {"value": sku, "source": "sabina_jsonld"} if sku else None,
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
        "raw_data": {
            "product_url": final_url,
            "status_code": response.status_code,
            "jsonld_product": product,
        },
        "name": title,
        "brand": brand,
        "price": (
            f"{price:.2f}".replace(".", ",") + " €"
            if price is not None else ""
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
        # Stage 1: generic search discovery across the site's known search
        # parameter forms. Stage 2: sitemap fallback. Stage 3: authoritative
        # product-page validation. Nothing here depends on a specific product.
        candidate_urls = discover_from_search(session, query)

        sitemap_urls = discover_from_sitemap(session, query)
        seen_candidates = set(candidate_urls)
        for url in sitemap_urls:
            if url not in seen_candidates:
                seen_candidates.add(url)
                candidate_urls.append(url)
                if len(candidate_urls) >= MAX_CANDIDATES:
                    break

        results, seen = [], set()

        for url in candidate_urls[:MAX_CANDIDATES]:
            product = extract_product_page(session, url, query)
            if not product:
                continue

            key = (
                product.get("identity", {})
                .get("store_product_id", {})
                .get("value")
            ) or product.get("url")

            if key in seen:
                continue
            seen.add(key)

            packaging = product.get("attributes", {}).get("packaging_type") or {}
            packaging_value = (
                packaging.get("value")
                if isinstance(packaging, dict) else packaging
            )
            if packaging_value == "tester":
                continue

            searchable = norm(" ".join(str(x or "") for x in (
                product.get("name"), product.get("brand")
            )))
            if any(norm(term) in searchable for term in NON_PRODUCT_TERMS):
                continue

            results.append(product)

        return results
    finally:
        session.close()


def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generic Sabina scraper")
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
