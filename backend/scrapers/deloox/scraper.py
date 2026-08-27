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
READER_BASE = "https://r.jina.ai/"
TIMEOUT = 10
READER_TIMEOUT = 15
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



def _reader_get(session, url):
    """Generic read-only fallback for Deloox pages blocked to normal HTTP."""
    try:
        response = session.get(
            READER_BASE + url,
            headers={
                "User-Agent": "ScentHunter/1.0",
                "Accept": "text/plain,text/markdown,text/html;q=0.9,*/*;q=0.8",
            },
            timeout=READER_TIMEOUT,
        )
        response.raise_for_status()
        return response.text or ""
    except requests.RequestException:
        return ""


def _reader_product_urls(text, query):
    """Extract Deloox product URLs from reader/markdown output."""
    found = []
    seen = set()

    patterns = (
        r'https?://(?:www\.)?deloox\.com/[^\s<>\]\)"\']+/product/[^\s<>\]\)"\']+',
        r'\]\((https?://(?:www\.)?deloox\.com/[^\s\)]+/product/[^\s\)]+)\)',
        r'\]\((/[^)\s]+/product/[^)\s]+)\)',
    )

    for pattern in patterns:
        for raw in re.findall(pattern, text or "", re.I):
            url = urljoin(BASE_URL, clean(raw)).split("#")[0].split("?")[0]
            try:
                parsed = urlparse(url)
            except Exception:
                continue
            if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
                continue
            if "/product/" not in parsed.path.lower():
                continue
            if url in seen:
                continue
            seen.add(url)
            found.append(url)

    return found



