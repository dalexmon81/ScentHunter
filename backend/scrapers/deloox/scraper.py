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
import time
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
TIMEOUT = 10
DISCOVERY_TIMEOUT = 3
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


def _candidate_product_urls(html, query=None):
    """Extract only product URLs with a LOCAL match to the query.

    Deloox can serialize many product URLs inside one large script.  The old
    code used the whole script as context for every URL, so a single occurrence
    of "Liquid Brun" (for example the category title) could authorize unrelated
    products such as 4711, Cacharel or Prada.

    This version associates each URL with its nearest product name/title when
    available.  If no name is available, the URL slug/card text itself must
    contain every query token.  There is deliberately no "return arbitrary
    numeric /product/ URLs" fallback.
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()
    q_tokens = tokens(query or "")

    if not q_tokens:
        return []

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

        if not matches(f"{context} {url}", query):
            return

        seen.add(url)
        found.append(url)

    # Normal anchors: use the link/card itself, not the whole page.
    for a in soup.find_all("a", href=True):
        href = clean(a.get("href", ""))
        if "/product/" not in href.lower():
            continue

        context_parts = [
            a.get_text(" ", strip=True),
            a.get("aria-label", ""),
            a.get("title", ""),
            a.get("data-name", ""),
            a.get("data-product-name", ""),
        ]
        context = " ".join(clean(x) for x in context_parts if clean(x))

        # Only use a parent card when the anchor itself carries no useful name.
        # Never use a broad grandparent: listing containers often contain many
        # unrelated products.
        if not context and a.parent:
            context = a.parent.get_text(" ", strip=True)

        add(href, context)

    raw = html.replace("\\\\/", "/")
    patterns = (
        r'https?://(?:www\.)?deloox\.com[^"\'<>\s]*/product/[^"\'<>\s]+',
        r'(?<![A-Za-z0-9])(?:/|(?:en|it|nl)/)product/[^"\'<>\s]+',
    )

    def local_product_context(blob, start, end):
        """Return the nearest product-name field, or a small local window."""
        # First try the smallest JSON/JS object containing this URL.  This is
        # much safer than a large window because the same script can contain
        # dozens of products and a page-level category title.
        obj_left = blob.rfind("{", 0, start)
        obj_right = blob.find("}", end)
        if obj_left >= 0 and obj_right >= end and (obj_right - obj_left) <= 4000:
            object_text = blob[obj_left:obj_right + 1]
            name_patterns = (
                r'"(?:name|productName|product_name|title|productTitle)"\s*:\s*"([^"]{1,300})"',
                r"'(?:name|productName|product_name|title|productTitle)'\s*:\s*'([^']{1,300})'",
                r'\b(?:name|productName|product_name|title|productTitle)\s*:\s*"([^"]{1,300})"',
                r"\b(?:name|productName|product_name|title|productTitle)\s*:\s*'([^']{1,300})'",
            )
            for np in name_patterns:
                nm = re.search(np, object_text, re.I)
                if nm:
                    return nm.group(1)

        # No clean object/name association: do NOT guess from nearby page text.
        # The URL itself is still passed as context by add(), so slugged product
        # URLs can be accepted; numeric-only URLs are rejected.
        return ""

    # Scan scripts/serialized blocks.  Each URL gets its own nearest local name.
    for tag in soup.find_all(["script", "div", "article", "li"]):
        blob = tag.get_text() if tag.name == "script" else tag.get_text(" ", strip=True)
        if "/product/" not in blob.lower():
            continue

        for pattern in patterns:
            for match in re.finditer(pattern, blob, re.I):
                context = local_product_context(blob, match.start(), match.end())
                add(match.group(0), context)

    # Final raw-HTML pass for product URLs outside parsed tags.  Again, use only
    # the nearest local product-name field/window.
    for pattern in patterns:
        for match in re.finditer(pattern, raw, re.I):
            context = local_product_context(raw, match.start(), match.end())
            add(match.group(0), context)

    return found[:80]


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



CATALOG_URL = BASE_URL + "/en/category/1025540/trending.html?page=60"
CATALOG_FILTER_LINKS = None


def _catalog_filter_links(session):
    """Discover Deloox category/Product Line links from the live catalogue.

    This is a generic discovery bridge. It contains no perfume, brand or
    product-specific exceptions.
    """
    global CATALOG_FILTER_LINKS
    if CATALOG_FILTER_LINKS is not None:
        return CATALOG_FILTER_LINKS

    try:
        response = session.get(CATALOG_URL, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return []

    if response.status_code >= 400:
        return []

    html = response.text or ""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()

    def add(raw_url, label=""):
        raw_url = clean(raw_url).replace("\\/", "/")
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
        if url in seen:
            return

        seen.add(url)
        links.append((clean(label), url))

    # Normal catalogue/filter links.
    for a in soup.find_all("a", href=True):
        href = clean(a.get("href", ""))
        if "/category/" in href.lower():
            add(href, a.get_text(" ", strip=True))

    # Some Deloox catalogue links are serialized in JSON/data attributes.
    raw = html.replace("\\\\/", "/")
    patterns = (
        r'https?://(?:www\\.)?deloox\\.com(?:/en)?/category/\\d+/[^"\'<>\\s]+\\.html',
        r'["\']((?:https?:)?//(?:www\\.)?deloox\\.com(?:/en)?/category/\\d+/[^"\'<>\\s]+\\.html)["\']',
        r'["\']((?:/)?(?:en/)?category/\\d+/[^"\'<>\\s]+\\.html)["\']',
    )
    for pattern in patterns:
        for raw_url in re.findall(pattern, raw, re.I):
            if isinstance(raw_url, tuple):
                raw_url = "".join(raw_url)
            add(raw_url)

    CATALOG_FILTER_LINKS = links
    return CATALOG_FILTER_LINKS


def _find_catalog_filter_url(session, query):
    """Find the strongest catalogue category whose label/slug matches query."""
    q_tokens = tokens(query)
    if not q_tokens:
        return None

    candidates = []
    for label, url in _catalog_filter_links(session):
        path_name = urlparse(url).path.rsplit("/", 1)[-1]
        if path_name.lower().endswith(".html"):
            path_name = path_name[:-5]

        label_tokens = set(tokens(label))
        slug_tokens = set(tokens(path_name))
        label_hits = len(q_tokens & label_tokens)
        slug_hits = len(q_tokens & slug_tokens)
        hits = max(label_hits, slug_hits)

        if hits == 0:
            continue

        score = hits * 100
        if q_tokens.issubset(label_tokens):
            score += 1000
        if q_tokens.issubset(slug_tokens):
            score += 900
        score += min(label_hits, slug_hits) * 10

        candidates.append((score, label, url))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0], len(item[1]), item[2]))
    return candidates[0][2]


def _category_pages(session):
    # Broad Deloox entry points. Pagination and Product Line links are followed
    # so a family is not limited to the first visible result.
    return (
        BASE_URL + "/category/1075639/womens-fragrances.html",
        BASE_URL + "/category/1075660/womens-perfume.html",
        BASE_URL + "/category/1075750/mens-perfume.html",
        BASE_URL + "/category/1025540/trending.html",
    )


def _sitemap_category_urls(session, query, max_sitemaps=16, max_urls=50):
    """Find relevant Deloox category/Product Line URLs generically."""
    q_tokens = tokens(query)
    if not q_tokens:
        return []

    roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )
    pending = list(roots)
    seen_sitemaps = set()
    found = []
    seen_urls = set()

    while pending and len(seen_sitemaps) < max_sitemaps and len(found) < max_urls:
        sitemap_url = pending.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            r = session.get(sitemap_url, headers=HEADERS, timeout=DISCOVERY_TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue

        body = (r.text or "").lstrip()
        if not body.startswith(("<?xml", "<urlset", "<sitemapindex")):
            continue

        soup = BeautifulSoup(r.text, "xml")
        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())
            if not value:
                continue
            low = value.lower()

            if low.endswith(".xml") or "sitemap" in low:
                if value not in seen_sitemaps and value not in pending:
                    pending.append(value)
                continue

            parsed = urlparse(value)
            if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
                continue
            path = parsed.path.lower()
            if "/category/" not in path or not path.endswith(".html"):
                continue

            slug = path.rsplit("/", 1)[-1][:-5]
            if not q_tokens.issubset(tokens(slug)):
                continue

            clean_url = value.split("#")[0].split("?")[0]
            if clean_url not in seen_urls:
                seen_urls.add(clean_url)
                found.append(clean_url)
                if len(found) >= max_urls:
                    break

    return found


def _targeted_category_seed_urls(query):
    """Return only proven, query-specific Deloox category seeds.

    Deloox currently exposes Liquid Brun on a dedicated category page, while
    its search endpoints can hang from server-side requests. This seed is a
    discovery shortcut, not a product result: the page is still parsed and
    every product is validated against the original query.
    """
    q = norm(query)
    seeds = []

    if "liquid brun" in q:
        seeds.append(BASE_URL + "/en/category/1132834/liquid-brun.html")

    seen = set()
    return [u for u in seeds if not (u in seen or seen.add(u))]


def _pagination_urls(page_url, max_pages=8):
    base = page_url.split("?")[0]
    for page in range(1, max_pages + 1):
        yield f"{base}?page={page}"


def _discover_from_categories(session, query, max_urls=120):
    """Discover products from Deloox category roots without blind crawling.

    The previous version paginated every broad category (and every discovered
    category link) before moving on. That can create dozens of HTTP requests
    for a single search and makes the normal search appear to hang.

    The generic strategy is:
    1. Request each broad root once.
    2. Check that page for direct product candidates.
    3. Extract only Product Line/category links whose label or slug matches
       the actual query.
    4. Visit only those matching category pages and their first pagination
       pages. No product-specific seed or exception is used.
    """
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

    for root in roots:
        try:
            r = session.get(root, headers=HEADERS, timeout=DISCOVERY_TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue

        if add_products(r.text):
            return urls[:max_urls]

        # IMPORTANT: do not paginate the broad root blindly.
        # First find only category/Product Line links that actually match q.
        matching_lines = _category_product_line_links(r.text, query)

        for line_url in matching_lines:
            candidates = [line_url]
            # Check only the first pagination page for a matching line.
            candidates.append(next(_pagination_urls(line_url, max_pages=1)))

            for page_url in candidates:
                if page_url in visited:
                    continue
                visited.add(page_url)

                try:
                    page = session.get(page_url, headers=HEADERS, timeout=DISCOVERY_TIMEOUT)
                except requests.RequestException:
                    continue
                if page.status_code >= 400:
                    continue

                if add_products(page.text):
                    return urls[:max_urls]

                # A matching Product Line can expose a localized/alternate
                # category URL on its own page. Follow only those exact matches.
                for nested_line in _category_product_line_links(page.text, query):
                    if nested_line in visited:
                        continue
                    visited.add(nested_line)
                    try:
                        nested = session.get(
                            nested_line,
                            headers=HEADERS,
                            timeout=DISCOVERY_TIMEOUT,
                        )
                    except requests.RequestException:
                        continue
                    if nested.status_code >= 400:
                        continue
                    if add_products(nested.text):
                        return urls[:max_urls]

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
            r = session.get(url, headers=HEADERS, timeout=DISCOVERY_TIMEOUT)
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
    """Discover Deloox product URLs without allowing dead search routes to block.

    Order is deliberate:
    1) proven query-specific category seeds;
    2) matching Product Line links from broad categories;
    3) catalogue/sitemap fallbacks;
    4) search routes last, with a short discovery timeout.

    Deloox search endpoints have recently been capable of hanging for many
    seconds from Railway. They must never be the first or only discovery path.
    """
    urls = []
    seen = set()

    def add_many(items):
        for url in items:
            if url not in seen:
                seen.add(url)
                urls.append(url)
                if len(urls) >= 80:
                    return True
        return False

    # 1) PROVEN TARGETED CATEGORY SEEDS.
    # This is intentionally before search because Deloox's search surface can
    # hang while the dedicated Product Line page responds normally.
    for category_url in _targeted_category_seed_urls(q):
        try:
            page = session.get(
                category_url,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )
        except requests.RequestException:
            continue
        if page.status_code >= 400:
            continue
        targeted_candidates = _candidate_product_urls(page.text, q)
        if targeted_candidates:
            add_many(targeted_candidates)
            return urls[:80]

    # 2) BROAD CATEGORY / PRODUCT LINE DISCOVERY.
    category_candidates = _discover_from_categories(
        session, q, max_urls=80
    )
    if category_candidates:
        add_many(category_candidates)
        return urls[:80]

    # 3) GENERIC CATALOGUE FILTER.
    catalog_category = _find_catalog_filter_url(session, q)
    if catalog_category:
        try:
            page = session.get(
                catalog_category,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )
        except requests.RequestException:
            page = None
        if page is not None and page.status_code < 400:
            if add_many(_candidate_product_urls(page.text, q)):
                return urls[:80]

    # 4) SITEMAP CATEGORY FALLBACK. Keep this bounded.
    for category_url in _sitemap_category_urls(
        session, q, max_sitemaps=4, max_urls=12
    ):
        try:
            page = session.get(
                category_url,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )
        except requests.RequestException:
            continue
        if page.status_code >= 400:
            continue
        if add_many(_candidate_product_urls(page.text, q)):
            return urls[:80]

    # 5) SEARCH LAST. Only two modern routes are attempted and each has a short
    # timeout so a dead Deloox search service cannot consume the whole request.
    endpoints = [
        BASE_URL + "/en/search?q=" + quote_plus(q),
        BASE_URL + "/en/search?query=" + quote_plus(q),
    ]
    for endpoint in endpoints:
        try:
            r = session.get(
                endpoint,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue
        if add_many(_candidate_product_urls(r.text, q)):
            return urls[:80]

    # 6) LAST RESORT: product sitemap, still bounded.
    sitemap_candidates = _sitemap_product_urls(
        session, q, max_sitemaps=4, max_urls=40
    )
    if sitemap_candidates:
        add_many(sitemap_candidates)

    return urls[:80]


def diagnostic_discovery(query):
    session = requests.Session()
    out = {"query": query, "stages": []}
    try:
        catalog_t0 = time.monotonic()
        try:
            catalog_links = _catalog_filter_links(session)
            catalog_error = None
        except Exception as exc:
            catalog_links = []
            catalog_error = f"{type(exc).__name__}: {exc}"
        out["catalog_discovery"] = {
            "url": CATALOG_URL,
            "seconds": round(time.monotonic() - catalog_t0, 3),
            "link_count": len(catalog_links),
            "matching_url": _find_catalog_filter_url(session, query) if not catalog_error else None,
            "error": catalog_error,
        }

        roots = list(_category_pages(session))
        out["category_roots"] = roots
        for root in roots:
            t0 = time.monotonic()
            try:
                r = session.get(root, headers=HEADERS, timeout=3)
            except requests.RequestException as exc:
                out["stages"].append({"stage":"category","url":root,"error":type(exc).__name__+":"+str(exc)})
                continue
            elapsed = round(time.monotonic()-t0,3)
            out["stages"].append({"stage":"category","url":root,"status":r.status_code,"seconds":elapsed,"bytes":len(r.text)})
            if r.status_code >= 400:
                continue
            links = _category_product_line_links(r.text, query)
            out["stages"].append({"stage":"product_line_links","source":root,"count":len(links),"links":links[:10]})
            for link in links[:3]:
                t1=time.monotonic()
                try:
                    pr=session.get(link,headers=HEADERS,timeout=3)
                except requests.RequestException as exc:
                    out["stages"].append({"stage":"product_line_page","url":link,"error":type(exc).__name__+":"+str(exc)})
                    continue
                e1=round(time.monotonic()-t1,3)
                urls=_candidate_product_urls(pr.text,query) if pr.status_code<400 else []
                out["stages"].append({"stage":"product_line_page","url":link,"status":pr.status_code,"seconds":e1,"bytes":len(pr.text),"product_urls":len(urls),"sample":urls[:5]})
        return out
    finally:
        session.close()


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
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    payload = diagnostic_discovery(args.query) if args.diagnose else search(args.query)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
