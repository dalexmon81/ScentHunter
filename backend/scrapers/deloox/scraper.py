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

        if not any(part in parsed.path.lower() for part in ("/produit/", "/product/")):
            return

        if url in seen:
            return

        # During search discovery we want candidate URLs, not final matches.
        # Require at least one generic query token in the link context so the
        # candidate pool remains bounded, but do not require every token.
        # _product() performs the authoritative product-name validation later.
        if not accept_all_products:
            haystack = f"{context} {url}"
            if not (tokens(query) & tokens(haystack)):
                return

        seen.add(url)
        found.append(url)

    for a in soup.find_all("a", href=True):
        add(a.get("href"), a.get_text(" ", strip=True))

    patterns = [
        r'https?://(?:www\.)?deloox\.be/[^"\'>\s]+/(?:produit|product)/[^"\'>\s]+',
        r'["\']((?:/)?(?:en/|fr/|nl/|it/)?(?:produit|product)/[^"\']+)["\']',
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
        if not any(part in parsed.path.lower() for part in ("/categorie/", "/category/")):
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
        r"(?=\"|\\\')((?:https?:)?//(?:www\.)?deloox\.be)?"
        r"(/(?:en/|fr/|it/|nl/)?(?:categorie|category)/\d+/[^\"\\'<>\s]+\.html)",
        r"(?=\"|\\\')((?:/)?(?:en/|fr/|it/|nl/)?(?:categorie|category)/\d+/[^\"\\'<>\s]+\.html)(?=\"|\\\')",
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
        BASE_URL + "/categorie/1000003/parfum.html",
        BASE_URL + "/categorie/1000062/parfum-homme.html",
        BASE_URL + "/categorie/1000063/parfum-femme.html",
    )


def _category_page_variants(category_url, max_pages=8):
    """Add bounded pagination only to the broad men's fragrance category."""
    if not category_url.lower().endswith(
        "/categorie/1000003/parfum.html"
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
        BASE_URL + "/fr/sitemap.xml",
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
            if ("/categorie/" in low or "/category/" in low) and low.endswith(".html"):
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
    """Discover relevant Deloox product URLs from sitemaps.

    Sitemap discovery is candidate-oriented but still relevance-aware. It
    ranks URLs by generic overlap with the query instead of requiring every
    query token to be present. The actual product page remains authoritative.
    """
    query_tokens = tokens(query)
    if not query_tokens:
        return []

    sitemap_roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/fr/sitemap.xml",
    )

    pending = list(sitemap_roots)
    seen_sitemaps = set()
    scored = {}
    order = 0

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

    def score_url(value):
        low = value.lower()
        if "/produit/" not in low and "/product/" not in low:
            return None

        url_tokens = tokens(value)
        overlap = len(query_tokens & url_tokens)
        if overlap == 0:
            return None

        # Generic ranking only. No product/brand-specific knowledge.
        normalized_url = norm(value)
        normalized_query = norm(query)
        phrase_bonus = 3 if normalized_query and normalized_query in normalized_url else 0
        coverage = overlap / max(1, len(query_tokens))
        return (phrase_bonus, overlap, coverage)

    while (
        pending
        and len(seen_sitemaps) < max_sitemaps
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

            if "/produit/" in low or "/product/" in low:
                score = score_url(value)
                if score is not None:
                    if value not in scored:
                        scored[value] = (score, order)
                        order += 1
            elif low.endswith(".xml") or "sitemap" in low:
                if value not in seen_sitemaps:
                    pending.append(value)

    ranked = sorted(
        scored.items(),
        key=lambda item: (
            item[1][0][0],
            item[1][0][1],
            item[1][0][2],
            -item[1][1],
        ),
        reverse=True,
    )

    return [url for url, _meta in ranked[:max_urls]]

def _discover(session, q):
    """Generic Deloox discovery for the current .be site.

    Discovery combines several generic sources and deduplicates them:
    - Deloox search endpoints, when available;
    - category/Product-line pages;
    - product sitemaps.

    Sources are candidates only. Final product identity is validated by
    _product(), so no perfume, brand, SKU, or URL-specific exception exists.
    """
    candidates = []
    seen = set()

    def add(url):
        if url and url not in seen and len(candidates) < 80:
            seen.add(url)
            candidates.append(url)

    # 1. SEARCH ENDPOINTS: query-specific source, so use it first.
    for endpoint in (
        BASE_URL + "/en/search?query=" + quote_plus(q),
        BASE_URL + "/en/search?search=" + quote_plus(q),
        BASE_URL + "/en/search?q=" + quote_plus(q),
    ):
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
            accept_all_products=True,
        ):
            add(product_url)
            if len(candidates) >= 80:
                break

        if len(candidates) >= 80:
            break

    # 2. CATEGORY PAGES.
    if len(candidates) < 80:
        for url in _discover_from_categories(
            session,
            q,
            max_urls=40,
        ):
            add(url)
            if len(candidates) >= 80:
                break

    # 3. SITEMAPS, ranked by generic query relevance.
    if len(candidates) < 80:
        for url in _sitemap_product_urls(
            session,
            q,
            max_sitemaps=8,
            max_urls=40,
        ):
            add(url)
            if len(candidates) >= 80:
                break

    return candidates[:80]


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