def _candidate_product_urls(
    html,
    query,
    discovery_query=None,
    accept_all_products=False,
):
    """Extract Deloox product URLs from anchors, JSON and JS.

    Discovery may use a broader query, but final matching is performed by
    _product() against the original query. Therefore this function never
    creates a product result by itself.
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()
    discovery_query = clean(discovery_query or query)

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

        # During search discovery we want candidate URLs, not final matches.
        # _product() performs the authoritative product-name validation later.
        if not accept_all_products:
            haystack = f"{context} {url}"
            if not matches(haystack, query):
                return

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
        path_low = parsed.path.lower()
        query_low = parsed.query.lower()

        # Deloox uses both dedicated /category/... pages and filter links
        # carrying the selected product line in the query string.
        if "/category/" not in path_low and "filters" not in query_low:
            return

        # Prefer an exact match on the category slug, but also accept a
        # matching visible label when Deloox uses a localized slug.
        slug_text = parsed.path.rsplit("/", 1)[-1]
        if slug_text.lower().endswith(".html"):
            slug_text = slug_text[:-5]

        label_tokens = tokens(label)
        slug_tokens = tokens(slug_text)
        query_tokens_text = tokens(parsed.query.replace("%20", " "))

        if not (
            q_tokens.issubset(slug_tokens)
            or q_tokens.issubset(label_tokens)
            or q_tokens.issubset(query_tokens_text)
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
        BASE_URL + "/en/category/1000003/fragrances.html",
        BASE_URL + "/en/category/1000054/mens-fragrances.html",
        BASE_URL + "/category/1075660/womens-perfume.html",
        BASE_URL + "/category/1075750/mens-perfume.html",
        BASE_URL + "/en/category/1025540/trending.html",
    )


def _discover_from_categories(session, query, max_urls=80):
    """Generic category discovery.

    First inspect Deloox's sitemap for dedicated category/Product-line pages
    matching the query. Then inspect the broad perfume categories and any
    Product-line filter links exposed there.

    No query-specific seeds, brands, products, or hard-coded exceptions.
    """
    urls = []
    seen_urls = set()
    category_urls = []
    seen_categories = set()

    def add_category(url):
        if not url or url in seen_categories:
            return
        seen_categories.add(url)
        category_urls.append(url)

    # 1. Generic sitemap discovery: this is the important path for dedicated
    # Product-line pages such as Deloox creates for individual product lines.
    for category_url in _sitemap_category_urls(
        session,
        query,
        max_sitemaps=48,
        max_urls=50,
    ):
        add_category(category_url)

    # 2. Always keep the two broad perfume categories as a generic fallback.
    for category_url in _category_pages(session):
        add_category(category_url)

    for category_url in category_urls:
        try:
            r = session.get(
                category_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            reader_html = _reader_get(session, page_url)
            if reader_html:
                for product_url in _reader_product_urls(reader_html, query):
                    if product_url not in seen_urls:
                        seen_urls.add(product_url)
                        urls.append(product_url)
                        if len(urls) >= max_urls:
                            return urls[:max_urls]
            continue

        # A category can expose a more specific Product-line filter.
        product_line_links = _category_product_line_links(
            r.text,
            query,
        )

        candidate_pages = []
        seen_pages = set()

        for page_url in [category_url] + product_line_links:
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            candidate_pages.append(page_url)

        for page_url in candidate_pages:
            if page_url == category_url:
                page_html = r.text
            else:
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

            # For dedicated/filter pages we can collect all product URLs
            # present on that page; _product() remains the final validator.
            filtered_page = page_url != category_url

            before_count = len(urls)

            for product_url in _candidate_product_urls(
                page_html,
                query,
                accept_all_products=filtered_page,
            ):
                if product_url in seen_urls:
                    continue

                seen_urls.add(product_url)
                urls.append(product_url)

                if len(urls) >= max_urls:
                    return urls[:max_urls]

            # Deloox can render the product grid in client-side structures
            # that are visible to a reader but not exposed as normal anchors.
            if len(urls) == before_count:
                reader_html = _reader_get(session, page_url)
                for product_url in _reader_product_urls(reader_html, query):
                    if product_url in seen_urls:
                        continue
                    seen_urls.add(product_url)
                    urls.append(product_url)
                    if len(urls) >= max_urls:
                        return urls[:max_urls]

    return urls[:max_urls]

def _sitemap_category_urls(session, query, max_sitemaps=48, max_urls=60):
    """Discover dedicated Deloox category/Product-line pages generically.

    Deloox has dedicated pages such as /category/<id>/<product-line>.html.
    The location of the sitemap can change, so first read robots.txt for
    declared Sitemap entries and then try common sitemap index names.
    """

    query_tokens = tokens(query)
    if not query_tokens:
        return []

    sitemap_roots = [
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
        BASE_URL + "/en/sitemap_index.xml",
        BASE_URL + "/1_index_sitemap.xml",
    ]

    # robots.txt is the authoritative generic discovery mechanism when the
    # site uses a non-standard sitemap path.
    try:
        robots = session.get(
            BASE_URL + "/robots.txt",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if robots.status_code < 400:
            for line in robots.text.splitlines():
                if line.strip().lower().startswith("sitemap:"):
                    value = clean(line.split(":", 1)[1])
                    if value:
                        sitemap_roots.insert(0, value)
    except requests.RequestException:
        pass

    pending = []
    seen_pending = set()

    for url in sitemap_roots:
        if url and url not in seen_pending:
            seen_pending.add(url)
            pending.append(url)

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
                if value not in seen_sitemaps and value not in seen_pending:
                    seen_pending.add(value)
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



def _navigation_category_discovery(session, query):
    """Find a query-matching Deloox category/filter link from navigation.

    This is generic: the query itself is the only matching criterion.
    """
    found = []
    seen = set()

    pages = (
        BASE_URL + "/en",
        BASE_URL + "/it",
        BASE_URL + "/nl",
        BASE_URL + "/fr",
    ) + tuple(_category_pages(session))

    for page_url in pages:
        try:
            r = session.get(page_url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            continue

        for url in _category_product_line_links(r.text, query):
            if url not in seen:
                seen.add(url)
                found.append(url)

    return found[:12]


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
        max_sitemaps=2,
        max_urls=12,
    ):
        add(product_url)
        if len(urls) >= 24:
            return urls[:24]

    # 3. GENERIC NAVIGATION FALLBACK: discover a dedicated product-line
    # category/filter link from the site's own navigation.
    for category_url in _navigation_category_discovery(session, q):
        try:
            r = session.get(
                category_url,
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
            accept_all_products=True,
        ):
            add(product_url)
            if len(urls) >= 24:
                return urls[:24]

    # 4. FALLBACK: category -> brand -> product-line discovery.
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
