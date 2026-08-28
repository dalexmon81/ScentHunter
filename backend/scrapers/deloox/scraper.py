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
BASE_URL = "https://www.deloox.be"
TIMEOUT = 4
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


def availability(text, offer=None, soup=None):
    """Determine availability from product-specific signals only.

    IMPORTANT: do not scan the entire product page for ``out of stock``
    before checking structured data. Deloox can mention that phrase in
    unrelated/recommendation/filter content even when the current product
    is purchasable.

    Priority:
      1. JSON-LD Product/Offer availability (most reliable)
      2. product-page purchase controls / availability elements
      3. only then a tightly scoped textual fallback
    """

    # 1) Structured data. Schema.org normally exposes values such as
    # https://schema.org/InStock, OutOfStock, LimitedAvailability, etc.
    if isinstance(offer, dict):
        raw = clean(
            offer.get("availability")
            or offer.get("itemAvailability")
            or offer.get("availabilityStatus")
            or ""
        ).lower()
        if raw:
            if any(x in raw for x in (
                "outofstock", "out_of_stock", "soldout", "sold_out",
                "discontinued", "unavailable",
            )):
                return "out_of_stock"
            if any(x in raw for x in (
                "instock", "in_stock", "limitedavailability",
                "preorder", "pre_order",
            )):
                return "in_stock"

    # 2) Look only at elements that are likely to describe the current
    # product's purchase/stock state. Do NOT use soup.get_text() here.
    if soup is not None:
        scoped_parts = []

        selectors = [
            '[itemprop="availability"]',
            '[data-testid*="availability" i]',
            '[data-test*="availability" i]',
            '[class*="availability" i]',
            '[class*="stock" i]',
            '[class*="add-to-cart" i]',
            '[class*="buy" i]',
            'button[type="submit"]',
        ]

        seen_nodes = set()
        for selector in selectors:
            try:
                nodes = soup.select(selector)
            except Exception:
                nodes = []
            for node in nodes[:20]:
                marker = id(node)
                if marker in seen_nodes:
                    continue
                seen_nodes.add(marker)
                scoped_parts.append(
                    clean(node.get("content") or node.get("aria-label") or node.get_text(" ", strip=True))
                )

        scoped = norm(" ".join(x for x in scoped_parts if x))
        if scoped:
            if any(x in scoped for x in (
                "sold out", "out of stock", "not available",
                "currently unavailable", "unavailable",
            )):
                return "out_of_stock"
            if any(x in scoped for x in (
                "in stock", "available", "op voorraad", "add to cart",
                "add to basket", "buy now", "bestellen",
            )):
                return "in_stock"

    # 3) Deliberately conservative fallback. Only use the whole-page text
    # when there is NO structured/scoped signal at all. This prevents a
    # recommendation card saying "out of stock" from poisoning the product.
    t = norm(text)
    if any(x in t for x in (
        "sold out",
        "out of stock",
        "currently unavailable",
    )):
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

    avail = availability(text, offer=offer, soup=soup)

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


