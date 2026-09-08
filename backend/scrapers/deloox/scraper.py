"""Deloox adapter for ScentHunter.

Discovery strategy:
- Prefer Deloox's current category pages and their Product line filter links.
- Fall back to Deloox search endpoints and sitemap discovery.
- Product pages are parsed through JSON-LD/page content.
"""
from __future__ import annotations

import json
import html as htmllib
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.be"
TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _diag(stage, **fields):
    parts = [f"{k}={fields[k]!r}" for k in fields]
    suffix = " " + " ".join(parts) if parts else ""
    print(f"DELOOX_DIAG: {stage}{suffix}", flush=True)


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


def availability_from_sources(data, soup):
    """Prefer structured offer availability; never classify from unrelated page text."""
    offers = data.get("offers") if isinstance(data, dict) else None
    if isinstance(offers, dict):
        offers = [offers]
    if isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            raw = offer.get("availability") or offer.get("availabilityStatus") or offer.get("stock")
            if raw:
                t = norm(raw)
                if any(x in t for x in ("instock", "in stock", "available")):
                    return "in_stock"
                if any(x in t for x in ("outofstock", "out of stock", "soldout", "sold out", "unavailable", "not available")):
                    return "out_of_stock"

    # Secondary: explicit HTML metadata, not the full page text.
    for tag in soup.select('[itemprop="availability"], meta[property="product:availability"], meta[name="availability"]'):
        raw = tag.get("content") or tag.get_text(" ", strip=True)
        t = norm(raw)
        if any(x in t for x in ("instock", "in stock", "available")):
            return "in_stock"
        if any(x in t for x in ("outofstock", "out of stock", "soldout", "sold out", "unavailable", "not available")):
            return "out_of_stock"

    # Last resort: inspect only elements whose own text is an explicit stock message.
    for node in soup.find_all(string=re.compile(r"\b(?:in stock|out of stock|sold out|not available|unavailable)\b", re.I)):
        t = norm(node)
        if "out of stock" in t or "sold out" in t or "not available" in t or "unavailable" in t:
            return "out_of_stock"
        if "in stock" in t:
            return "in_stock"

    return "unknown"


def _selected_size(soup, data, h1_name):
    """Extract the actually selected bottle size, avoiding stale JSON-LD names."""
    # H1 is authoritative when it contains a size.
    m = re.search(r"(?<!\d)(\d{1,4})\s*ml\b", h1_name or "", re.I)
    if m:
        return int(m.group(1))

    # Selected/checked form controls are the best source for variant pages.
    selectors = [
        'input[type="radio"][checked]',
        'input[type="radio"][aria-checked="true"]',
        'input[checked][name*="size" i]',
        'option[selected]',
        '[aria-selected="true"]',
    ]
    for selector in selectors:
        for node in soup.select(selector):
            chunks = [node.get("value", ""), node.get("aria-label", ""), node.get("data-value", ""), node.get("data-size", ""), node.get_text(" ", strip=True)]
            parent = node.parent
            if parent:
                chunks.append(parent.get_text(" ", strip=True))
            grand = parent.parent if parent else None
            if grand:
                chunks.append(grand.get_text(" ", strip=True))
            blob = " ".join(chunks)
            m = re.search(r"(?<!\d)(\d{1,4})\s*ml\b", blob, re.I)
            if m:
                return int(m.group(1))

    # Fallback to structured name only after H1/selected controls.
    structured_name = clean(data.get("name")) if isinstance(data, dict) else ""
    m = re.search(r"(?<!\d)(\d{1,4})\s*ml\b", structured_name, re.I)
    if m:
        return int(m.group(1))

    return None


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
    h1_name = clean(h1.get_text(" ", strip=True)) if h1 else ""
    # Deloox JSON-LD can contain a stale/SEO size (e.g. 30 ml) while the
    # visible product page offers 50/100 ml. Prefer the visible H1.
    name = h1_name or clean(data.get("name"))

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

    avail = availability_from_sources(data, soup)
    selected_size = _selected_size(soup, data, h1_name)

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
                "value": selected_size,
                "source": "selected_variant_or_product_name",
            } if selected_size is not None else None,
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
    anchor_count = 0
    raw_count = 0

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

        if not re.search(r"/(?:product|produit)/", parsed.path, re.I):
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
        anchor_count += 1
        before = len(found)
        add(a.get("href"), a.get_text(" ", strip=True))
        if len(found) > before:
            raw_count += 1

    # Deloox product cards can keep the product URL outside href (for
    # example in data-* attributes or serialized state). Scan every element
    # attribute as well as the raw document, and support the live Belgian
    # /produit/ path. This is deliberately generic: query matching is still
    # performed against the URL slug/context, and the product page itself is
    # validated again by _product().
    attr_hits = 0
    for tag in soup.find_all(True):
        for value in tag.attrs.values():
            values = value if isinstance(value, (list, tuple)) else [value]
            for raw_value in values:
                if not isinstance(raw_value, str):
                    continue
                for raw in re.findall(
                    r'(?:(?:https?:)?//(?:www\.)?deloox\.be)?'
                    r'/(?:en/|fr/|nl/|it/)?(?:produit|product)/\d+/[^"\'<>\\\s]+',
                    raw_value,
                    re.I,
                ):
                    attr_hits += 1
                    add(raw)

    raw_html = html.replace('\\/', '/')
    patterns = [
        r'https?://(?:www\.)?deloox\.be/(?:en/|fr/|nl/|it/)?(?:produit|product)/\d+/[^"\'<>\\\s]+',
        r'(?:(?:/)(?:en/|fr/|nl/|it/)?(?:produit|product)/\d+/[^"\'<>\\\s]+)',
    ]
    for pattern in patterns:
        for raw in re.findall(pattern, raw_html, re.I):
            add(raw)

    _diag(
        "candidate_urls",
        anchors=anchor_count,
        accepted=raw_count,
        attr_hits=attr_hits,
        total=len(found),
        sample=found[:10],
        query=query,
    )
    return found


