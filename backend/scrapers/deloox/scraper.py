"""Deloox adapter for ScentHunter.

Discovery strategy:
- Prefer Deloox's current category pages and their Product line filter links.
- Fall back to Deloox search endpoints and sitemap discovery.
- Product pages are parsed through JSON-LD/page content.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "en-GB,en;q=0.9",
}


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(v).lower())).strip()


def tokens(v):
    return {x for x in norm(v).split() if len(x) > 1}


def matches(text, q):
    q_tokens = tokens(q)
    return bool(q_tokens) and q_tokens.issubset(tokens(text))


def size_ml(*values):
    m = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        " ".join(clean(x) for x in values),
        re.I,
    )
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    n *= 10 if m.group(2).lower() == "cl" else 1
    return int(n) if n.is_integer() else n


def concentration(*values):
    t = norm(" ".join(clean(x) for x in values))
    if re.search(r"\beau de toilette\b|\bedt\b", t):
        return "Eau de Toilette"
    if re.search(r"\beau de parfum\b|\bedp\b", t):
        return "Eau de Parfum"
    if re.search(r"\bextrait(?: de parfum)?\b", t):
        return "Extrait de Parfum"
    return None


def parse_price(v):
    s = clean(v)
    m = re.search(r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?", s)
    if not m:
        return None
    try:
        return round(float(m.group(1).replace(",", ".")), 2)
    except ValueError:
        return None


def availability(text="", offer_availability=None):
    """Normalize Deloox stock status.

    Deloox exposes the authoritative stock state in JSON-LD as
    offers.availability (usually schema.org/InStock or OutOfStock).
    The visible page text is only a fallback because it can contain
    generic words such as "available" that do not describe stock.
    """
    raw = clean(offer_availability)

    # JSON-LD is authoritative when present.
    if raw:
        t = norm(raw)
        if any(x in t for x in ("outofstock", "soldout", "unavailable")):
            return "out_of_stock"
        if any(x in t for x in ("instock", "available", "op voorraad")):
            return "in_stock"

    # Fallback to page text.
    t = norm(text)
    if any(
        x in t
        for x in (
            "sold out",
            "out of stock",
            "not available",
            "currently unavailable",
        )
    ):
        return "out_of_stock"
    if any(x in t for x in ("in stock", "op voorraad")):
        return "in_stock"
    return "unknown"


def _jsonld(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]
        while stack:
            x = stack.pop(0)
            if isinstance(x, list):
                stack.extend(x)
                continue
            if not isinstance(x, dict):
                continue
            if x.get("@type") == "Product" or "offers" in x:
                return x
            if isinstance(x.get("@graph"), list):
                stack.extend(x["@graph"])
    return {}


def _product(url, html, query):
    soup = BeautifulSoup(html, "html.parser")
    data = _jsonld(soup)

    h1 = soup.find("h1")
    name = clean(data.get("name")) or (
        clean(h1.get_text(" ", strip=True)) if h1 else ""
    )

    if not name or not matches(name, query):
        return None

    # Deloox product pages expose the product line separately.  Keep it
    # available as extra source context, but use the actual product name
    # for the strict query match.
    product_line = ""
    text = soup.get_text(" ", strip=True)
    m = re.search(
        r"product line\s+(.+?)(?:for whom|fragrance type|season|spray|article number)",
        text,
        re.I,
    )
    if m:
        product_line = clean(m.group(1))

    brand = data.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    offers = data.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    offer = next((x for x in offers if isinstance(x, dict)), {})

    price = parse_price(offer.get("price"))
    if price is None:
        price = parse_price(text)
    if price is None:
        return None

    gtin = clean(data.get("gtin13") or data.get("gtin") or "") or None
    mpn = clean(data.get("mpn") or "") or None
    sku = clean(data.get("sku") or "") or None

    image = data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None

    # Deloox puts the real stock state in offers.availability.
    # Do not infer "out of stock" merely because the page text is
    # ambiguous; pass the structured value to the normalizer first.
    offer_availability = offer.get("availability")
    avail = availability(text, offer_availability)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": clean(brand),
            "url": url,
            "image": urljoin(url, str(image)) if image else None,
        },
        "identity": {
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
            "mpn": {"value": mpn, "source": "jsonld"} if mpn else None,
            "sku": {"value": sku, "source": "jsonld"} if sku else None,
            "store_product_id": {
                "value": sku,
                "source": "deloox_sku",
            } if sku else None,
        },
        "attributes": {
            "size_ml": {
                "value": size_ml(name),
                "source": "product_name",
            } if size_ml(name) is not None else None,
            "concentration": {
                "value": concentration(name),
                "source": "product_name",
            } if concentration(name) else None,
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
            "product_line": {
                "value": product_line,
                "source": "deloox_page",
            } if product_line else None,
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": avail,
        },
        "provenance": {
            "source_page": url,
            "product_source": "jsonld_or_page",
        },
        "raw_data": {"jsonld": data},
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": avail == "in_stock",
    }


def _candidate_product_urls(html, query):
    """Extract Deloox product URLs from anchors, JSON and JS."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    def add(raw_url, context=""):
        if not raw_url:
            return

        raw_url = clean(raw_url).replace("\\/", "/")
        if raw_url.startswith(("javascript:", "mailto:", "#")):
            return

        url = urljoin(BASE_URL, raw_url).split("#")[0].split("?")[0]

        try:
            parsed = urlparse(url)
        except Exception:
            return

        if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
            return

        if "/product/" not in parsed.path.lower():
            return

        if url in seen:
            return

        # Search/category pages often put the product title in nearby text.
        # Accept the URL if either the URL slug or surrounding card text
        # contains the query tokens.
        haystack = f"{context} {url}"
        if matches(haystack, query):
            seen.add(url)
            found.append(url)

    for a in soup.find_all("a", href=True):
        add(a.get("href"), a.get_text(" ", strip=True))

    patterns = [
        r'https?://(?:www\.)?deloox\.com/[^"\'>\s]+/product/[^"\'>\s]+',
        r'["\']((?:/)?(?:en/)?product/[^"\']+)["\']',
    ]
    for pattern in patterns:
        for raw in re.findall(pattern, html, re.I):
            add(raw)

    return found


