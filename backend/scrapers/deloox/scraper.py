import json
import re
import unicodedata
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.nl"
SITEMAP_URL = BASE_URL + "/sitemap.xml"
TIMEOUT = 15
MAX_SITEMAP_FILES = 40
MAX_SITEMAP_URLS = 200000
MAX_CANDIDATES = 40

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
    "spray", "ml", "for", "by", "pour", "the", "and", "avec",
    "met", "van", "des", "du", "da", "del",
}

NON_PRODUCT_TERMS = {
    "gift set", "giftset", "set regalo", "coffret", "bundle",
    "deodorant", "deo spray", "shower gel", "body lotion",
    "after shave", "aftershave", "travel set", "discovery set",
    "miniature set", "miniatures", "sample", "samples", "decant",
}

PRODUCT_PATH_RE = re.compile(
    r"/(?:product|producto|produit|produkt)/\d+/",
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


def tokens(value):
    return [
        t for t in norm(value).split()
        if len(t) > 1 and t not in IGNORED_QUERY_WORDS
    ]


def query_has_explicit_non_product_term(query):
    q = norm(query)
    return any(norm(term) in q for term in NON_PRODUCT_TERMS)


def product_url(url):
    return bool(PRODUCT_PATH_RE.search(url or ""))


def extract_xml_urls(text):
    urls = []
    try:
        soup = BeautifulSoup(text or "", "xml")
        for loc in soup.find_all("loc"):
            value = clean(loc.get_text(strip=True))
            if value:
                urls.append(value)
    except Exception:
        for match in re.finditer(r"<loc>\s*([^<]+?)\s*</loc>", text or "", re.I):
            urls.append(clean(match.group(1)))
    return urls


def get_sitemap_urls(session):
    """
    Reads the sitemap index and child sitemaps without crawling site pages.
    Product/category URL discovery is therefore bounded to sitemap contents.
    """
    try:
        response = session.get(SITEMAP_URL, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return []

    first = extract_xml_urls(response.text)
    if not first:
        return []

    sitemap_children = [
        u for u in first
        if re.search(r"(?:sitemap|\.xml(?:\.gz)?)", u, re.I)
        and not product_url(u)
    ]

    if not sitemap_children:
        return first[:MAX_SITEMAP_URLS]

    output = []
    seen = set()

    for child in sitemap_children[:MAX_SITEMAP_FILES]:
        if child in seen:
            continue
        seen.add(child)

        try:
            response = session.get(child, headers=HEADERS, timeout=TIMEOUT)
            if response.status_code != 200:
                continue
        except requests.RequestException:
            continue

        for url in extract_xml_urls(response.text):
            if url not in seen:
                seen.add(url)
                output.append(url)
                if len(output) >= MAX_SITEMAP_URLS:
                    return output

    return output


def url_search_text(url):
    path = unquote(url or "")
    path = re.sub(r"[-_/]+", " ", path)
    return norm(path)


def query_matches_text(text, query):
    qtokens = tokens(query)
    if not qtokens:
        return False

    haystack = norm(text)
    return all(token in haystack.split() for token in qtokens)


def candidate_score(url, query):
    """
    Score is used only to order already discovered candidates.
    It never accepts a candidate by itself.
    """
    qtokens = tokens(query)
    if not qtokens:
        return 0.0

    text = url_search_text(url)
    parts = set(text.split())
    exact = sum(1 for token in qtokens if token in parts)

    compact_q = "".join(qtokens)
    compact_text = "".join(text.split())
    compact_bonus = 1.0 if compact_q and compact_q in compact_text else 0.0

    return exact / len(qtokens) + compact_bonus * 0.5


def discover_from_sitemap(session, query):
    urls = get_sitemap_urls(session)
    product_candidates = []
    category_candidates = []

    for url in urls:
        if product_url(url):
            text = url_search_text(url)
            if query_matches_text(text, query):
                product_candidates.append(url)
        elif re.search(r"/(?:category|categorie|categoria|catégorie|kategorie)/", url, re.I):
            text = url_search_text(url)
            if query_matches_text(text, query):
                category_candidates.append(url)

    product_candidates.sort(
        key=lambda u: candidate_score(u, query),
        reverse=True,
    )
    category_candidates.sort(
        key=lambda u: candidate_score(u, query),
        reverse=True,
    )

    return product_candidates[:MAX_CANDIDATES], category_candidates[:10]


def parse_price(value):
    raw = clean(value).replace("€", " ")
    match = re.search(r"(?<![\d.,])(\d{1,4}(?:[.,]\d{1,2})?)\s*$", raw)
    if not match:
        return None

    value = match.group(1)
    if "." in value and "," in value:
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", ".")

    try:
        return round(float(value), 2)
    except ValueError:
        return None


def extract_price(soup):
    # Prefer structured product offers.
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

            offers = item.get("offers")
            offers = offers if isinstance(offers, list) else [offers]

            for offer in offers:
                if isinstance(offer, dict):
                    value = parse_price(offer.get("price"))
                    if value is not None:
                        return value

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)

    # Generic semantic price elements.
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


def extract_brand(soup, product_data=None):
    if isinstance(product_data, dict):
        brand = product_data.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        if brand:
            return clean(brand)

    node = soup.select_one('[itemprop="brand"]')
    if node:
        return clean(node.get("content") or node.get_text(" ", strip=True))

    return ""


def jsonld_product_items(soup):
    items = []

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
                items.append(item)

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)

    return items


