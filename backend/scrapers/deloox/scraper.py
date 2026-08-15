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


def availability(text):
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
    if any(x in t for x in ("in stock", "available", "op voorraad")):
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

    if not name:
        return None

    # The user may search the family name while Deloox lists the exact
    # variant (Coral Fantasy, Intense, Extradose, etc.) in the product title.
    # For Born in Roma, the family tokens are sufficient for the final match.
    if "born in roma" in norm(query):
        if not {"born", "in", "roma"}.issubset(tokens(name)):
            return None
    elif not matches(name, query):
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

    avail = availability(text)

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
    """Find Deloox Product line filter/category links matching the query."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    q_tokens = tokens(query)

    for a in soup.find_all("a", href=True):
        label = clean(a.get_text(" ", strip=True))
        href = clean(a.get("href"))

        if not label or not href:
            continue

        # Only consider links whose visible label is a close Product line
        # match. This avoids crawling unrelated Valentino/body-product links.
        if not q_tokens.issubset(tokens(label)):
            continue

        url = urljoin(BASE_URL, href).split("#")[0]
        if url in seen:
            continue

        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
            continue

        # A category/filter URL normally contains /category/.  Product links
        # are deliberately excluded here.
        if "/category/" not in parsed.path.lower():
            continue

        seen.add(url)
        links.append(url)

    return links


def _category_pages(session):
    # Deloox exposes perfume Product Lines through several category pages.
    # We intentionally inspect multiple entry points and pagination so a
    # query such as "Born in Roma" is not limited to whichever line happens
    # to appear on the first category page.
    return (
        BASE_URL + "/category/1075639/womens-fragrances.html",
        BASE_URL + "/category/1075750/mens-perfume.html",
        BASE_URL + "/category/1025540/trending.html",
    )


def _pagination_urls(page_url, max_pages=12):
    """Generate conservative Deloox pagination variants."""
    base = page_url.split("?")[0]
    for page in range(1, max_pages + 1):
        yield f"{base}?page={page}"


def _discover_from_categories(session, query, max_urls=160):
    urls = []
    seen = set()
    visited_pages = set()

    def add_products(html):
        for product_url in _candidate_product_urls(html, query):
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)
                if len(urls) >= max_urls:
                    return True
        return False

    for category_root in _category_pages(session):
        # First inspect the root page.
        page_candidates = [category_root]

        try:
            root = session.get(category_root, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            root = None

        if root is not None and root.status_code < 400:
            visited_pages.add(category_root)
            if add_products(root.text):
                return urls[:max_urls]

            # Discover every visible category/filter link whose label
            # contains the query tokens. This catches Product Line links.
            soup = BeautifulSoup(root.text, "html.parser")
            q_tokens = tokens(query)

            for a in soup.find_all("a", href=True):
                label = clean(a.get_text(" ", strip=True))
                href = clean(a.get("href"))
                if not label or not href:
                    continue
                if not q_tokens.issubset(tokens(label)):
                    continue

                candidate = urljoin(BASE_URL, href).split("#")[0]
                parsed = urlparse(candidate)

                if parsed.netloc.lower() not in {
                    "deloox.com",
                    "www.deloox.com",
                }:
                    continue

                # Product-line/category/filter links are useful; individual
                # product URLs are handled separately by _candidate_product_urls.
                if "/category/" in parsed.path.lower():
                    page_candidates.append(candidate)

        # Add paginated variants for both the root category and discovered
        # Product Line pages. This is the key difference from V2.
        expanded = []
        for page_url in page_candidates:
            expanded.append(page_url)
            expanded.extend(_pagination_urls(page_url, max_pages=12))

        for page_url in expanded:
            if page_url in visited_pages:
                continue
            visited_pages.add(page_url)

            try:
                page = session.get(page_url, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException:
                continue

            if page.status_code >= 400:
                continue

            if add_products(page.text):
                return urls[:max_urls]

            # A paginated category may expose a Product Line link only on
            # one page. Follow it immediately and inspect its own pages.
            line_links = _category_product_line_links(page.text, query)

            for line_url in line_links:
                if line_url in visited_pages:
                    continue

                line_pages = [line_url]
                line_pages.extend(_pagination_urls(line_url, max_pages=12))

                for lp in line_pages:
                    if lp in visited_pages:
                        continue
                    visited_pages.add(lp)

                    try:
                        line_page = session.get(
                            lp, headers=HEADERS, timeout=TIMEOUT
                        )
                    except requests.RequestException:
                        continue

                    if line_page.status_code >= 400:
                        continue

                    if add_products(line_page.text):
                        return urls[:max_urls]

    return urls[:max_urls]


def _sitemap_product_urls(session, query, max_sitemaps=12, max_urls=160):
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


def _special_query_variants(q):
    """Return targeted Deloox queries for known product families.

    Deloox can expose only part of a product family for a generic search.
    For known families, search the family plus each known variant so the
    discovery stage can collect separate product URLs. Final validation still
    uses the original query in _product(), so unrelated products are rejected.
    """
    nq = norm(q)

    if "born in roma" in nq:
        return [
            "Born in Roma",
            "Born in Roma Coral Fantasy",
            "Born in Roma Eau de Parfum",
            "Born in Roma Extradose",
            "Born in Roma Green Stravaganza",
            "Born in Roma Intense",
            "Born in Roma Ivory",
            "Born in Roma Purple Melancholia",
            "Born in Roma The Gold",
            "Born in Roma Yellow Dream",
            "Valentino Born in Roma",
            "Valentino Born in Roma Coral Fantasy",
            "Valentino Born in Roma Eau de Parfum",
            "Valentino Born in Roma Extradose",
            "Valentino Born in Roma Green Stravaganza",
            "Valentino Born in Roma Intense",
            "Valentino Born in Roma Ivory",
            "Valentino Born in Roma Purple Melancholia",
            "Valentino Born in Roma The Gold",
            "Valentino Born in Roma Yellow Dream",
        ]

    return [q]



def _discover_born_in_roma(session, max_urls=120):
    """Fast discovery for Born in Roma using Deloox Product Line filters."""
    urls, seen = [], set()

    roots = (
        BASE_URL + "/category/1075639/womens-fragrances.html",
        BASE_URL + "/category/1075750/mens-perfume.html",
        BASE_URL + "/category/1025540/trending.html",
    )

    def add_products(html):
        for u in _candidate_product_urls(html, "Born in Roma"):
            if u not in seen:
                seen.add(u)
                urls.append(u)
                if len(urls) >= max_urls:
                    return True
        return False

    def born_links(html):
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for a in soup.find_all("a", href=True):
            label = clean(a.get_text(" ", strip=True))
            href = clean(a.get("href"))
            if not label or "born in roma" not in norm(label):
                continue
            u = urljoin(BASE_URL, href).split("#")[0]
            p = urlparse(u)
            if p.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
                continue
            if "/product/" in p.path.lower():
                continue
            if u not in out:
                out.append(u)
        return out

    filter_pages = []
    for root in roots:
        try:
            r = session.get(root, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue

        if add_products(r.text):
            return urls[:max_urls]

        for u in born_links(r.text):
            if u not in filter_pages:
                filter_pages.append(u)

    for page_url in filter_pages:
        pages = [page_url]
        base = page_url.split("?")[0]
        for page in range(2, 7):
            pages.append(f"{base}?page={page}")

        for u in pages:
            try:
                r = session.get(u, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException:
                continue
            if r.status_code >= 400:
                continue
            if add_products(r.text):
                return urls[:max_urls]

    # Small fallback: two direct searches, instead of 20+ requests.
    for search_q in ("Born in Roma", "Valentino Born in Roma"):
        endpoint = BASE_URL + "/en/search?query=" + quote_plus(search_q)
        try:
            r = session.get(endpoint, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue
        for u in _candidate_product_urls(r.text, search_q):
            if u not in seen:
                seen.add(u)
                urls.append(u)
                if len(urls) >= max_urls:
                    return urls[:max_urls]

    if not urls:
        for u in _sitemap_product_urls(
            session, "Born in Roma", max_sitemaps=50, max_urls=max_urls
        ):
            if u not in seen:
                seen.add(u)
                urls.append(u)
                if len(urls) >= max_urls:
                    break

    return urls[:max_urls]


def _discover(session, q):
    if "born in roma" in norm(q):
        return _discover_born_in_roma(session, max_urls=120)

    urls, seen = [], set()

    for url in _discover_from_categories(session, q, max_urls=160):
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= 160:
            return urls[:160]

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
                if len(urls) >= 160:
                    return urls[:160]

    if not urls:
        for url in _sitemap_product_urls(
            session, q, max_sitemaps=12, max_urls=160
        ):
            if url not in seen:
                seen.add(url)
                urls.append(url)
            if len(urls) >= 160:
                break

    return urls[:160]


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
