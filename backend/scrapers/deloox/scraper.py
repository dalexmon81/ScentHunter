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

        raw_scoped = clean(" ".join(x for x in scoped_parts if x)).lower()
        scoped = norm(raw_scoped)
        if scoped:
            if (
                any(x in scoped for x in (
                    "sold out", "out of stock", "not available",
                    "currently unavailable", "unavailable", "epuise",
                    "niet beschikbaar",
                ))
                or "epuisé" in raw_scoped or "épuisé" in raw_scoped
            ):
                return "out_of_stock"
            if any(x in scoped for x in (
                "in stock", "en stock", "available", "disponible",
                "op voorraad", "add to cart", "add to basket", "buy now",
                "bestellen", "ajouter au panier",
            )):
                return "in_stock"

    # 3) Deliberately conservative fallback. Only use the whole-page text
    # when there is NO structured/scoped signal at all. This prevents a
    # recommendation card saying "out of stock" from poisoning the product.
    raw_text = clean(text).lower()
    t = norm(raw_text)
    if (
        any(x in t for x in (
            "sold out",
            "out of stock",
            "currently unavailable",
            "epuise",
            "niet beschikbaar",
        ))
        or "epuisé" in raw_text or "épuisé" in raw_text
    ):
        return "out_of_stock"
    if any(x in t for x in ("in stock", "en stock", "available", "disponible", "op voorraad")):
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

    # Deloox.be can expose the current price in structured/meta attributes
    # before it appears as ordinary visible text. Prefer those product-scoped
    # signals before falling back to the whole page.
    if price is None:
        price_candidates = []

        for selector in (
            'meta[itemprop="price"]',
            'meta[property="product:price:amount"]',
            '[data-testid*="price" i]',
            '[data-test*="price" i]',
            '[itemprop="price"]',
            '[class*="price" i]',
        ):
            try:
                nodes = soup.select(selector)
            except Exception:
                nodes = []
            for node in nodes[:30]:
                value = (
                    node.get("content")
                    or node.get("data-price")
                    or node.get("data-value")
                    or node.get_text(" ", strip=True)
                )
                if value:
                    price_candidates.append(value)

        for candidate in price_candidates:
            price = parse_price(candidate)
            if price is not None:
                break

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

        if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
            return

        if not re.search(r"/(?:product|produit)/", parsed.path.lower()):
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
        r'https?://(?:www\.)?deloox\.be/[^"\'>\s]+/(?:product|produit)/[^"\'>\s]+',
        r'["\']((?:/)?(?:fr/|nl/|en/|it/)?(?:product|produit)/[^"\']+)["\']',
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

        if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
            return
        if not re.search(r"/(?:category|categorie)/", parsed.path.lower()):
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
        r'(?:"|\\\')((?:https?:)?//(?:www\\.)?deloox\\.be)?'
        r'(/(?:fr/|nl/|en/|it/)?(?:category|categorie)/\\d+/[^"\\\'<>\\s]+\\.html)',
        r'(?:"|\\\')((?:/)?(?:fr/|nl/|en/|it/)?(?:category|categorie)/\\d+/[^"\\\'<>\\s]+\\.html)(?:"|\\\')',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, raw, re.I):
            if isinstance(match, tuple):
                match = "".join(match)
            add(match)

    return links


