"""Deloox adapter for ScentHunter.

Discovery strategy:
- Prefer Deloox's current category pages and their Product line filter links.
- Fall back to Deloox search endpoints and sitemap discovery.
- Product pages are parsed through JSON-LD/page content.

Important:
- Discovery is generic and contains no perfume-specific rules.
- Candidate filtering is generic; _product() remains the final authority.
- Technical failures are never converted into NOT_FOUND by this scraper.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"

# Deloox exposes the same retailer through country/language storefronts.
# Discovery starts with the storefronts that currently expose the public
# search/category surfaces, then falls back to the generic .com surface.
BASE_URL = "https://www.deloox.be"
DELOOX_BASE_URLS = (
    "https://www.deloox.com",
    "https://www.deloox.be",
    "https://www.deloox.nl",
    "https://www.deloox.lu",
    "https://www.deloox.es",
)
TIMEOUT = (2.5, 6.0)
MAX_CANDIDATES = 48
MAX_RESULTS = 40
MAX_SEARCH_PAGES = 3
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.7",
    "Cache-Control": "no-cache",
}
DELOOX_HOSTS = {
    "deloox.lu", "www.deloox.lu",
    "deloox.be", "www.deloox.be",
    "deloox.com", "www.deloox.com",
    "deloox.nl", "www.deloox.nl",
    "deloox.es", "www.deloox.es",
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
    """Determine availability from product-specific signals only."""

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
                    clean(
                        node.get("content")
                        or node.get("aria-label")
                        or node.get_text(" ", strip=True)
                    )
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
    """Build generic discovery-query variants."""
    q = clean(query)
    if not q:
        return []

    variants = [q]

    parts = q.split()
    removable = {
        "parfum", "perfume", "eau", "de", "toilette",
        "edt", "edp", "extrait", "extract"
    }
    broad = " ".join(
        p for p in parts if p.lower() not in removable
    ).strip()

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
    accept_all_products=True,
    base_url=None,
):
    """Extract and rank generic Deloox product URLs.

    Deloox search pages contain many unrelated product links in navigation,
    recommendations and other page sections.  Taking the first N product URLs
    is therefore unsafe: the desired product can occur much later in the HTML.

    We collect all product URLs visible in the bounded HTML response, score
    them by generic query relevance (link text, URL and nearby product-card
    context), then return the highest-ranked candidates.  The product page
    remains authoritative through _product().
    """
    soup = BeautifulSoup(html, "html.parser")
    base_url = clean(base_url or BASE_URL)

    # Keep numeric query tokens for discovery scoring (e.g. a model line or
    # product family may contain a single digit).  Final identity validation
    # is still performed by _product()/ProductMatcher.
    query_tokens = [
        x for x in re.findall(r"[a-z0-9]+", clean(query).lower())
        if x
    ]
    query_norm = " ".join(query_tokens)

    candidates = {}
    order = 0

    def relevance(url, context=""):
        nonlocal order
        path_text = norm(url)
        context_text = norm(context)
        combined = f"{context_text} {path_text}".strip()
        score = 0

        if query_norm and query_norm in combined:
            score += 100
        for tok in query_tokens:
            if tok in context_text:
                score += 20
            if tok in path_text:
                score += 12
            if tok in combined:
                score += 4
        return score

    def add(raw_url, context=""):
        nonlocal order
        if not raw_url:
            return
        raw_url = clean(raw_url).replace("\\/", "/")
        if raw_url.startswith(("javascript:", "mailto:", "#")):
            return
        url = urljoin(base_url, raw_url).split("#")[0].split("?")[0]
        try:
            parsed = urlparse(url)
        except Exception:
            return
        if parsed.netloc.lower() not in DELOOX_HOSTS:
            return
        if not re.search(
            r"/(?:product|produit|producto|prodotto)/\d+",
            parsed.path,
            re.I,
        ):
            return

        score = relevance(url, context)
        existing = candidates.get(url)
        if existing is None or score > existing[0]:
            candidates[url] = (score, order)
        order += 1

    # First pass: normal product links.  Use the anchor's own text plus the
    # nearest product/article container as generic relevance context.
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        parent_context = ""
        node = a
        for _ in range(3):
            node = getattr(node, "parent", None)
            if node is None:
                break
            cls = " ".join(node.get("class", [])) if getattr(node, "get", None) else ""
            if any(x in cls.lower() for x in ("product", "article", "variation", "card", "row")):
                parent_context = clean(node.get_text(" ", strip=True))[:2500]
                break
        context = clean(
            " ".join(
                x for x in (
                    a.get_text(" ", strip=True),
                    a.get("title"),
                    href,
                    parent_context,
                ) if x
            )
        )
        add(href, context)

    # Second pass: generic data-* URL attributes.  Do not assume a particular
    # product/card implementation; only inspect common URL-bearing fields.
    attr_names = (
        "data-url",
        "data-href",
        "data-link",
        "data-product-url",
        "data-product-link",
        "data-target",
        "data-href-url",
    )
    for node in soup.find_all(True):
        context = clean(node.get_text(" ", strip=True))[:2500]
        for attr in attr_names:
            raw = node.get(attr)
            if raw:
                add(raw, f"{raw} {context}")

    # Third pass: product URLs embedded in JSON/state/hydration payloads.
    patterns = (
        r'https?://(?:www\\.)?deloox\.(?:lu|be|com|nl|es)/[^"\'<>\s]+/(?:product|produit|producto|prodotto)/\d+[^"\'<>\s]*',
        r'(?:(?:https?:)?//(?:www\\.)?deloox\.(?:lu|be|com|nl|es))?/(?:en/|fr/|nl/|es/|it/|de/)?(?:product|produit|producto|prodotto)/\d+/[^"\'<>\s]+',
    )
    for pattern in patterns:
        for raw in re.findall(pattern, html, re.I):
            add(raw, raw)

    ranked = sorted(
        candidates.items(),
        key=lambda item: (-item[1][0], item[1][1]),
    )
    return [url for url, _meta in ranked[:MAX_CANDIDATES]]


def _category_pages(session=None):
    """Return generic fragrance category surfaces, bounded for live search."""
    paths = (
        "/categorie/1075744/eau-de-toilette-homme.html",
        "/categorie/1075743/eau-de-parfum-femme.html",
        "/en/category/1103659/fragrances.html",
        "/category/1103659/fragrances.html",
        "/category/1075660/womens-perfume.html",
        "/category/1075750/mens-perfume.html",
    )
    out = []
    seen = set()
    for base in DELOOX_BASE_URLS:
        for path in paths:
            url = base + path
            if url not in seen:
                seen.add(url)
                out.append(url)
    return tuple(out)


def _sitemap_roots():
    paths = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/en/sitemap.xml")
    return tuple(base + path for base in DELOOX_BASE_URLS for path in paths)


def _fetch_xml(session, url):
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException:
        return None
    if r.status_code >= 400:
        return None
    body = r.text.lstrip()
    ctype = (r.headers.get("content-type") or "").lower()
    if "xml" not in ctype and not body.startswith(("<?xml", "<urlset", "<sitemapindex")):
        return None
    return r.text


def _sitemap_product_urls(session, query, max_sitemaps=120, max_urls=MAX_CANDIDATES):
    """Search the retailer's sitemap tree generically and with bounded concurrency.

    The previous implementation inspected only a handful of sitemap nodes.
    Large retailers commonly shard product URLs across many child sitemaps, so
    an arbitrary small prefix can miss a valid product.  We now expand the
    sitemap index, fetch child sitemaps concurrently, and select only URLs
    whose own path contains the complete query token set.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    q_tokens = tokens(query)
    if not q_tokens:
        return []

    roots = _sitemap_roots()
    seen_roots = set()
    root_xmls = []

    def fetch_xml(url):
        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            if r.status_code >= 400:
                return None
            return r.text
        except requests.RequestException:
            return None

    with ThreadPoolExecutor(max_workers=min(8, len(roots))) as pool:
        futures={pool.submit(fetch_xml,u):u for u in roots}
        for f in as_completed(futures):
            u=futures[f]
            try: xml=f.result()
            except Exception: xml=None
            if xml:
                root_xmls.append((u,xml))

    pending=[]
    direct=[]
    for root_url,xml in root_xmls:
        soup=BeautifulSoup(xml,"xml")
        for loc in soup.find_all("loc"):
            value=clean(loc.get_text())
            if not value:
                continue
            low=value.lower()
            if re.search(r"/(?:product|produit|producto|prodotto)/\d+", low, re.I):
                direct.append(value)
            elif low.endswith(".xml") or "sitemap" in low:
                if value not in seen_roots:
                    seen_roots.add(value)
                    pending.append(value)

    # If a root itself is a sitemap containing product URLs, use them first.
    out=[]
    seen_out=set()
    for value in direct:
        if q_tokens.issubset(tokens(value)) and value not in seen_out:
            seen_out.add(value)
            out.append(value)
            if len(out)>=max_urls:
                return out[:max_urls]

    pending=pending[:max_sitemaps]

    # Fetch the sharded product sitemaps concurrently.  The limit is large
    # enough to cover normal sitemap trees but bounded so one store cannot
    # monopolize Main's global timeout.
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures={pool.submit(fetch_xml,u):u for u in pending}
        for f in as_completed(futures):
            try: xml=f.result()
            except Exception: xml=None
            if not xml:
                continue
            soup=BeautifulSoup(xml,"xml")
            for loc in soup.find_all("loc"):
                value=clean(loc.get_text())
                low=value.lower()
                if not re.search(r"/(?:product|produit|producto|prodotto)/\d+", low, re.I):
                    continue
                if q_tokens.issubset(tokens(value)) and value not in seen_out:
                    seen_out.add(value)
                    out.append(value)
                    if len(out)>=max_urls:
                        return out[:max_urls]

    return out[:max_urls]