def _category_product_line_links(html, query):
    """Find matching Deloox.be Product Line category URLs, fast.

    The live category pages are very large (multi-megabyte).  Do not build a
    BeautifulSoup tree or walk every DOM attribute just to discover a single
    Product Line link.  Scan the raw response first, then use a small amount
    of rendered-text context only when needed.
    """
    text = str(html or "")
    links = []
    seen = set()
    q_tokens = tokens(query)

    def normalize_url(raw_url):
        raw_url = str(raw_url or "").strip()
        if not raw_url:
            return ""
        for _ in range(3):
            raw_url = (raw_url
                       .replace("\\/", "/")
                       .replace("\\u002F", "/")
                       .replace("\\u002f", "/"))
        raw_url = htmllib.unescape(raw_url)
        return urljoin(BASE_URL, raw_url).split("#")[0].split("?")[0]

    def add(raw_url, label=""):
        url = normalize_url(raw_url)
        if not url:
            return
        try:
            parsed = urlparse(url)
        except Exception:
            return
        if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
            return
        if not re.search(r"/(?:category|categoria|categorie)/", parsed.path, re.I):
            return
        slug = parsed.path.rsplit("/", 1)[-1]
        if slug.lower().endswith(".html"):
            slug = slug[:-5]
        if not (q_tokens.issubset(tokens(slug)) or q_tokens.issubset(tokens(label))):
            return
        if url not in seen:
            seen.add(url)
            links.append(url)

    # Raw URL extraction is the cheap path and handles JSON/JS serialization.
    raw = text
    for _ in range(3):
        raw = (raw.replace("\\/", "/")
                  .replace("\\u002F", "/")
                  .replace("\\u002f", "/"))
    raw = htmllib.unescape(raw)

    patterns = (
        r'https?://(?:www\.)?deloox\.be/(?:en/|it/|nl/|fr/)?(?:category|categoria|categorie)/\d+/[^"\'<>\s]+?\.html',
        r'(?<![A-Za-z0-9])/(?:en/|it/|nl/|fr/)?(?:category|categoria|categorie)/\d+/[^"\'<>\s]+?\.html',
    )
    raw_category_count = 0
    for pattern in patterns:
        for raw_url in re.findall(pattern, raw, re.I):
            raw_category_count += 1
            add(raw_url)

    # If the exact Product Line URL is not serialized, recover its category id
    # from a tight window around the requested label.  This avoids reparsing a
    # 6 MB page with BeautifulSoup and is intentionally generic.
    candidate_ids = []
    if not links and q_tokens:
        q_norm = norm(query)
        raw_norm = norm(raw)
        start = 0
        contexts = []
        while True:
            pos = raw_norm.find(q_norm, start)
            if pos < 0:
                break
            contexts.append(raw[max(0, pos - 4000):pos + 4000])
            start = pos + max(1, len(q_norm))
            if len(contexts) >= 8:
                break

        id_patterns = (
            r'(?:categoryId|category_id|productLineId|product_line_id)["\']?\s*[:=]\s*["\']?(\d{4,9})',
            r'(?:data-category-id|data-product-line-id)\s*=\s*["\']?(\d{4,9})',
            r'(?:category|categorie|product.?line)[^0-9]{0,80}(\d{4,9})',
            r'(\d{4,9})[^A-Za-z]{0,80}(?:category|categorie|product.?line)',
        )
        for context in contexts:
            for pattern in id_patterns:
                for value in re.findall(pattern, context, re.I):
                    if value not in candidate_ids:
                        candidate_ids.append(value)

        slug = re.sub(r"[^a-zA-Z0-9]+", "-", query).strip("-").lower()
        for category_id in candidate_ids[:20]:
            add(f"{BASE_URL}/categorie/{category_id}/{slug}.html", query)
            if links:
                break

    _diag("category_links", accepted=len(links), raw_hits=raw_category_count,
          candidate_ids=candidate_ids[:20], query=query, links=links[:20])
    return links