def _category_product_line_links(html, query):
    """Find Deloox Product-line category URLs matching the query.

    Deloox does not always render Product-line filters as normal <a> tags.
    Some are present only in serialized HTML/JSON or in data attributes.
    Therefore we inspect both parsed links and raw category URLs.
    """
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    q_tokens = tokens(query)

    def add(raw_url, label=""):
        raw_url = clean(raw_url).replace("\\/","/")
        if not raw_url:
            return

        url = urljoin(BASE_URL, raw_url).split("#")[0]
        try:
            parsed = urlparse(url)
        except Exception:
            return

        if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
            return
        if "/category/" not in parsed.path.lower():
            return

        # Prefer an exact match on the category slug, but also accept a
        # matching visible label when Deloox uses a localized slug.
        slug_text = parsed.path.rsplit("/", 1)[-1]
        if slug_text.lower().endswith(".html"):
            slug_text = slug_text[:-5]

        if not (
            q_tokens.issubset(tokens(slug_text))
            or q_tokens.issubset(tokens(label))
        ):
            return

        if url in seen:
            return
        seen.add(url)
        links.append(url)

    # Normal visible links.
    for a in soup.find_all("a", href=True):
        add(a.get("href"), a.get_text(" ", strip=True))

    # Deloox can expose filter/category links inside JSON, data attributes,
    # escaped URLs, or scripts without an <a> element.
    raw = html.replace("\\\\/", "/")
    patterns = [
        r'(?:"|\\\')((?:https?:)?//(?:www\\.)?deloox\\.com)?'
        r'(/(?:en/|it/|nl/)?category/\\d+/[^"\\\'<>\\s]+\\.html)',
        r'(?:"|\\\')((?:/)?(?:en/|it/|nl/)?category/\\d+/[^"\\\'<>\\s]+\\.html)(?:"|\\\')',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, raw, re.I):
            if isinstance(match, tuple):
                match = "".join(match)
            add(match)

    return links


