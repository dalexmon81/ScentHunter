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

    # Deloox can serialize product URLs inside JSON/JavaScript with escaped
    # slashes (for example https:\\/\\/www.deloox.com\\/product\\/...). Normalize
    # those representations before applying the URL patterns. This is generic
    # and does not depend on any product or brand name.
    raw_html = html.replace("\\\\/", "/")

    for pattern in patterns:
        for raw in re.findall(pattern, raw_html, re.I):
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


def _category_pages(session=None):
    """Return generic Deloox fragrance category entry points.

    These are store taxonomy pages, not product-specific exceptions.
    The broad men's-fragrances category is important because Deloox can
    expose product-line filters there that are not present in the narrower
    men's-perfume page.
    """
    return (
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
    urls = []
    seen = set()
    seen_category_pages = set()

    for category_url in _category_pages(session):
        for category_page_url in _category_page_variants(
            category_url,
            max_pages=8,
        ):
            if category_page_url in seen_category_pages:
                continue
            seen_category_pages.add(category_page_url)

            try:
                r = session.get(
                    category_page_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException:
                continue

            if r.status_code >= 400:
                continue

            # First, discover exact Product-line category links exposed by
            # Deloox. If no filter link is available, reuse the category HTML
            # already downloaded and inspect its product cards directly.
            product_line_links = _category_product_line_links(
                r.text,
                query,
            )

            if product_line_links:
                candidate_pages = [
                    (page_url, None)
                    for page_url in product_line_links
                ]
            else:
                candidate_pages = [
                    (category_page_url, r.text)
                ]

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
                ):
                    if product_url in seen:
                        continue

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
    """Very detailed Deloox discovery diagnostic; does not change normal search."""
    query = clean(query)
    report = {
        "query": query,
        "limits": {
            "candidate_max": 80,
            "sitemap_max_sitemaps": 12,
            "sitemap_max_products": 80,
            "probe_max_products": 12,
        },
        "candidate_queries": _candidate_queries(query)[:4] if query else [],
        "search_endpoints": [],
        "sitemap_endpoints": [],
        "category_endpoints": [],
        "category_filter_urls": [],
        "category_candidates": [],
        "sitemap_candidates": [],
        "search_candidates": [],
        "candidate_urls": [],
        "product_probes": [],
        "validated_products": [],
    }
    if not query:
        return report

    def response_meta(r):
        body = r.text or ""
        low = body.lower()
        return {
            "status": r.status_code,
            "content_type": r.headers.get("content-type"),
            "bytes": len(r.content or b""),
            "title": clean(
                BeautifulSoup(body, "html.parser").title.get_text(" ", strip=True)
            ) if BeautifulSoup(body, "html.parser").title else None,
            "contains_product_marker": "/product/" in low,
            "product_marker_count": low.count("/product/"),
            "query_occurrences": low.count(query.lower()),
            "html_start": body[:300].replace("\n", " "),
        }

    def extract_product_urls_detailed(html, discovery_query=None):
        strict = _candidate_product_urls(
            html,
            query,
            discovery_query=discovery_query or query,
            accept_all_products=False,
        )
        broad = _candidate_product_urls(
            html,
            query,
            discovery_query=discovery_query or query,
            accept_all_products=True,
        )
        return {
            "strict_count": len(strict),
            "strict_samples": strict[:12],
            "broad_count": len(broad),
            "broad_samples": broad[:12],
        }

    # 1. Search endpoints: test every route and show whether product URLs
    # are actually present in the returned HTML.
    for discovery_query in report["candidate_queries"]:
        for route in (
            "/en/search?query=",
            "/en/search?search=",
            "/en/search?q=",
        ):
            url = BASE_URL + route + quote_plus(discovery_query)
            entry = {
                "url": url,
                "discovery_query": discovery_query,
            }
            try:
                r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
                entry.update(response_meta(r))
                if r.status_code < 400:
                    extracted = extract_product_urls_detailed(
                        r.text,
                        discovery_query=discovery_query,
                    )
                    entry["extraction"] = extracted
                    report["search_candidates"].extend(extracted["broad_samples"])
            except requests.RequestException as exc:
                entry["error"] = str(exc)
            report["search_endpoints"].append(entry)

    # 2. Sitemap roots: report every root, XML detection, loc count and
    # query-matching product URLs. This was missing from the old diagnostic.
    sitemap_roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )
    pending = list(sitemap_roots)
    seen_sitemaps = set()
    seen_products = set()

    while pending and len(seen_sitemaps) < 12:
        sitemap_url = pending.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        entry = {"url": sitemap_url}
        try:
            r = session.get(sitemap_url, headers=HEADERS, timeout=TIMEOUT)
            body = r.text or ""
            entry.update(response_meta(r))
            entry["is_xml"] = (
                "xml" in (r.headers.get("content-type") or "").lower()
                or body.lstrip().startswith(("<?xml", "<urlset", "<sitemapindex"))
            )
            entry["loc_count"] = 0
            entry["product_loc_count"] = 0
            entry["query_product_loc_count"] = 0
            entry["matching_product_samples"] = []

            if r.status_code < 400 and entry["is_xml"]:
                soup_xml = BeautifulSoup(body, "xml")
                locs = [
                    clean(loc.get_text())
                    for loc in soup_xml.find_all("loc")
                    if clean(loc.get_text())
                ]
                entry["loc_count"] = len(locs)

                for value in locs:
                    low = value.lower()
                    if "/product/" in low:
                        entry["product_loc_count"] += 1
                        if tokens(query) and tokens(query) <= tokens(value):
                            entry["query_product_loc_count"] += 1
                            if value not in seen_products:
                                seen_products.add(value)
                                report["sitemap_candidates"].append(value)
                                entry["matching_product_samples"].append(value)
                                if len(report["sitemap_candidates"]) >= 80:
                                    break
                    elif low.endswith(".xml") or "sitemap" in low:
                        if value not in seen_sitemaps and len(seen_sitemaps) < 12:
                            pending.append(value)
        except requests.RequestException as exc:
            entry["error"] = str(exc)

        report["sitemap_endpoints"].append(entry)
        if len(report["sitemap_candidates"]) >= 80:
            break

    # 3. Category pages: inspect the actual HTML first, then product-line
    # links. This tells us whether the failure is link discovery or URL parsing.
    seen_category_pages = set()
    for category_url in _category_pages(session):
        entry = {
            "url": category_url,
            "variants": [],
        }
        for page_url in _category_page_variants(category_url, max_pages=8):
            if page_url in seen_category_pages:
                continue
            seen_category_pages.add(page_url)
            variant = {"url": page_url}
            try:
                r = session.get(page_url, headers=HEADERS, timeout=TIMEOUT)
                variant.update(response_meta(r))
                if r.status_code < 400:
                    filters = _category_product_line_links(r.text, query)
                    variant["filter_urls"] = filters[:30]
                    variant["filter_count"] = len(filters)

                    broad = _candidate_product_urls(
                        r.text,
                        query,
                        accept_all_products=True,
                    )
                    strict = _candidate_product_urls(
                        r.text,
                        query,
                        accept_all_products=False,
                    )
                    variant["direct_product_extraction"] = {
                        "broad_count": len(broad),
                        "broad_samples": broad[:12],
                        "strict_count": len(strict),
                        "strict_samples": strict[:12],
                    }

                    for f_url in filters[:20]:
                        try:
                            fr = session.get(
                                f_url,
                                headers=HEADERS,
                                timeout=TIMEOUT,
                            )
                            f_entry = {
                                "url": f_url,
                                "status": fr.status_code,
                                "bytes": len(fr.content or b""),
                            }
                            if fr.status_code < 400:
                                fbroad = _candidate_product_urls(
                                    fr.text,
                                    query,
                                    accept_all_products=True,
                                )
                                fstrict = _candidate_product_urls(
                                    fr.text,
                                    query,
                                    accept_all_products=False,
                                )
                                f_entry["broad_count"] = len(fbroad)
                                f_entry["broad_samples"] = fbroad[:12]
                                f_entry["strict_count"] = len(fstrict)
                                f_entry["strict_samples"] = fstrict[:12]
                                report["category_candidates"].extend(fbroad[:40])
                            variant.setdefault("filter_probes", []).append(f_entry)
                        except requests.RequestException as exc:
                            variant.setdefault("filter_probes", []).append(
                                {"url": f_url, "error": str(exc)}
                            )

                    report["category_filter_urls"].extend(filters)
                    report["category_candidates"].extend(broad[:40])
            except requests.RequestException as exc:
                variant["error"] = str(exc)

            entry["variants"].append(variant)

        report["category_endpoints"].append(entry)

    # 4. Unified candidate list, preserving the source that found each URL.
    source_lists = (
        ("search", report["search_candidates"]),
        ("sitemap", report["sitemap_candidates"]),
        ("category", report["category_candidates"]),
    )
    candidate_sources = {}
    for source, urls in source_lists:
        for url in urls:
            if url:
                candidate_sources.setdefault(url, set()).add(source)

    report["candidate_urls"] = [
        {
            "url": url,
            "sources": sorted(candidate_sources[url]),
        }
        for url in list(candidate_sources)[:80]
    ]

    # 5. Probe the actual product pages and report WHY _product() rejects them.
    # This is the key diagnostic missing before.
    for candidate in report["candidate_urls"][:12]:
        url = candidate["url"]
        probe = {
            "url": url,
            "sources": candidate["sources"],
        }
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            probe["status"] = r.status_code
            if r.status_code < 400:
                soup = BeautifulSoup(r.text, "html.parser")
                data = _jsonld(soup)
                h1 = soup.find("h1")
                name = clean(data.get("name")) or (
                    clean(h1.get_text(" ", strip=True)) if h1 else ""
                )
                offers = data.get("offers")
                offers = offers if isinstance(offers, list) else [offers]
                offer = next(
                    (x for x in offers if isinstance(x, dict)),
                    {},
                )
                probe["extracted"] = {
                    "name": name or None,
                    "name_matches_query": bool(name and matches(name, query)),
                    "h1": clean(h1.get_text(" ", strip=True)) if h1 else None,
                    "brand": (
                        clean(data.get("brand", {}).get("name"))
                        if isinstance(data.get("brand"), dict)
                        else clean(data.get("brand"))
                    ),
                    "price": parse_price(offer.get("price")),
                    "jsonld_type": data.get("@type"),
                    "gtin": clean(data.get("gtin13") or data.get("gtin") or "") or None,
                    "sku": clean(data.get("sku") or "") or None,
                    "availability": availability(
                        soup.get_text(" ", strip=True),
                        offer=offer,
                        soup=soup,
                    ),
                    "has_h1": bool(h1),
                    "has_jsonld": bool(data),
                }
                probe["product_result"] = _product(url, r.text, query)
                probe["accepted_by_product"] = bool(probe["product_result"])
            else:
                probe["accepted_by_product"] = False
        except requests.RequestException as exc:
            probe["error"] = str(exc)
            probe["accepted_by_product"] = False

        report["product_probes"].append(probe)

    report["validated_products"] = [
        p for p in (
            probe.get("product_result")
            for probe in report["product_probes"]
        )
        if p
    ]

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
            ensure_asc