def page_is_product(soup, url):
    if not product_url(url):
        return False

    h1 = soup.find("h1")
    if not h1:
        return False

    name = clean(h1.get_text(" ", strip=True))
    if not name:
        return False

    products = jsonld_product_items(soup)
    if products:
        return True

    # Deloox product pages expose a product path + H1 even when JSON-LD
    # is absent or incomplete. Price is the second required signal.
    return extract_price(soup) is not None


def extract_product(session, url, query):
    try:
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    if not page_is_product(soup, url):
        return None

    h1 = soup.find("h1")
    name = clean(h1.get_text(" ", strip=True)) if h1 else ""

    products = jsonld_product_items(soup)
    product_data = products[0] if products else {}

    brand = extract_brand(soup, product_data)
    combined = f"{brand} {name}".strip()

    # Final identity validation happens on the product page, not on the URL.
    if not query_matches_text(combined, query):
        return None

    if query_has_explicit_non_product_term(query):
        pass
    else:
        normalized_name = norm(combined)
        if any(norm(term) in normalized_name for term in NON_PRODUCT_TERMS):
            return None

    price = parse_price(product_data.get("offers", {}).get("price")) \
        if isinstance(product_data.get("offers"), dict) else None
    if price is None:
        price = extract_price(soup)

    if price is None:
        return None

    image = None
    image_value = product_data.get("image")
    if isinstance(image_value, list):
        image_value = image_value[0] if image_value else None
    if image_value:
        image = urljoin(url, str(image_value))
    else:
        meta = soup.select_one('meta[property="og:image"]')
        if meta:
            image = urljoin(url, meta.get("content") or "")

    availability = "unknown"
    offers = product_data.get("offers")
    if isinstance(offers, dict):
        availability_value = norm(offers.get("availability"))
        if "instock" in availability_value:
            availability = "in_stock"
        elif "outofstock" in availability_value:
            availability = "out_of_stock"

    size = None
    size_match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:ml|cl)\b",
        combined,
        re.I,
    )
    if size_match:
        size = float(size_match.group(1).replace(",", "."))
        if size_match.group(0).lower().endswith("cl"):
            size *= 10
        if size.is_integer():
            size = int(size)

    gtin = product_data.get("gtin") or product_data.get("gtin13")
    sku = product_data.get("sku")
    mpn = product_data.get("mpn")

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand or None,
            "url": url,
            "image": image,
        },
        "identity": {
            "gtin": {"value": str(gtin), "source": "jsonld"} if gtin else None,
            "mpn": {"value": str(mpn), "source": "jsonld"} if mpn else None,
            "sku": {"value": str(sku), "source": "jsonld"} if sku else None,
            "store_product_id": {
                "value": re.search(PRODUCT_PATH_RE, url).group(0).split("/")[2]
                if re.search(PRODUCT_PATH_RE, url)
                else None,
                "source": "product_url",
            },
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {"value": size, "source": "product_title"} if size is not None else None,
            "concentration": None,
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": availability,
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
        "available": availability == "in_stock",
    }


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        product_candidates, category_candidates = discover_from_sitemap(
            session,
            query,
        )

        results = []
        seen = set()

        # Direct product URLs are the preferred discovery path.
        for url in product_candidates:
            if url in seen:
                continue
            seen.add(url)

            item = extract_product(session, url, query)
            if item:
                results.append(item)

        # Category pages are only a bounded fallback. We do not crawl links
        # recursively; only product URLs found on the matching category page
        # are considered, then each candidate is validated independently.
        for category_url in category_candidates:
            if len(results) >= MAX_CANDIDATES:
                break

            try:
                response = session.get(
                    category_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException:
                continue

            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            category_product_urls = []
            category_seen = set()

            for anchor in soup.find_all("a", href=True):
                candidate = urljoin(category_url, anchor.get("href", "")).split("?")[0]
                if not product_url(candidate):
                    continue
                if candidate in category_seen:
                    continue
                category_seen.add(candidate)

                text = clean(
                    anchor.get("title")
                    or anchor.get_text(" ", strip=True)
                )
                if query_matches_text(text + " " + candidate, query):
                    category_product_urls.append(candidate)

            for url in category_product_urls[:MAX_CANDIDATES]:
                if url in seen:
                    continue
                seen.add(url)

                item = extract_product(session, url, query)
                if item:
                    results.append(item)

        # Final deterministic deduplication.
        unique = []
        result_seen = set()

        for item in results:
            key = (
                norm(item.get("name")),
                item.get("url", "").lower(),
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