def _category_pages(session):
    """Current generic fragrance catalog roots on Deloox.be.

    The old /category/... roots are obsolete on deloox.be and return 404.
    The live Belgian site exposes its catalog under /categorie/... .
    These are generic catalog roots, not product-specific seeds.
    """
    return (
        BASE_URL + "/categorie/1075732/parfum-homme.html",
        BASE_URL + "/categorie/1000063/parfum-femme.html",
        BASE_URL + "/categorie/1075918/parfum-mixte.html",
    )



def _pagination_urls(page_url, max_pages=3):
    base = page_url.split("?")[0]
    for page in range(1, max_pages + 1):
        yield f"{base}?page={page}"


def _targeted_category_seed_urls(query):
    """Return no product-specific category seeds.

    Discovery remains fully generic: matching Product Line/category URLs are
    discovered from Deloox.be itself by _category_product_line_links().
    """
    return []


def _discover_from_categories(session, query, max_urls=120):
    urls = []
    seen = set()
    visited = set()

    def add_products(html):
        for product_url in _candidate_product_urls(html, query):
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)
                if len(urls) >= max_urls:
                    return True
        return False

    roots = list(_category_pages(session))
    roots.extend(_targeted_category_seed_urls(query))
    _diag("category_roots", count=len(roots), roots=roots, query=query)

    for root in roots:
        try:
            r = session.get(root, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            _diag("root_fetch_error", url=root, error=repr(exc))
            continue
        _diag("root_fetch", url=root, status=r.status_code, bytes=len(r.text or ""))
        if r.status_code >= 400:
            continue

        # First inspect the root itself.  This is the only root-page parse.
        if add_products(r.text):
            return urls[:max_urls]

        # Discover the exact Product Line page.  If none is found, do NOT
        # crawl the root's pagination: the old 100-page expansion was the
        # source of the multi-minute diagnostic/search hang.
        line_links = _category_product_line_links(r.text, query)
        _diag("root_line_links", root=root, count=len(line_links), links=line_links[:20])

        for line_url in line_links:
            if line_url in visited:
                continue
            visited.add(line_url)

            # Fetch the exact Product Line page first, then at most 3 pages of
            # that targeted result if necessary.
            for page_url in _pagination_urls(line_url, max_pages=3):
                if page_url in visited:
                    continue
                visited.add(page_url)
                try:
                    page = session.get(page_url, headers=HEADERS, timeout=TIMEOUT)
                except requests.RequestException as exc:
                    _diag("page_fetch_error", url=page_url, error=repr(exc))
                    continue
                _diag("page_fetch", url=page_url, status=page.status_code, bytes=len(page.text or ""))
                if page.status_code >= 400:
                    continue
                if add_products(page.text):
                    return urls[:max_urls]

    _diag("category_discovery_done", count=len(urls), urls=urls[:20], query=query)
    return urls[:max_urls]

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
        _diag("sitemap_product_fetch", url=sitemap_url, ok=bool(xml), pending=len(pending))
        if not xml:
            continue

        soup = BeautifulSoup(xml, "xml")

        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())
            if not value:
                continue

            low = value.lower()

            if re.search(r"/(?:product|produit)/", low, re.I):
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