def _category_pages(session=None):
    """Discover generic fragrance catalogue entry points from Deloox itself.

    Deloox.be changed its category IDs/paths.  Do not rely on stale IDs:
    read the live homepage and keep only generic fragrance taxonomy links.
    """
    urls = []
    seen = set()

    fragrance_terms = {
        "parfum", "parfums", "perfume", "perfumes",
        "fragrance", "fragrances", "geur", "geuren",
    }
    exclude_terms = {
        "interieur", "maison", "bougie", "douche", "bain",
        "corps", "cheveux", "make", "maquillage", "soin",
        "shampoo", "aftershave", "accessoire",
    }

    def add(raw_url, label=""):
        if not raw_url:
            return
        url = urljoin(BASE_URL, clean(raw_url)).split("#")[0]
        try:
            parsed = urlparse(url)
        except Exception:
            return
        if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
            return
        if not re.search(r"/(?:category|categorie)/", parsed.path.lower()):
            return
        if not parsed.path.lower().endswith(".html"):
            return

        haystack = norm(
            f"{parsed.path.rsplit('/', 1)[-1]} {label}"
        )
        if not any(term in haystack.split() for term in fragrance_terms):
            return
        if any(term in haystack.split() for term in exclude_terms):
            return

        if url not in seen:
            seen.add(url)
            urls.append(url)

    # The homepage is the authoritative source for the current taxonomy.
    if session is not None:
        try:
            r = session.get(BASE_URL + "/", headers=HEADERS, timeout=TIMEOUT)
            if r.status_code < 400:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    add(a.get("href"), a.get_text(" ", strip=True))
        except requests.RequestException:
            pass

    # Generic current fallback roots only.  These are taxonomy pages, never
    # product-specific seeds, and are used only when the homepage exposes no
    # usable fragrance category.
    if not urls:
        for fallback in (
            BASE_URL + "/categorie/1075732/parfum-homme.html",
            BASE_URL + "/categorie/1075918/parfum-mixte.html",
            BASE_URL + "/categorie/1000003/parfum.html",
        ):
            add(fallback, "parfum")

    return tuple(urls[:12])


