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
BASE_URL = "https://www.deloox.be"
TIMEOUT = 1.5
DISCOVERY_DEADLINE = 5.5
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


def _selected_size(soup, data, h1_name, url=""):
    """Extract the actually selected bottle size, avoiding stale JSON-LD names."""
    # H1 is authoritative when it contains a size.
    m = re.search(r"(?<!\d)(\d{1,4})\s*ml\b", h1_name or "", re.I)
    if m:
        return int(m.group(1))

    # Deloox product URLs normally contain the canonical bottle size, e.g.
    # .../liquid-brun-eau-de-parfum-100-ml.html. This is stronger than a
    # generic page-text scan because it cannot accidentally pick a size from
    # a recommendation/review elsewhere on the page.
    m = re.search(r"(?:-|/)(\d{1,4})\s*[-_]?ml(?:\.html)?(?:$|[?#])", url or "", re.I)
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
    selected_size = _selected_size(soup, data, h1_name, url)

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
    """Discover product URLs broadly; strict identity validation happens in _product().

    Important: discovery must NOT contain hard-coded product exceptions and must not
    require the entire query to be present in the href. Deloox often stores the product
    name in card text/JSON while the href is only a numeric product URL.
    """
    soup = BeautifulSoup(html, "html.parser")
    scored = {}
    q_tokens = tokens(query or "")

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
        if not ("/product/" in parsed.path.lower() or "/produit/" in parsed.path.lower()):
            return

        haystack = norm(f"{context} {url}")
        hits = sum(1 for tok in q_tokens if tok in haystack)
        # Do not discard numeric product URLs merely because the query is not
        # present in the href/card text. Deloox can expose product IDs without
        # the name in the surrounding HTML. The final _product() parser remains
        # the authoritative query validator.
        previous = scored.get(url)
        if previous is None or hits > previous[0]:
            scored[url] = (hits, context)

    for a in soup.find_all("a", href=True):
        add(a.get("href"), a.get_text(" ", strip=True))

    # Raw HTML / JS product URLs.
    patterns = [
        r'https?://(?:www\.)?deloox\.be/[^"\'>\s]+/(?:product|produit)/[^"\'>\s]+',
        r'["\']((?:/)?(?:en/|it/|nl/)?product/[^"\']+)["\']',
        r'["\']((?:https?:)?//(?:www\.)?deloox\.be/[^"\']*/(?:product|produit)/[^"\']+)["\']',
    ]
    for pattern in patterns:
        for raw in re.findall(pattern, html, re.I):
            if isinstance(raw, tuple):
                raw = "".join(raw)
            add(raw, "")

    # Serialized JSON / data attributes may contain product names next to URLs.
    for tag in soup.find_all(["script", "div", "article", "li"]):
        blob = str(tag)
        if not ("/product/" in blob.lower() or "/produit/" in blob.lower()):
            continue
        urls = re.findall(r'(?:(?:https?:)?//(?:www\.)?deloox\.be)?[^"\'<>\s]*?/(?:product|produit)/[^"\'<>\s]+', blob, re.I)
        text = tag.get_text(" ", strip=True)[:1000]
        for raw in urls:
            add(raw, text)

    ordered = sorted(
        scored.items(),
        key=lambda item: (-item[1][0], len(item[0]), item[0])
    )

    # Prefer candidates whose surrounding card/serialized data actually contains
    # query tokens. If Deloox exposes only numeric product URLs with no useful
    # context, keep a bounded fallback set anyway and let _product() perform the
    # authoritative name validation on the product page.
    exact = [
        url for url, meta in ordered
        if q_tokens and meta[0] == len(q_tokens)
    ]
    if exact:
        return exact[:80]

    # Never feed unrelated products into the parser just because a broad
    # category page exposed numeric product URLs. If the query is not present
    # in the discovery context, return no candidate and let the caller continue
    # with the next bounded discovery page.
    return []


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
        if not ("/category/" in parsed.path.lower() or "/categorie/" in parsed.path.lower()):
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
        r'(/(?:en/|fr/|it/|nl/|de/)?(?:category|categorie)/\\d+/[^"\\\'<>\\s]+\\.html)',
        r'(?:"|\\\')((?:/)?(?:en/|fr/|it/|nl/|de/)?(?:category|categorie)/\\d+/[^"\\\'<>\\s]+\\.html)(?:"|\\\')',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, raw, re.I):
            if isinstance(match, tuple):
                match = "".join(match)
            add(match)

    return links