def _sitemap_category_urls(session, query, max_sitemaps=12, max_urls=30):
    """Discover relevant Deloox.be category/Product-line pages from sitemaps."""
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

    while pending and len(seen_sitemaps) < max_sitemaps and len(category_urls) < max_urls:
        sitemap_url = pending.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            r = session.get(sitemap_url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            _diag("sitemap_category_error", url=sitemap_url, error=repr(exc))
            continue
        _diag("sitemap_category_fetch", url=sitemap_url, status=r.status_code, bytes=len(r.text or ""))
        if r.status_code >= 400:
            continue

        body = (r.text or "").lstrip()
        ctype = (r.headers.get("content-type") or "").lower()
        if "xml" not in ctype and not body.startswith(("<?xml", "<urlset", "<sitemapindex")):
            continue

        soup = BeautifulSoup(r.text, "xml")
        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())
            if not value:
                continue
            low = value.lower()
            if re.search(r"/(?:category|categoria|categorie)/", low) and low.endswith(".html"):
                slug = low.rsplit("/", 1)[-1][:-5]
                if query_tokens.issubset(tokens(slug)) and value not in seen_categories:
                    seen_categories.add(value)
                    category_urls.append(value)
                    if len(category_urls) >= max_urls:
                        break
            elif low.endswith(".xml") or "sitemap" in low:
                if value not in seen_sitemaps:
                    pending.append(value)

    _diag("sitemap_category_done", count=len(category_urls), urls=category_urls[:30], query=query)
    return category_urls[:max_urls]


def _discover(session, q):
    """Discover Deloox.be product pages generically for the requested query."""
    urls = []
    seen = set()
    _diag("discover_start", query=q, base_url=BASE_URL)

    # PRIMARY: current category / Product-line structure.
    category_products = _discover_from_categories(session, q, max_urls=80)
    _diag("discover_primary", count=len(category_products), urls=category_products[:20])
    for url in category_products:
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= 80:
            return urls[:80]

    # SECONDARY: Product-line/category pages exposed by Deloox.be sitemaps.
    sitemap_categories = _sitemap_category_urls(
        session, q, max_sitemaps=12, max_urls=30
    )
    _diag("discover_sitemap_categories", count=len(sitemap_categories), urls=sitemap_categories[:30])
    for category_url in sitemap_categories:
        try:
            page = session.get(category_url, headers=HEADERS, timeout=TIMEOUT)
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

    # TERTIARY: localized search endpoints, retained as fallback.
    endpoints = [
        BASE_URL + "/en/search?query=" + quote_plus(q),
        BASE_URL + "/en/search?search=" + quote_plus(q),
        BASE_URL + "/en?search=" + quote_plus(q),
        BASE_URL + "/en/search?q=" + quote_plus(q),
        BASE_URL + "/nl/zoeken?query=" + quote_plus(q),
        BASE_URL + "/nl/zoeken?q=" + quote_plus(q),
        BASE_URL + "/fr/recherche?query=" + quote_plus(q),
        BASE_URL + "/fr/recherche?q=" + quote_plus(q),
    ]
    for endpoint in endpoints:
        try:
            r = session.get(endpoint, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            _diag("search_endpoint_error", endpoint=endpoint, error=repr(exc))
            continue
        _diag("search_endpoint", endpoint=endpoint, status=r.status_code, bytes=len(r.text or ""))
        if r.status_code >= 400:
            continue
        endpoint_products = _candidate_product_urls(r.text, q)
        _diag("search_endpoint_products", endpoint=endpoint, count=len(endpoint_products), urls=endpoint_products[:20])
        for url in endpoint_products:
            if url not in seen:
                seen.add(url)
                urls.append(url)
        if len(urls) >= 80:
            return urls[:80]

    # LAST RESORT: product sitemap discovery.
    for url in _sitemap_product_urls(session, q, max_sitemaps=12, max_urls=80):
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= 80:
            break

    _diag("discover_done", count=len(urls), urls=urls[:80], query=q)
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