def _candidate_queries(query):
    """Build a small set of generic Deloox search queries.

    The original query is always first. Broadening is only used for discovery;
    the final product name is still validated by _product(), so this does not
    whitelist any specific perfume or brand.
    """
    q = clean(query)
    if not q:
        return []

    variants = [q]

    parts = q.split()
    # Generic fallback: remove common concentration/size words only.
    removable = {
        "parfum", "perfume", "eau", "de", "toilette", "toilette",
        "edt", "edp", "extrait", "extract"
    }
    broad = " ".join(p for p in parts if p.lower() not in removable).strip()
    if broad and broad.lower() != q.lower():
        variants.append(broad)

    out = []
    seen = set()
    for item in variants:
        key = norm(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _candidate_product_urls(
    html,
    query,
    discovery_query=None,
    accept_all_products=False,
):
    """Extract Deloox product URLs from every common HTML representation.

    Deloox may expose product links as normal anchors, data-* attributes,
    serialized JSON/JS, or escaped relative URLs. Discovery remains generic;
    final validation is always performed by _product() against the original
    query.
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    def add(raw_url):
        if not raw_url:
            return

        raw_url = clean(raw_url).replace("\\/", "/")
        if not raw_url:
            return

        # Some attributes contain JSON strings or a complete URL embedded in
        # surrounding text. Extract product URLs from those values as well.
        candidates = []
        if raw_url.startswith(("http://", "https://", "/")):
            candidates.append(raw_url)
        candidates.extend(
            re.findall(
                r'https?://(?:www\.)?deloox\.be[^"\'<>\s]+/product/[^"\'<>\s]+',
                raw_url,
                re.I,
            )
        )
        candidates.extend(
            re.findall(
                r'(?:(?:/)?(?:en/|it/|nl/)?product/[^"\'<>\s]+)',
                raw_url,
                re.I,
            )
        )

        for candidate in candidates:
            candidate = clean(candidate).replace("\\/", "/")
            if not candidate:
                continue

            url = urljoin(BASE_URL, candidate).split("#")[0].split("?")[0]

            try:
                parsed = urlparse(url)
            except Exception:
                continue

            if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
                continue

            if "/product/" not in parsed.path.lower():
                continue

            if url in seen:
                continue

            seen.add(url)
            found.append(url)

    # 1. Normal links.
    for a in soup.find_all("a", href=True):
        add(a.get("href"))

    # 2. Product URLs stored in data attributes or other serialized
    # attributes. This is important on Deloox pages where product cards are
    # hydrated client-side and do not expose the URL as a normal <a>.
    for tag in soup.find_all(True):
        for attr, value in tag.attrs.items():
            if isinstance(value, str):
                if attr.startswith(("data-", "href", "src")):
                    add(value)

    # 3. Raw HTML / JSON / JavaScript. Keep this deliberately generic.
    raw_html = html.replace("\\\\/", "/")
    patterns = [
        r'href\s*=\s*["\']((?:https?:)?//(?:www\.)?deloox\.be[^"\']*/product/[^"\']+)',
        r'["\']((?:/)?(?:en/|it/|nl/)?product/[^"\'\s<>]+)["\']',
        r'["\']((?:/)?(?:en/|it/|nl/)?product/[^"\'\s<>]+)',
        r'https?://(?:www\.)?deloox\.be[^"\'<>\s]+/product/[^"\'<>\s]+',
    ]

    for pattern in patterns:
        for raw_url in re.findall(pattern, raw_html, re.I):
            add(raw_url)

    return found


def _category_product_line_links(html, query):
    """Find generic Deloox category/Product-line URLs matching *query*.

    Deloox can expose filter links as normal anchors, data attributes, or
    serialized JSON/JS. We inspect all of those representations and never
    hard-code a product, brand, or category.
    """
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    q_tokens = tokens(query)

    def add(raw_url, label=""):
        raw_url = clean(raw_url).replace("\\/", "/")
        if not raw_url:
            return

        # A data attribute may contain a JSON blob with one or more URLs.
        raw_candidates = [raw_url]
        raw_candidates.extend(
            re.findall(
                r'(?:https?:)?//(?:www\.)?deloox\.be[^"\'<>\s]+/category/\d+/[^"\'<>\s]+',
                raw_url,
                re.I,
            )
        )
        raw_candidates.extend(
            re.findall(
                r'(?:(?:/)?(?:en/|it/|nl/)?category/\d+/[^"\'<>\s]+)',
                raw_url,
                re.I,
            )
        )

        for candidate in raw_candidates:
            candidate = clean(candidate).replace("\\/", "/")
            if not candidate:
                continue

            url = urljoin(BASE_URL, candidate).split("#")[0].split("?")[0]

            try:
                parsed = urlparse(url)
            except Exception:
                continue

            if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
                continue

            if "/category/" not in parsed.path.lower():
                continue

            slug_text = parsed.path.rsplit("/", 1)[-1]
            slug_text = re.sub(r"\.html$", "", slug_text, flags=re.I)

            if not (
                q_tokens.issubset(tokens(slug_text))
                or q_tokens.issubset(tokens(label))
            ):
                continue

            if url in seen:
                continue

            seen.add(url)
            links.append(url)

    # Normal visible links and their labels.
    for a in soup.find_all("a", href=True):
        add(a.get("href"), a.get_text(" ", strip=True))

    # Serialized/data attributes.
    for tag in soup.find_all(True):
        for attr, value in tag.attrs.items():
            if isinstance(value, str) and attr.startswith(("data-", "href")):
                add(value, tag.get_text(" ", strip=True))

    # Raw category URLs. Do not require .html: Deloox may serialize a route
    # without the final extension.
    raw = html.replace("\\\\/", "/")
    patterns = [
        r'(?:https?:)?//(?:www\.)?deloox\.be[^"\'<>\s]*/category/\d+/[^"\'<>\s]+',
        r'(?:(?:/)?(?:en/|it/|nl/)?category/\d+/[^"\'<>\s]+)',
    ]

    for pattern in patterns:
        for raw_url in re.findall(pattern, raw, re.I):
            add(raw_url)

    return links


def _category_pages(session=None):
    """Return generic Deloox fragrance category entry points.

    These are store taxonomy pages, not product-specific exceptions.
    The broad men's-fragrances category is important because Deloox can
    expose product-line filters there that are not present in the narrower
    men's-perfume page.
    """
    return (
        BASE_URL + "/category/1103659/fragrances.html",
        BASE_URL + "/category/1000054/mens-fragrances.html",
        BASE_URL + "/category/1075660/womens-perfume.html",
        BASE_URL + "/category/1075750/mens-perfume.html",
    )


def _category_page_variants(category_url, max_pages=8):
    """Add bounded pagination only to the broad men's fragrance category."""
    if not category_url.lower().endswith(
        "/category/1000054/mens-fragrances.html"
    ):
        return [category_url]

    return [
        category_url,
        *[
            category_url + "?page=" + str(page_number)
            for page_number in range(2, max_pages + 1)
        ],
    ]


def _discover_from_categories(session, query, max_urls=80):
    """Discover product-line/category pages without serial category delays.

    Deloox's taxonomy/filter links are normally present on the first page of
    each broad fragrance category. Fetch those entry points concurrently so a
    slow category cannot hold the whole store behind several sequential
    timeouts. Pagination is deliberately not used here; the filter/category
    discovery is the generic path, while product validation remains strict.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    category_urls = list(_category_pages(session))
    if not category_urls:
        return []

    def inspect_category(category_url):
        try:
            r = session.get(
                category_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            return []

        if r.status_code >= 400:
            return []

        product_line_links = _category_product_line_links(
            r.text,
            query,
        )

        candidate_pages = [
            (page_url, None)
            for page_url in product_line_links
        ]

        # If the filter is not exposed in this representation, inspect the
        # already downloaded category page itself. This costs no extra request.
        if not candidate_pages:
            candidate_pages = [(category_url, r.text)]

        local_urls = []
        local_seen = set()

        for page_url, page_html in candidate_pages:
            if page_html is None:
                try:
                    page = session.get(
                        page_url,
                        headers=HEADERS,
                        timeout=TIMEOUT,
                    )
                except requests.RequestException:
                    continue

                if page.status_code >= 400:
                    continue

                page_html = page.text

            for product_url in _candidate_product_urls(
                page_html,
                query,
                accept_all_products=True,
            ):
                if product_url in local_seen:
                    continue

                local_seen.add(product_url)
                local_urls.append(product_url)

                if len(local_urls) >= max_urls:
                    break

            if len(local_urls) >= max_urls:
                break

        return local_urls

    urls = []
    seen = set()

    max_workers = min(4, len(category_urls))
    executor = ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="deloox-category",
    )
    futures = [
        executor.submit(inspect_category, category_url)
        for category_url in category_urls
    ]

    try:
        for future in as_completed(futures):
            try:
                local_urls = future.result() or []
            except Exception:
                continue

            for url in local_urls:
                if url in seen:
                    continue

                seen.add(url)
                urls.append(url)

                if len(urls) >= max_urls:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return urls[:max_urls]
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

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
    """Generic Deloox discovery with direct search FIRST.

    The important rule is that Deloox must be attempted for every query.
    Category crawling is only a fallback because category pages can hang.
    No perfume/brand-specific rule belongs here.
    """
    urls = []
    seen = set()

    def add(url):
        if url and url not in seen and len(urls) < 24:
            seen.add(url)
            urls.append(url)

    # 1. PRIMARY: Deloox's own search surface.
    # Try the complete query first, then a small generic broadening.  The
    # original query is still validated later by _product(), so broadening
    # discovery cannot make unrelated products appear in the final results.
    discovery_queries = _candidate_queries(q)[:2]
    search_endpoints = (
        "/en/search?query=",
        "/en/search?search=",
        "/en/search?q=",
    )

    for discovery_query in discovery_queries:
        for route in search_endpoints:
            endpoint = BASE_URL + route + quote_plus(discovery_query)
            try:
                r = session.get(
                    endpoint,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException:
                continue

            if r.status_code >= 400:
                continue

            for product_url in _candidate_product_urls(
                r.text,
                q,
                discovery_query=discovery_query,
                accept_all_products=True,
            ):
                add(product_url)
                if len(urls) >= 24:
                    return urls[:24]

    # 2. SECONDARY: direct product sitemap.  This is still generic and does
    # not depend on a brand/category filter being rendered by Deloox.
    for product_url in _sitemap_product_urls(
        session,
        q,
        max_sitemaps=8,
        max_urls=24,
    ):
        add(product_url)
        if len(urls) >= 24:
            return urls[:24]

    # 3. FALLBACK: category -> brand -> product-line discovery.
    # This is deliberately last: the previous implementation put this first,
    # so a slow category request could prevent Deloox from ever reaching its
    # own search endpoint.
    for url in _discover_from_categories(
        session,
        q,
        max_urls=12,
    ):
        add(url)
        if len(urls) >= 24:
            return urls[:24]

    # 4. Last-resort search route used by older Deloox deployments.
    endpoint = BASE_URL + "/it/cerca?query=" + quote_plus(q)
    try:
        r = session.get(
            endpoint,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return urls[:24]

    if r.status_code < 400:
        for product_url in _candidate_product_urls(
            r.text,
            q,
            discovery_query=q,
            accept_all_products=True,
        ):
            add(product_url)
            if len(urls) >= 24:
                break

    return urls[:24]



def diagnose_search(session, query):
    """Deep Deloox discovery diagnostic; does not change normal search."""
    query = clean(query)
    report = {
        "query": query,
        "category_endpoints": [],
        "filter_urls": [],
        "candidate_urls": [],
        "validated_products": [],
        "search_fallback": [],
    }
    if not query:
        return report

    seen_candidates = set()
    for category_url in _category_pages():
        entry = {"url": category_url, "status": None, "filter_urls": [], "candidate_urls": []}
        try:
            r = session.get(category_url, headers=HEADERS, timeout=TIMEOUT)
            entry["status"] = r.status_code
        except requests.RequestException as exc:
            entry["error"] = str(exc)
            report["category_endpoints"].append(entry)
            continue
        report["category_endpoints"].append(entry)
        if r.status_code >= 400:
            continue
        filter_urls = _category_product_line_links(r.text, query)
        entry["filter_urls"] = filter_urls[:20]
        report["filter_urls"].extend(filter_urls)
        pages = [(category_url, False)] + [(url, True) for url in filter_urls]
        for page_url, filtered in pages:
            try:
                page = session.get(page_url, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException:
                continue
            if page.status_code >= 400:
                continue
            candidates = _candidate_product_urls(page.text, query, accept_all_products=filtered)
            entry["candidate_urls"].extend(candidates[:40])
            for url in candidates:
                if url in seen_candidates:
                    continue
                seen_candidates.add(url)
                report["candidate_urls"].append(url)
                if len(report["candidate_urls"]) >= 80:
                    break
            if len(report["candidate_urls"]) >= 80:
                break
        if len(report["candidate_urls"]) >= 80:
            break

    for url in report["candidate_urls"]:
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue
        item = _product(url, r.text, query)
        if item:
            report["validated_products"].append(item)

    for endpoint in (
        BASE_URL + "/en/search?query=" + quote_plus(query),
        BASE_URL + "/en/search?search=" + quote_plus(query),
        BASE_URL + "/en/search?q=" + quote_plus(query),
    ):
        try:
            r = session.get(endpoint, headers=HEADERS, timeout=TIMEOUT)
            report["search_fallback"].append({"url": endpoint, "status": r.status_code})
        except requests.RequestException as exc:
            report["search_fallback"].append({"url": endpoint, "error": str(exc)})
    return report

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