def _category_pages(session):
    # These are Deloox's current perfume category URLs verified from the
    # public site structure. We use both genders because Born in Roma exists
    # as separate Uomo/Donna product lines.
    return (
        BASE_URL + "/category/1075660/womens-perfume.html",
        BASE_URL + "/category/1075750/mens-perfume.html",
    )


def _targeted_category_seed_urls(query):
    """
    Deloox sometimes exposes a product line on a dedicated category page
    without exposing that category URL through the sitemap used by the
    scraper. Keep a small, query-aware seed map for these cases, then fall
    back to the broader brand category pages.
    """
    q = norm(query)

    seeds = []

    # Liquid Brun has a dedicated Deloox category page.
    if "liquid brun" in q:
        seeds.append(
            BASE_URL + "/en/category/1132834/liquid-brun.html"
        )

    # French Avenue's category index exposes both the regular Liquid Brun
    # 100 ml and the Limited Edition 150 ml, plus other French Avenue lines.
    if "liquid brun" in q or "french avenue" in q:
        seeds.extend(
            [
                BASE_URL + "/en/category/1121334/french-avenue-mens-fragrances.html",
                BASE_URL + "/en/category/1121322/french-avenue-fragrances.html",
            ]
        )

    # De-duplicate while preserving order.
    seen = set()
    return [u for u in seeds if not (u in seen or seen.add(u))]


def _discover_from_categories(session, query, max_urls=80):
    urls = []
    seen = set()

    for category_url in _category_pages(session):
        try:
            r = session.get(category_url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            continue

        # First, discover the exact Product line links exposed by Deloox.
        product_line_links = _category_product_line_links(r.text, query)

        # If Deloox's current HTML does not expose a filter link, also inspect
        # the current category page itself for product cards.
        candidate_pages = product_line_links or [category_url]

        for page_url in candidate_pages:
            try:
                page = session.get(page_url, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException:
                continue

            if page.status_code >= 400:
                continue

            for product_url in _candidate_product_urls(page.text, query):
                if product_url not in seen:
                    seen.add(product_url)
                    urls.append(product_url)
                    if len(urls) >= max_urls:
                        return urls[:max_urls]

    return urls[:max_urls]


def _sitemap_category_urls(session, query, max_sitemaps=12, max_urls=30):
    """Discover dedicated Deloox category/Product-line pages from sitemaps."""
    query_tokens = tokens(query)
    if not query_tokens:
        return []

    sitemap_roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )

    pending = list(sitemap_roots)
    seen_sitemaps = set()
    category_urls = []
    seen_categories = set()

    def fetch_xml(url):
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            return None
        if r.status_code >= 400:
            return None
        body = r.text.lstrip()
        ctype = (r.headers.get("content-type") or "").lower()
        if "xml" not in ctype and not body.startswith(
            ("<?xml", "<urlset", "<sitemapindex")
        ):
            return None
        return r.text

    while (
        pending
        and len(seen_sitemaps) < max_sitemaps
        and len(category_urls) < max_urls
    ):
        sitemap_url = pending.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        xml = fetch_xml(sitemap_url)
        if not xml:
            continue

        soup = BeautifulSoup(xml, "xml")
        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())
            if not value:
                continue

            low = value.lower()
            if "/category/" in low and low.endswith(".html"):
                slug = low.rsplit("/", 1)[-1][:-5]
                if query_tokens.issubset(tokens(slug)):
                    if value not in seen_categories:
                        seen_categories.add(value)
                        category_urls.append(value)
                        if len(category_urls) >= max_urls:
                            break
            elif low.endswith(".xml") or "sitemap" in low:
                if value not in seen_sitemaps:
                    pending.append(value)

    return category_urls[:max_urls]