def _category_page_variants(category_url, max_pages=8):
    """Add bounded pagination to generic perfume catalogue pages."""
    path = urlparse(category_url).path.lower()
    if "parfum" not in path:
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
            if re.search(r"/(?:category|categorie)/", low) and low.endswith(".html"):
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

            if re.search(r"/(?:product|produit)/", low):
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
        if url and url not in seen and len(urls) < 48:
            seen.add(url)
            urls.append(url)

    # 1. PRIMARY: use the search form exposed by the live Deloox.be homepage.
    # Its action is /chercher.html and its query field is named "q".
    # This is the authoritative current search surface and avoids wasting
    # time on obsolete localized routes that now return HTTP 404.
    discovery_queries = _candidate_queries(q)[:2]
    search_endpoints = (
        "/chercher.html?q=",
        "/chercher.html?search=",
        "/chercher.html?query=",
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

            candidates = _candidate_product_urls(
                r.text,
                q,
                discovery_query=discovery_query,
                accept_all_products=True,
            )
            for product_url in candidates:
                add(product_url)
                if len(urls) >= 48:
                    return urls[:48]

            # Once the current search route returns candidates, do not crawl
            # categories/sitemaps as well.  This keeps discovery fast.
            if candidates:
                return urls[:48]

    # 2. SECONDARY: direct product sitemap.  This is still generic and does
    # not depend on a brand/category filter being rendered by Deloox.
    for product_url in _sitemap_product_urls(
        session,
        q,
        max_sitemaps=2,
        max_urls=12,
    ):
        add(product_url)
        if len(urls) >= 48:
            return urls[:48]

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
        if len(urls) >= 48:
            return urls[:48]

    # 4. Final retry through the live search form with the original query.
    # Keep this single route as a bounded last resort.
    endpoint = BASE_URL + "/chercher.html?q=" + quote_plus(q)
    try:
        r = session.get(
            endpoint,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        r = None

    if r is not None and r.status_code < 400:
        for product_url in _candidate_product_urls(
            r.text,
            q,
            discovery_query=q,
            accept_all_products=True,
        ):
            add(product_url)
            if len(urls) >= 48:
                return urls[:48]

    return urls[:48]



def diagnose_search(session, query):
    """Deep, read-only diagnostic of the REAL generic Deloox discovery.

    This diagnostic follows the same discovery order used by _discover():
      1. current /chercher.html search surface
      2. product sitemaps
      3. generic category/Product-line discovery
      4. final bounded /chercher.html retry

    It records the HTTP result of every stage, timing, final URL, content
    type/size, candidate URLs and validation results.  It never contains
    product-specific seeds or exceptions.
    """
    import time

    query = clean(query)
    report = {
        "query": query,
        "base_url": BASE_URL,
        "discovery_order": [
            "search",
            "product_sitemap",
            "categories",
            "final_search_retry",
        ],
        "candidate_urls": [],
        "validated_products": [],
        "stages": {
            "search": [],
            "product_sitemap": [],
            "categories": [],
            "final_search_retry": [],
        },
        "summary": {
            "candidate_count": 0,
            "validated_count": 0,
        },
    }

    if not query:
        return report

    seen_candidates = set()

    def request_trace(stage, url, started, response=None, error=None):
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        item = {
            "url": url,
            "elapsed_ms": elapsed_ms,
        }

        if response is not None:
            item.update({
                "status": response.status_code,
                "final_url": getattr(response, "url", url),
                "content_type": (
                    response.headers.get("content-type")
                    if getattr(response, "headers", None)
                    else None
                ),
                "bytes": len(response.content or b""),
            })

        if error is not None:
            item["error"] = f"{type(error).__name__}: {error}"

        report["stages"][stage].append(item)
        return item

    def add_candidates(urls, stage_item=None):
        added = []
        for url in urls or []:
            if not url or url in seen_candidates:
                continue
            seen_candidates.add(url)
            report["candidate_urls"].append(url)
            added.append(url)
            if len(report["candidate_urls"]) >= 80:
                break

        if stage_item is not None:
            stage_item["candidate_count"] = len(added)
            stage_item["candidates"] = added[:40]

        return added

    # ------------------------------------------------------------
    # 1. PRIMARY: the current Deloox search surface.
    # ------------------------------------------------------------
    discovery_queries = _candidate_queries(query)[:2]
    search_endpoints = (
        "/chercher.html?q=",
        "/chercher.html?search=",
        "/chercher.html?query=",
    )

    for discovery_query in discovery_queries:
        for route in search_endpoints:
            endpoint = BASE_URL + route + quote_plus(discovery_query)
            started = time.perf_counter()

            try:
                response = session.get(
                    endpoint,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException as exc:
                request_trace(
                    "search",
                    endpoint,
                    started,
                    error=exc,
                )
                continue

            trace = request_trace(
                "search",
                endpoint,
                started,
                response=response,
            )

            if response.status_code >= 400:
                continue

            candidates = _candidate_product_urls(
                response.text,
                query,
                discovery_query=discovery_query,
                accept_all_products=True,
            )
            added = add_candidates(candidates, trace)

            if candidates:
                trace["discovery_query"] = discovery_query
                trace["route"] = route
                trace["returned_candidates"] = len(candidates)
                break

        if report["candidate_urls"]:
            break

    # ------------------------------------------------------------
    # 2. SECONDARY: product sitemap discovery.
    # Trace the actual sitemap requests and extract query-matching
    # product URLs using the same generic rules.
    # ------------------------------------------------------------
    if not report["candidate_urls"]:
        sitemap_roots = (
            BASE_URL + "/sitemap.xml",
            BASE_URL + "/sitemap_index.xml",
            BASE_URL + "/sitemap-index.xml",
            BASE_URL + "/en/sitemap.xml",
        )

        pending = list(sitemap_roots)
        seen_sitemaps = set()

        while (
            pending
            and len(seen_sitemaps) < 2
            and not report["candidate_urls"]
        ):
            sitemap_url = pending.pop(0)
            if sitemap_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_url)

            started = time.perf_counter()
            try:
                response = session.get(
                    sitemap_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException as exc:
                request_trace(
                    "product_sitemap",
                    sitemap_url,
                    started,
                    error=exc,
                )
                continue

            trace = request_trace(
                "product_sitemap",
                sitemap_url,
                started,
                response=response,
            )

            if response.status_code >= 400:
                continue

            body = response.text.lstrip()
            content_type = (
                response.headers.get("content-type") or ""
            ).lower()

            if "xml" not in content_type and not body.startswith(
                ("<?xml", "<urlset", "<sitemapindex")
            ):
                trace["xml_usable"] = False
                continue

            trace["xml_usable"] = True
            soup = BeautifulSoup(response.text, "xml")

            found = []
            for loc in soup.find_all("loc"):
                value = clean(loc.get_text())
                if not value:
                    continue

                low = value.lower()

                if re.search(r"/(?:product|produit)/", low):
                    if tokens(query).issubset(tokens(value)):
                        found.append(value)
                        if len(found) >= 40:
                            break
                elif low.endswith(".xml") or "sitemap" in low:
                    if value not in seen_sitemaps:
                        pending.append(value)

            add_candidates(found, trace)

    # ------------------------------------------------------------
    # 3. FALLBACK: generic live category discovery.
    # ------------------------------------------------------------
    if not report["candidate_urls"]:
        category_urls = _category_pages(session)

        for category_url in category_urls:
            if len(report["candidate_urls"]) >= 80:
                break

            started = time.perf_counter()
            try:
                response = session.get(
                    category_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException as exc:
                request_trace(
                    "categories",
                    category_url,
                    started,
                    error=exc,
                )
                continue

            trace = request_trace(
                "categories",
                category_url,
                started,
                response=response,
            )

            if response.status_code >= 400:
                continue

            product_line_links = _category_product_line_links(
                response.text,
                query,
            )
            trace["product_line_links"] = product_line_links[:20]

            candidate_pages = (
                product_line_links[:12]
                if product_line_links
                else [category_url]
            )

            category_candidates = []

            for page_url in candidate_pages:
                if page_url == category_url:
                    page_html = response.text
                else:
                    page_started = time.perf_counter()
                    try:
                        page = session.get(
                            page_url,
                            headers=HEADERS,
                            timeout=TIMEOUT,
                        )
                    except requests.RequestException as exc:
                        page_trace = request_trace(
                            "categories",
                            page_url,
                            page_started,
                            error=exc,
                        )
                        page_trace["parent_category"] = category_url
                        continue

                    page_trace = request_trace(
                        "categories",
                        page_url,
                        page_started,
                        response=page,
                    )
                    page_trace["parent_category"] = category_url

                    if page.status_code >= 400:
                        continue

                    page_html = page.text

                candidates = _candidate_product_urls(
                    page_html,
                    query,
                    accept_all_products=bool(product_line_links),
                )
                category_candidates.extend(candidates)

                if len(category_candidates) >= 40:
                    break

            add_candidates(category_candidates, trace)

    # ------------------------------------------------------------
    # 4. Validate every discovered candidate through the real parser.
    # ------------------------------------------------------------
    for url in report["candidate_urls"]:
        started = time.perf_counter()

        try:
            response = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            report["validated_products"].append({
                "url": url,
                "status": None,
                "elapsed_ms": round(
                    (time.perf_counter() - started) * 1000,
                    1,
                ),
                "decision": "request_error",
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        validation = {
            "url": url,
            "status": response.status_code,
            "final_url": getattr(response, "url", url),
            "elapsed_ms": round(
                (time.perf_counter() - started) * 1000,
                1,
            ),
            "bytes": len(response.content or b""),
        }

        if response.status_code >= 400:
            validation["decision"] = "http_error"
        else:
            item = _product(url, response.text, query)
            validation["decision"] = (
                "accepted" if item else "rejected_by_product_parser"
            )
            if item:
                validation["product"] = item

        report["validated_products"].append(validation)

    # ------------------------------------------------------------
    # 5. Always record the legacy localized routes separately.
    # This is diagnostic evidence only; these routes are NOT used by
    # the normal discovery algorithm.
    # ------------------------------------------------------------
    legacy_routes = (
        "/fr/recherche?query=",
        "/fr/recherche?search=",
        "/fr/recherche?q=",
        "/nl/zoeken?query=",
        "/nl/zoeken?search=",
        "/nl/zoeken?q=",
        "/en/search?query=",
        "/en/search?search=",
        "/en/search?q=",
        "/search?query=",
        "/search?search=",
        "/search?q=",
    )

    for route in legacy_routes:
        endpoint = BASE_URL + route + quote_plus(query)
        started = time.perf_counter()

        try:
            response = session.get(
                endpoint,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            request_trace(
                "final_search_retry",
                endpoint,
                started,
                error=exc,
            )
            continue

        trace = request_trace(
            "final_search_retry",
            endpoint,
            started,
            response=response,
        )
        trace["legacy_route"] = True

    report["summary"]["candidate_count"] = len(
        report["candidate_urls"]
    )
    report["summary"]["validated_count"] = sum(
        1
        for item in report["validated_products"]
        if item.get("decision") == "accepted"
    )
    report["summary"]["rejected_count"] = sum(
        1
        for item in report["validated_products"]
        if item.get("decision") != "accepted"
    )

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
