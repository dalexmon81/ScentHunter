import json
import re
import unicodedata
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.nl"
TIMEOUT = 15
MAX_DISCOVERY_PAGES = 8
MAX_CANDIDATES = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/json;q=0.8,*/*;q=0.7"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
    "spray", "ml", "for", "by", "pour", "the", "and",
}

NON_PRODUCT_TERMS = {
    "gift set", "giftset", "coffret", "bundle", "deodorant",
    "deo spray", "shower gel", "body lotion", "after shave",
    "aftershave", "travel set", "discovery set", "miniature set",
    "sample", "samples", "decant",
}

PRODUCT_URL_RE = re.compile(
    r"/(?:product|producto|produit|produkt)/(\d+)/",
    re.I,
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    text = unicodedata.normalize("NFKD", clean(value).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def query_tokens(query):
    return [
        token for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS and len(token) > 1
    ]


def product_url_id(url):
    match = PRODUCT_URL_RE.search(url or "")
    return match.group(1) if match else None


def is_product_url(url):
    return product_url_id(url) is not None


def token_match(text, query):
    wanted = query_tokens(query)
    if not wanted:
        return False

    haystack = set(norm(text).split())
    return all(token in haystack for token in wanted)


def score_candidate(text, query):
    wanted = query_tokens(query)
    if not wanted:
        return 0.0

    haystack = set(norm(text).split())
    exact = sum(token in haystack for token in wanted) / len(wanted)

    compact_query = "".join(wanted)
    compact_text = "".join(norm(text).split())
    compact = 0.5 if compact_query and compact_query in compact_text else 0.0

    return exact + compact


def extract_product_links(soup, query):
    candidates = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        absolute = urljoin(BASE_URL, href).split("?")[0].rstrip("/")

        if not is_product_url(absolute):
            continue

        if absolute in seen:
            continue

        # Product cards normally contain the product name in the anchor,
        # a parent card, or a title/aria-label attribute. We inspect only
        # a bounded local context, never the whole page.
        contexts = [
            anchor.get("title"),
            anchor.get("aria-label"),
            anchor.get_text(" ", strip=True),
        ]

        parent = anchor
        for _ in range(4):
            parent = parent.parent if parent is not None else None
            if parent is None:
                break
            contexts.append(parent.get_text(" ", strip=True))

        context = clean(" ".join(contexts))

        if token_match(context, query):
            seen.add(absolute)
            candidates.append(
                (absolute, score_candidate(context, query))
            )

    candidates.sort(key=lambda item: item[1], reverse=True)
    return [url for url, _ in candidates[:MAX_CANDIDATES]]


def search_pages(session, query):
    """
    Deloox exposes its catalogue through normal HTML search/category pages.
    We try a small set of generic search routes used by common Deloox
    deployments. Every route is bounded; there is no recursive crawling.
    """
    encoded = quote_plus(query)

    routes = [
        f"/catalogsearch/result/?q={encoded}",
        f"/zoeken/?q={encoded}",
        f"/search?q={encoded}",
        f"/zoeken?q={encoded}",
    ]

    found = []
    seen = set()

    for route in routes:
        if len(found) >= MAX_CANDIDATES:
            break

        try:
            response = session.get(
                urljoin(BASE_URL, route),
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if response.status_code != 200:
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        for url in extract_product_links(soup, query):
            if url not in seen:
                seen.add(url)
                found.append(url)
                if len(found) >= MAX_CANDIDATES:
                    break

    return found


def category_from_search_result(soup, query):
    """
    Some Deloox pages expose a product-line/category result instead of
    product cards. We collect only category URLs whose visible text matches
    the query. Category URLs are never returned as products.
    """
    categories = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        absolute = urljoin(BASE_URL, href).split("?")[0].rstrip("/")

        if not re.search(
            r"/(?:categorie|category|categoria|catégorie|kategorie)/",
            absolute,
            re.I,
        ):
            continue

        text = clean(
            anchor.get("title")
            or anchor.get("aria-label")
            or anchor.get_text(" ", strip=True)
        )

        if not token_match(text + " " + absolute, query):
            continue

        if absolute not in seen:
            seen.add(absolute)
            categories.append(absolute)

    return categories[:4]


def discover_from_category(session, category_url, query):
    """
    A category is a bounded discovery source only. We inspect the category
    page once and validate its product links individually. We never follow
    arbitrary internal links and never recurse through categories.
    """
    try:
        response = session.get(
            category_url,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return []

    if response.status_code != 200:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    return extract_product_links(soup, query)


def extract_jsonld_products(soup):
    products = []

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop(0)

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]

            if any(str(t).lower() == "product" for t in types):
                products.append(item)

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)

    return products


def parse_price(value):
    if value in (None, ""):
        return None

    raw = clean(value).replace("€", " ")

    match = re.search(
        r"(?<![\d.,])(\d{1,5}(?:[.,]\d{1,2})?)",
        raw,
    )
    if not match:
        return None

    number = match.group(1)

    if "." in number and "," in number:
        number = number.replace(".", "").replace(",", ".")
    else:
        number = number.replace(",", ".")

    try:
        value = float(number)
    except ValueError:
        return None

    return round(value, 2) if value > 0 else None


def extract_price(soup, product_data):
    offers = product_data.get("offers") if isinstance(product_data, dict) else None
    offers_list = offers if isinstance(offers, list) else [offers]

    for offer in offers_list:
        if isinstance(offer, dict):
            price = parse_price(offer.get("price"))
            if price is not None:
                return price

    for selector in (
        '[itemprop="price"]',
        '[data-price]',
        '[class*="price"]',
    ):
        for node in soup.select(selector):
            for value in (
                node.get("content"),
                node.get("data-price"),
                node.get_text(" ", strip=True),
            ):
                price = parse_price(value)
                if price is not None:
                    return price

    return None


def extract_brand(soup, product_data):
    if isinstance(product_data, dict):
        brand = product_data.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        if brand:
            return clean(brand)

    node = soup.select_one('[itemprop="brand"]')
    if node:
        return clean(node.get("content") or node.get_text(" ", strip=True))

    # Deloox product pages expose the brand as a labelled field.
    text = soup.get_text(" ", strip=True)
    match = re.search(
        r"\b(?:merk|brand)\s+([A-ZÀ-ÖØ-Ý][^|]{1,80}?)(?:\s+Productlijn\b|\s+voor wie\b)",
        text,
        re.I,
    )
    return clean(match.group(1)) if match else ""


def extract_size(text):
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        text,
        re.I,
    )
    if not match:
        return None

    value = float(match.group(1).replace(",", "."))

    if match.group(2).lower() == "cl":
        value *= 10

    return int(value) if value.is_integer() else value


def extract_concentration(text):
    value = norm(text)

    if re.search(r"\bextrait de parfum\b|\bextrait\b", value):
        return "Extrait de Parfum"
    if re.search(r"\beau de parfum\b|\bedp\b", value):
        return "Eau de Parfum"
    if re.search(r"\beau de toilette\b|\bedt\b", value):
        return "Eau de Toilette"
    if re.search(r"\beau de cologne\b|\bedc\b", value):
        return "Eau de Cologne"
    if re.search(r"\bparfum\b", value):
        return "Parfum"

    return None


def extract_image(soup, product_data, url):
    image = product_data.get("image") if isinstance(product_data, dict) else None

    if isinstance(image, list):
        image = image[0] if image else None

    if image:
        return urljoin(url, str(image))

    meta = soup.select_one('meta[property="og:image"]')
    if meta and meta.get("content"):
        return urljoin(url, meta["content"])

    return None


def extract_availability(product_data):
    offers = product_data.get("offers") if isinstance(product_data, dict) else None
    offers_list = offers if isinstance(offers, list) else [offers]

    for offer in offers_list:
        if not isinstance(offer, dict):
            continue

        value = norm(offer.get("availability"))

        if "instock" in value:
            return "in_stock"
        if "outofstock" in value:
            return "out_of_stock"

    return "unknown"


def extract_product(session, url, query):
    if not is_product_url(url):
        return None

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    h1 = soup.find("h1")
    name = clean(h1.get_text(" ", strip=True)) if h1 else ""

    if not name:
        return None

    jsonld = extract_jsonld_products(soup)
    product_data = jsonld[0] if jsonld else {}

    brand = extract_brand(soup, product_data)
    identity_text = clean(f"{brand} {name}")

    # The URL is only a candidate. The product page itself must match.
    if not token_match(identity_text, query):
        return None

    normalized_identity = norm(identity_text)

    if not any(
        norm(term) in normalized_identity
        for term in NON_PRODUCT_TERMS
    ):
        pass
    elif not all(
        norm(term) in norm(query)
        for term in NON_PRODUCT_TERMS
        if norm(term) in normalized_identity
    ):
        return None

    price = extract_price(soup, product_data)
    if price is None:
        return None

    size = extract_size(identity_text)
    concentration = extract_concentration(identity_text)

    gtin = product_data.get("gtin") or product_data.get("gtin13")
    sku = product_data.get("sku")
    mpn = product_data.get("mpn")
    store_id = product_url_id(url)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand or None,
            "url": url,
            "image": extract_image(soup, product_data, url),
        },
        "identity": {
            "gtin": {"value": str(gtin), "source": "jsonld"} if gtin else None,
            "mpn": {"value": str(mpn), "source": "jsonld"} if mpn else None,
            "sku": {"value": str(sku), "source": "jsonld"} if sku else None,
            "store_product_id": {
                "value": store_id,
                "source": "product_url",
            } if store_id else None,
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {
                "value": size,
                "source": "product_title",
            } if size is not None else None,
            "concentration": {
                "value": concentration,
                "source": "product_title",
            } if concentration else None,
            "gender": {
                "value": "unknown",
                "source": "not_explicit",
            },
            "packaging_type": {
                "value": "product",
                "source": "default",
            },
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": extract_availability(product_data),
        },
        "provenance": {
            "source_page": url,
            "name_source": "h1",
            "brand_source": "jsonld_or_html",
            "price_source": "jsonld_or_html",
        },
        "raw_data": {
            "jsonld_product": product_data,
        },
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": extract_availability(product_data) == "in_stock",
    }


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        candidates = search_pages(session, query)

        # A search route can redirect to a category or product-line page.
        # Inspect only that returned page, never arbitrary site links.
        category_candidates = []

        encoded = quote_plus(query)
        routes = [
            f"/catalogsearch/result/?q={encoded}",
            f"/zoeken/?q={encoded}",
            f"/search?q={encoded}",
            f"/zoeken?q={encoded}",
        ]

        for route in routes[:MAX_DISCOVERY_PAGES]:
            try:
                response = session.get(
                    urljoin(BASE_URL, route),
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
            except requests.RequestException:
                continue

            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            category_candidates.extend(
                category_from_search_result(soup, query)
            )

        seen = set(candidates)

        for category_url in category_candidates[:4]:
            for url in discover_from_category(
                session,
                category_url,
                query,
            ):
                if url not in seen:
                    seen.add(url)
                    candidates.append(url)

        results = []

        for url in candidates[:MAX_CANDIDATES]:
            item = extract_product(session, url, query)
            if item:
                results.append(item)

        unique = []
        result_seen = set()

        for item in results:
            key = (
                item.get("url", "").lower(),
                norm(item.get("name", "")),
            )
            if key in result_seen:
                continue
            result_seen.add(key)
            unique.append(item)

        return unique

    finally:
        session.close()


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generic Deloox store adapter"
    )
    parser.add_argument("query")
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