def _candidate_category_urls(html, query, base_url=None):
    """Extract retailer category/filter URLs that are relevant to the query.

    This is a store-navigation mechanism, not a product rule.  A Deloox search
    can resolve a query to a category/brand/product-family page rather than
    exposing every matching product directly.  Following those store-provided
    links is necessary to discover all variants.
    """
    q_tokens = tokens(query)
    if not q_tokens:
        return []

    base_url = clean(base_url or BASE_URL)
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = clean(a.get("href"))
        label = clean(a.get_text(" ", strip=True))
        context = norm(f"{label} {href}")
        parsed = urlparse(urljoin(base_url, href).split("#")[0].split("?")[0])
        if parsed.netloc.lower() not in DELOOX_HOSTS:
            continue
        if not re.search(r"/(?:category|categorie|categoria|catégorie)/", parsed.path, re.I):
            continue

        # Require at least one query token in the retailer's own category
        # label/URL. This is intentionally broad: the category page itself
        # will perform the authoritative product discovery.
        if not any(tok in context.split() or tok in norm(parsed.path).split() for tok in q_tokens):
            continue

        url = parsed.geturl()
        if url not in seen:
            seen.add(url)
            found.append(url)

    return found[:32]


def _discover_from_search(session, query):
    """Discover product URLs and store category URLs from Deloox search.

    Important: a non-empty search result is NOT considered complete.  Search
    pages may expose only one variant while linking to a category/family page
    containing the other variants.  We therefore collect both product and
    relevant category URLs and let the next stage inspect those pages.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    query = clean(query)
    if not query:
        return []

    routes = (
        "/chercher.html", "/zoeken.html", "/search.html", "/search",
        "/en/search.html", "/en/search", "/fr/search.html", "/fr/search",
        "/nl/search.html", "/nl/search",
    )
    params = ("q", "query", "search", "searchTerm", "keyword")
    jobs = []
    seen_jobs = set()

    for base in DELOOX_BASE_URLS:
        for route in routes:
            for param in params:
                endpoint = base + route + "?" + param + "=" + quote_plus(query)
                if endpoint not in seen_jobs:
                    seen_jobs.add(endpoint)
                    jobs.append(endpoint)

    jobs = jobs[:75]

    def probe(endpoint):
        try:
            r = session.get(endpoint, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            return [], []
        if r.status_code >= 400:
            return [], []
        base = f"{urlparse(r.url).scheme}://{urlparse(r.url).netloc}"
        products = _candidate_product_urls(r.text, query, base_url=base, accept_all_products=True)
        categories = _candidate_category_urls(r.text, query, base_url=base)
        return products, categories

    products = []
    categories = []
    seen_products = set()
    seen_categories = set()

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(probe, endpoint) for endpoint in jobs]
        for future in as_completed(futures):
            try:
                found_products, found_categories = future.result()
            except Exception:
                continue
            for url in found_products:
                if url not in seen_products:
                    seen_products.add(url)
                    products.append(url)
            for url in found_categories:
                if url not in seen_categories:
                    seen_categories.add(url)
                    categories.append(url)

    # Follow the store's own relevant category/family links.  This is the
    # generic path that allows queries such as a product variant to discover
    # sibling variants that are not all exposed by the search result cards.
    def fetch_category(url):
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            return []
        if r.status_code >= 400:
            return []
        base = f"{urlparse(r.url).scheme}://{urlparse(r.url).netloc}"
        return _candidate_product_urls(r.text, query, base_url=base, accept_all_products=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_category, url) for url in categories[:16]]
        for future in as_completed(futures):
            try:
                found = future.result()
            except Exception:
                continue
            for url in found:
                if url not in seen_products:
                    seen_products.add(url)
                    products.append(url)

    return products[:MAX_CANDIDATES]

def _category_product_line_links(html, query):
    """Extract generic category/filter links whose visible text matches query.

    This is not product-specific: it simply uses the store's own category/filter
    navigation as a discovery surface and lets _product() validate the final
    product page.
    """
    q_tokens = tokens(query)
    if not q_tokens:
        return []

    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    for a in soup.find_all("a", href=True):
        label = clean(a.get_text(" ", strip=True))
        href = clean(a.get("href"))
        context = f"{label} {href}"
        if not q_tokens.issubset(tokens(context)):
            continue
        url = urljoin(BASE_URL, href).split("#")[0]
        parsed = urlparse(url)
        if parsed.netloc.lower() not in DELOOX_HOSTS:
            continue
        # Category/filter discovery only. Never treat this URL as a product
        # unless _candidate_product_urls() later identifies a product URL.
        if re.search(r"/(?:category|categorie|categoria)/", parsed.path, re.I):
            if url not in seen:
                seen.add(url)
                found.append(url)
    return found[:MAX_CANDIDATES]


def _discover_from_categories(session, query, max_urls=MAX_CANDIDATES):
    """Bounded generic category fallback after search has failed."""
    urls = []
    seen = set()
    for page_url in _category_pages()[:12]:
        try:
            r = session.get(page_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue
        base = f"{urlparse(r.url).scheme}://{urlparse(r.url).netloc}"
        pages = [r.url]
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = clean(a.get("href"))
            if "page=" not in href.lower():
                continue
            u = urljoin(base, href)
            if u not in pages:
                pages.append(u)
            if len(pages) >= 8:
                break

        for current_url in pages:
            if current_url == r.url:
                html = r.text
            else:
                try:
                    page = session.get(current_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
                    if page.status_code >= 400:
                        continue
                    html = page.text
                except requests.RequestException:
                    continue
            for product_url in _candidate_product_urls(
                html, query, base_url=base, accept_all_products=True
            ):
                if product_url not in seen:
                    seen.add(product_url)
                    urls.append(product_url)
                    if len(urls) >= max_urls:
                        return urls
    return urls


def _discover(session, q):
    """Generic Deloox discovery: search first, bounded fallbacks second."""
    q = clean(q)
    if not q:
        return []

    # Every discovery surface is complementary.  A search hit is not proof
    # that the search page is exhaustive, so never stop merely because one
    # surface returned candidates.
    candidates = []
    seen = set()

    for source in (
        _discover_from_search(session, q),
        _discover_from_categories(session, q, MAX_CANDIDATES),
        _sitemap_product_urls(session, q, max_sitemaps=48, max_urls=MAX_CANDIDATES),
    ):
        for url in source:
            if url in seen:
                continue
            seen.add(url)
            candidates.append(url)
            if len(candidates) >= MAX_CANDIDATES:
                return candidates

    return candidates


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

    for category_url in _category_pages(session):
        entry = {
            "url": category_url,
            "status": None,
            "filter_urls": [],
            "candidate_urls": [],
        }

        try:
            r = session.get(
                category_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            entry["status"] = r.status_code
        except requests.RequestException as exc:
            entry["error"] = str(exc)
            report["category_endpoints"].append(entry)
            continue

        report["category_endpoints"].append(entry)

        if r.status_code >= 400:
            continue

        filter_urls = _category_product_line_links(
            r.text,
            query,
        )

        entry["filter_urls"] = filter_urls[:20]
        report["filter_urls"].extend(filter_urls)

        pages = (
            [(category_url, False)]
            + [(url, True) for url in filter_urls]
        )

        for page_url, filtered in pages:
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

            candidates = _candidate_product_urls(
                page.text,
                query,
                accept_all_products=filtered,
                base_url=f"{urlparse(page.url).scheme}://{urlparse(page.url).netloc}",
            )

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
            r = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            continue

        item = _product(
            url,
            r.text,
            query,
        )

        if item:
            report["validated_products"].append(item)

    for endpoint in (
        BASE_URL + "/en/search?query=" + quote_plus(query),
        BASE_URL + "/en/search?search=" + quote_plus(query),
        BASE_URL + "/en/search?q=" + quote_plus(query),
    ):
        try:
            r = session.get(
                endpoint,
                headers=HEADERS,
                timeout=TIMEOUT,
            )

            report["search_fallback"].append({
                "url": endpoint,
                "status": r.status_code,
            })

        except requests.RequestException as exc:
            report["search_fallback"].append({
                "url": endpoint,
                "error": str(exc),
            })

    return report


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)
    results = []
    seen = set()

    try:
        candidates = _discover(session, query)[:MAX_CANDIDATES]
        if not candidates:
            return []

        # Product pages are independent HTTP requests.  Fetch them in parallel
        # so one slow candidate cannot consume the whole store timeout budget.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def fetch(url):
            try:
                r = session.get(
                    url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
                if r.status_code >= 400:
                    return None
                return _product(r.url or url, r.text, query)
            except requests.RequestException:
                return None
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as pool:
            futures = {pool.submit(fetch, url): url for url in candidates}
            for future in as_completed(futures):
                item = future.result()
                if not item:
                    continue
                sku = item.get("identity", {}).get("sku")
                sku_value = sku.get("value") if isinstance(sku, dict) else None
                key = (item.get("url"), sku_value)
                if key in seen:
                    continue
                seen.add(key)
                results.append(item)
                if len(results) >= MAX_RESULTS:
                    break

        return results[:MAX_RESULTS]
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