def _sitemap_product_urls(session, query, max_sitemaps=12, max_urls=80):
    query_tokens = tokens(query)
    if not query_tokens:
        return []

    sitemap_roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )

    pending = list(sitemap_roots)
    seen_sitemaps = set()
    product_urls = []
    seen_products = set()

    def fetch_xml(url):
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            return None
        if r.status_code >= 400:
            return None

        ctype = (r.headers.get("content-type") or "").lower()
        body = r.text.lstrip()
        if "xml" not in ctype and not body.startswith(
            ("<?xml", "<urlset", "<sitemapindex")
        ):
            return None
        return r.text

    while (
        pending
        and len(seen_sitemaps) < max_sitemaps
        and len(product_urls) < max_urls
    ):
        sitemap_url = pending.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        xml = fetch_xml(sitemap_url)
        if not xml:
            continue

        soup = BeautifulSoup(xml, "xml")

        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())
            if not value:
                continue

            low = value.lower()

            if "/product/" in low:
                if query_tokens.issubset(tokens(value)):
                    if value not in seen_products:
                        seen_products.add(value)
                        product_urls.append(value)
                        if len(product_urls) >= max_urls:
                            break
            elif low.endswith(".xml") or "sitemap" in low:
                if value not in seen_sitemaps:
                    pending.append(value)

    return product_urls


def _discover(session, q):
    urls = []
    seen = set()

    # PRIMARY: current Deloox category/Product-line structure.
    for url in _discover_from_categories(session, q, max_urls=80):
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= 80:
            return urls[:80]

    # SECONDARY: targeted Deloox category seeds.
    # Some dedicated Product-line pages are real and indexed by Deloox but
    # are not exposed by the sitemap endpoints we can reach from the scraper.
    # Check those exact category pages before relying on sitemap discovery.
    for category_url in _targeted_category_seed_urls(q):
        try:
            page = session.get(
                category_url, headers=HEADERS, timeout=TIMEOUT
            )
        except requests.RequestException:
            continue

        if page.status_code >= 400:
            continue

        for product_url in _candidate_product_urls(page.text, q):
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)
                if len(urls) >= 80:
                    return urls[:80]

    # TERTIARY: dedicated Product-line category pages discovered from sitemap.
    # This is important for other product lines whose category URLs are
    # exposed in Deloox's sitemap.
    for category_url in _sitemap_category_urls(
        session, q, max_sitemaps=12, max_urls=30
    ):
        try:
            page = session.get(
                category_url, headers=HEADERS, timeout=TIMEOUT
            )
        except requests.RequestException:
            continue

        if page.status_code >= 400:
            continue

        for product_url in _candidate_product_urls(page.text, q):
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)
                if len(urls) >= 80:
                    return urls[:80]

    # QUATERNARY: legacy/current search endpoints, retained as fallback.
    endpoints = [
        BASE_URL + "/en/search?query=" + quote_plus(q),
        BASE_URL + "/en/search?search=" + quote_plus(q),
        BASE_URL + "/en?search=" + quote_plus(q),
        BASE_URL + "/en/search?q=" + quote_plus(q),
    ]

    for endpoint in endpoints:
        try:
            r = session.get(endpoint, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            continue

        for url in _candidate_product_urls(r.text, q):
            if url not in seen:
                seen.add(url)
                urls.append(url)

        if len(urls) >= 80:
            return urls[:80]

    # LAST RESORT: direct product sitemap discovery.
    if not urls:
        for url in _sitemap_product_urls(
            session, q, max_sitemaps=12, max_urls=80
        ):
            if url not in seen:
                seen.add(url)
                urls.append(url)
            if len(urls) >= 80:
                break

    return urls[:80]


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    results = []
    seen = set()

    try:
        for url in _discover(session, query):
            try:
                r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException:
                continue

            if r.status_code >= 400:
                continue

            item = _product(url, r.text, query)
            if not item:
                continue

            sku_value = None
            sku = item["identity"].get("sku")
            if sku:
                sku_value = sku.get("value")

            key = (url, sku_value)

            if key in seen:
                continue

            seen.add(key)
            results.append(item)

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

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