CATALOG_URL = BASE_URL + "/categorie/1025540/tendances.html?page=60"
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

        if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
            return
        if not ("/category/" in parsed.path.lower() or "/categorie/" in parsed.path.lower()):
            return
        if url in seen:
            return

        seen.add(url)
        links.append((clean(label), url))

    # Normal catalogue/filter links.
    for a in soup.find_all("a", href=True):
        href = clean(a.get("href", ""))
        if "/category/" in href.lower() or "/categorie/" in href.lower():
            add(href, a.get_text(" ", strip=True))

    # Some Deloox catalogue links are serialized in JSON/data attributes.
    raw = html.replace("\\\\/", "/")
    patterns = (
        r'https?://(?:www\\.)?deloox\\.be(?:/en)?/category/\\d+/[^"\'<>\\s]+\\.html',
        r'["\']((?:https?:)?//(?:www\\.)?deloox\\.be(?:/en)?/category/\\d+/[^"\'<>\\s]+\\.html)["\']',
        r'["\']((?:/)?(?:en/|fr/|it/|nl/|de/)?(?:category|categorie)/\\d+/[^"\'<>\\s]+\\.html)["\']',
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
    # Current Deloox Belgium catalogue entry points. Keep the men's category
    # first because queries for men's fragrances (including French Avenue)
    # should reach the relevant catalogue immediately.
    return (
        BASE_URL + "/categorie/1075732/parfum-homme.html",
        BASE_URL + "/categorie/1075639/parfums-femme.html",
        BASE_URL + "/categorie/1075660/parfum-femme.html",
        BASE_URL + "/categorie/1025540/tendances.html",
    )


def _sitemap_category_urls(session, query, max_sitemaps=3, max_urls=20):
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
            r = session.get(sitemap_url, headers=HEADERS, timeout=request_timeout)
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
            if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
                continue
            path = parsed.path.lower()
            if not ("/category/" in path or "/categorie/" in path) or not path.endswith(".html"):
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
    """No product-specific exceptions. Discovery must work generically."""
    return []


def _pagination_urls(page_url, max_pages=8):
    base = page_url.split("?")[0]
    for page in range(1, max_pages + 1):
        yield f"{base}?page={page}"



def _filter_target_urls(html, query):
    """Recover category/filter targets represented as labels, forms or data attrs.

    Deloox's broad catalogue can render a Product Line such as "Liquid Brun"
    as a filter control rather than as a normal category <a>. The old discovery
    only accepted /categorie/... links, so the filter was visible in the HTML
    but never followed. This helper converts the matching control into a real
    URL when the page exposes either a direct URL or a GET form/value pair.
    """
    soup = BeautifulSoup(html, "html.parser")
    q = norm(query)
    qt = tokens(query)
    if not q or not qt:
        return []

    out, seen = [], set()

    def add(raw):
        if not raw:
            return
        raw = clean(str(raw)).replace("\\/", "/")
        if raw.startswith(("javascript:", "mailto:", "#")):
            return
        u = urljoin(BASE_URL, raw).split("#")[0]
        try:
            parsed = urlparse(u)
        except Exception:
            return
        if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
            return
        path = parsed.path.lower()
        if "/category/" not in path and "/categorie/" not in path:
            return
        if u not in seen:
            seen.add(u)
            out.append(u)

    def attrs_urls(node):
        for key, value in getattr(node, "attrs", {}).items():
            if key.lower() in {"action", "method", "class", "id", "name", "value"}:
                continue
            if isinstance(value, (list, tuple)):
                value = " ".join(map(str, value))
            if not isinstance(value, str):
                continue
            low = value.lower()
            if "category" in low or "categorie" in low:
                add(value)

    # Exact/near-exact text nodes for the requested Product Line.
    targets = []
    for node in soup.find_all(["a", "label", "span", "div", "li", "option"]):
        text = norm(node.get_text(" ", strip=True))
        if not text:
            continue
        tt = tokens(text)
        if qt.issubset(tt) and len(text) <= max(80, len(q) + 35):
            targets.append(node)

    for node in targets[:30]:
        # Direct and ancestor data attributes / hrefs.
        cur = node
        for _ in range(5):
            if cur is None:
                break
            attrs_urls(cur)
            for attr in ("href", "data-href", "data-url", "data-link", "data-target", "data-filter-url", "value"):
                value = cur.get(attr)
                if isinstance(value, str) and ("category" in value.lower() or "categorie" in value.lower()):
                    add(value)
            cur = cur.parent

        # GET form fallback: build the action URL from the matching control's
        # name/value. This is generic and does not assume a parameter name.
        form = node.find_parent("form")
        if form:
            action = form.get("action") or ""
            method = (form.get("method") or "get").lower()
            if method == "get" and action:
                from urllib.parse import urlencode
                params = {}
                for inp in form.find_all(["input", "select"]):
                    name = inp.get("name")
                    if not name:
                        continue
                    if inp.name == "input":
                        typ = (inp.get("type") or "text").lower()
                        if typ in {"submit", "button", "reset"}:
                            continue
                        value = inp.get("value")
                    else:
                        selected = inp.find("option", selected=True) or inp.find("option")
                        value = selected.get("value") if selected else None
                    if value is not None:
                        params[str(name)] = str(value)
                # Prefer the control that visibly contains the query.
                if params:
                    add(urljoin(BASE_URL, action) + "?" + urlencode(params))

    return out

def _discover_from_categories(session, query, max_urls=120, deadline=None):
    """Discover products through Deloox's category/filter hierarchy.

    Deloox can contain the searched product text in a broad catalogue page while
    the actual product link is hidden behind a category/filter relation. We first
    rank category URLs by proximity to the query text in the raw HTML, then visit
    only the strongest matching category pages. No product-specific URL is used.
    """
    urls, seen = [], set()

    def add_products(html):
        for u in _candidate_product_urls(html, query):
            if u not in seen:
                seen.add(u)
                urls.append(u)
                if len(urls) >= max_urls:
                    return True
        return False

    def category_candidates(html):
        soup = BeautifulSoup(html, "html.parser")
        q = norm(query)
        qt = tokens(query)
        scored = {}

        def consider(raw, label="", proximity=999999):
            if not raw:
                return
            u = urljoin(BASE_URL, clean(raw).replace('\\/', '/')).split('#')[0]
            try:
                parsed = urlparse(u)
            except Exception:
                return
            if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
                return
            path = parsed.path.lower()
            if "/category/" not in path and "/categorie/" not in path:
                return
            slug = path.rsplit('/', 1)[-1].removesuffix('.html')
            hay = norm(f"{label} {slug}")
            hits = sum(1 for t in qt if t in hay)
            # A category with both query tokens is strongest. Otherwise use
            # proximity to the literal query in the page as the signal.
            score = (hits * 1000) - min(proximity, 500)
            prev = scored.get(u)
            if prev is None or score > prev[0]:
                scored[u] = (score, proximity, label)

        for a in soup.find_all('a', href=True):
            label = a.get_text(' ', strip=True)
            consider(a.get('href'), label)

        # Generic raw-HTML proximity: the query can be present in JSON/text
        # while the useful category URL is nearby but not an <a> with matching
        # visible text. This is the key gap in the old discovery implementation.
        raw = html.replace('\\/', '/')
        cat_re = re.compile(r'https?://(?:www\\.)?deloox\\.be/(?:[^"\'<>\\s]*/)?(?:category|categorie)/\\d+/[^"\'<>\\s]+?\\.html|/(?:en/|fr/|it/|nl/|de/)?(?:category|categorie)/\\d+/[^"\'<>\\s]+?\\.html', re.I)
        positions = [m.start() for m in re.finditer(re.escape(q), norm(raw), re.I)] if q else []
        allcats = list(cat_re.finditer(raw))
        for m in allcats:
            near = min((abs(m.start()-pos) for pos in positions), default=999999)
            # Keep a generous local window: serialized product/filter data can
            # place the relation several KB away from the visible query text.
            if near <= 30000:
                consider(m.group(0), raw[max(0,m.start()-800):m.end()+800], near)

        return [u for u, _ in sorted(scored.items(), key=lambda kv: (-kv[1][0], kv[1][1], kv[0]))]

    roots = list(_category_pages(session))[:2]
    for root in roots:
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            remaining = TIMEOUT if deadline is None else max(0.5, min(TIMEOUT, deadline - time.monotonic()))
            if deadline is not None and remaining <= 0:
                break
            r = session.get(root, headers=HEADERS, timeout=remaining)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue
        html = r.text
        if add_products(html):
            return urls[:max_urls]

        # Product Line filters can be rendered as labels/forms rather than
        # category anchors. Try those targets before generic category links.
        filter_targets = _filter_target_urls(html, query)
        for cat_url in (filter_targets + category_candidates(html))[:4]:
            if deadline is not None and time.monotonic() >= deadline:
                break
            try:
                remaining = TIMEOUT if deadline is None else max(0.5, min(TIMEOUT, deadline - time.monotonic()))
                if deadline is not None and remaining <= 0:
                    break
                page = session.get(cat_url, headers=HEADERS, timeout=remaining)
            except requests.RequestException:
                continue
            if page.status_code >= 400:
                continue
            if add_products(page.text):
                return urls[:max_urls]

            # Follow only category links that are still query-relevant.
            for nested in category_candidates(page.text)[:1]:
                if nested == cat_url:
                    continue
                if deadline is not None and time.monotonic() >= deadline:
                    break
                try:
                    remaining = TIMEOUT if deadline is None else max(0.5, min(TIMEOUT, deadline - time.monotonic()))
                    if deadline is not None and remaining <= 0:
                        break
                    child = session.get(nested, headers=HEADERS, timeout=remaining)
                except requests.RequestException:
                    continue
                if child.status_code < 400 and add_products(child.text):
                    return urls[:max_urls]

    return urls[:max_urls]


def _sitemap_product_urls(session, query, max_sitemaps=2, max_urls=8, request_timeout=1.8):
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

            if "/(?:product|produit)/" in low or "/produit/" in low:
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
    """Bounded, query-faithful Deloox discovery.

    The live Deloox catalogue exposes the requested perfume through its
    Product-line/category filter layer. Broad pagination is both slow and
    unreliable, so use the existing generic category-link discovery first.
    No product-specific URL is hard-coded.
    """
    started = time.monotonic()
    deadline = started + DISCOVERY_DEADLINE

    # This path is already generic: it looks for Product Line/category links
    # whose visible label or slug matches the user's query, then parses only
    # the matching category page(s). This is the important layer that the
    # previous parallel broad-pagination implementation bypassed.
    try:
        results = _discover_from_categories(session, q, max_urls=8, deadline=deadline)
        if results:
            return results[:8]
    except Exception:
        pass

    # Small fallback: inspect the four public fragrance roots once. This is
    # deliberately bounded and only accepts product URLs when the surrounding
    # card contains the requested query.
    for root in _category_pages(session):
        if time.monotonic() >= deadline:
            break
        try:
            remaining = max(1.0, min(TIMEOUT, deadline - time.monotonic()))
            r = session.get(root, headers=HEADERS, timeout=remaining)
            if r.status_code >= 400:
                continue
            candidates = _candidate_product_urls(r.text, q)
            if candidates:
                return candidates[:8]
        except requests.RequestException:
            continue

    return []
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

    discovered = []
    session = requests.Session()
    try:
        discovered = _discover(session, query)[:8]
    finally:
        session.close()

    if not discovered:
        return []

    # Product pages are independent. Fetch a small bounded set concurrently so
    # one slow/invalid Deloox product cannot serialize all candidates.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch_one(url):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            return None
        if r.status_code >= 400:
            return None
        return _product(url, r.text, query)

    results = []
    seen = set()
    with ThreadPoolExecutor(max_workers=min(4, len(discovered))) as pool:
        futures = [pool.submit(fetch_one, url) for url in discovered]
        for future in as_completed(futures):
            item = future.result()
            if not item:
                continue
            sku_value = None
            sku = item["identity"].get("sku")
            if sku:
                sku_value = sku.get("value")
            key = (item["url"].rstrip("/"), sku_value)
            if key in seen:
                continue
            seen.add(key)
            results.append(item)

    return results

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
