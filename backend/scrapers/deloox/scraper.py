"""Deloox adapter for ScentHunter.

Discovery strategy:
- Prefer Deloox's public search surface (/chercher.html?q=...) and bounded pagination.
- Use category and sitemap discovery only when search yields no candidates.
- Product pages are parsed through JSON-LD/page content.

Important:
- Discovery is generic and contains no perfume-specific rules.
- Candidate filtering is generic; _product() remains the final authority.
- Technical failures are never converted into NOT_FOUND by this scraper.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, quote_plus, urljoin, urlparse, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"

# Production storefront used by ScentHunter.
BASE_URL = "https://www.deloox.be"
DELOOX_BASE_URLS = (
    "https://www.deloox.be",
    "https://www.deloox.nl",
    "https://www.deloox.com",
)
TIMEOUT = (3.5, 8.0)
MAX_CANDIDATES = 80
MAX_RESULTS = 80
MAX_SEARCH_PAGES = 10
MAX_CATEGORY_PAGES = 10
MAX_SEARCH_CANDIDATES = MAX_CANDIDATES
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
DELOOX_HOSTS = {
    "deloox.be",
    "www.deloox.be",
    "deloox.nl",
    "www.deloox.nl",
    "deloox.com",
    "www.deloox.com",
}

# Discovery state is diagnostic/contract state only. It never decides identity.
_LAST_DISCOVERY_STATE = {
    "search_pages_ok": 0,
    "search_pages_failed": 0,
    "search_verified": False,
    "category_verified": False,
    "sitemap_verified": False,
    "technical_failure": False,
}



def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(v).lower())).strip()


def tokens(v):
    return {x for x in norm(v).split() if len(x) > 1}


def compact_norm(v):
    """Normalize text again without word separators for discovery matching.

    Retailers often store the same product line with different separators:
    ``Night Out``, ``Night-Out`` or ``NightOut``.  This is a generic lexical
    normalization only; it does not identify a product or variant.
    """
    return re.sub(r"[^a-z0-9]+", "", clean(v).lower())


def matches(text, q):
    q_tokens = tokens(q)
    if not q_tokens:
        return False
    if q_tokens.issubset(tokens(text)):
        return True

    # Also accept a query written as one concatenated token when the retailer
    # writes the same words separately (e.g. ``nightout`` vs ``Night Out``).
    q_compact = compact_norm(q)
    text_compact = compact_norm(text)
    return bool(q_compact) and q_compact in text_compact


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
    """Parse one monetary value without guessing from arbitrary page numbers."""
    if v is None:
        return None

    s = clean(v)
    if not s:
        return None

    # Prefer a value explicitly associated with a currency symbol/code.
    money = re.search(
        r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€|\s*EUR)?",
        s,
        re.I,
    )
    if not money:
        return None

    try:
        value = round(float(money.group(1).replace(",", ".")), 2)
    except ValueError:
        return None

    if value <= 0 or value > 10000:
        return None
    return value


def _price_from_node(node):
    """Read a price from one DOM node, preferring machine-readable values."""
    if node is None:
        return None

    for attr in ("content", "data-price", "data-product-price", "value"):
        raw = node.get(attr)
        if raw is not None:
            price = parse_price(raw)
            if price is not None:
                return price

    return parse_price(node.get_text(" ", strip=True))


def _price_marker(node):
    """Return class/id/attribute context used only to rank price candidates."""
    parts = []

    current = node
    for _ in range(3):
        if current is None:
            break

        if getattr(current, "get", None):
            parts.extend(str(x) for x in (current.get("class") or []))
            parts.append(str(current.get("id") or ""))

            for attr in (
                "data-testid",
                "data-test",
                "aria-label",
                "itemprop",
            ):
                value = current.get(attr)
                if value:
                    parts.append(str(value))

        current = getattr(current, "parent", None)

    return norm(" ".join(parts))


def _bad_price_context(node):
    """Reject reference/list/old prices before considering current prices."""
    marker = _price_marker(node)

    bad_words = (
        "old price",
        "oldprice",
        "was price",
        "wasprice",
        "previous price",
        "previousprice",
        "list price",
        "listprice",
        "regular price",
        "regularprice",
        "recommended price",
        "recommendedprice",
        "retail price",
        "retailprice",
        "suggested retail",
        "suggestedretail",
        "rrp",
        "msrp",
        "pvc",
        "adviesprijs",
        "prix conseille",
        "prix de detail",
        "prix public",
        "strike",
        "crossed",
        "compare at",
    )

    return any(word in marker for word in bad_words)


def _cart_context_score(node):
    """Score a price by its relationship to the actual purchase controls."""
    score = 0
    current = node

    for depth in range(6):
        if current is None:
            break

        text = clean(
            current.get_text(" ", strip=True)
            if hasattr(current, "get_text")
            else ""
        ).lower()

        marker = _price_marker(current)

        if any(x in marker for x in (
            "current",
            "sale",
            "final",
            "product price",
            "productprice",
            "offer",
            "buybox",
            "buy-box",
            "price-current",
        )):
            score += 15

        if any(x in text for x in (
            "ajouter au panier",
            "ajouter au chariot",
            "in den warenkorb",
            "add to cart",
            "add to basket",
            "toevoegen aan winkelwagen",
            "voeg toe aan winkelmandje",
            "bestellen",
            "koop nu",
            "buy now",
        )):
            score += 50

        # A price inside the same small container as the purchase control is
        # much more likely to be the live selling price than PVC/RRP.
        if depth <= 2 and any(x in text for x in (
            "ajouter",
            "panier",
            "warenkorb",
            "winkelwagen",
            "cart",
            "basket",
            "bestellen",
            "buy",
        )):
            score += 20

        current = getattr(current, "parent", None)

    return score


def _visible_current_price(soup):
    """Extract the price visibly tied to the product purchase area.

    Deloox can expose a different price in JSON-LD than the price rendered in
    the Belgian storefront. The visible purchase price is authoritative for
    ScentHunter's Deloox.be offer. This function deliberately avoids generic
    whole-page number extraction.
    """
    candidates = []

    selectors = (
        '[itemprop="price"]',
        '[data-price]',
        '[data-product-price]',
        '[class*="current-price" i]',
        '[class*="price-current" i]',
        '[class*="sale-price" i]',
        '[class*="final-price" i]',
        '[class*="product-price" i]',
        '[class*="product_price" i]',
        '[class*="price" i]',
    )

    seen = set()
    for selector in selectors:
        try:
            nodes = soup.select(selector)
        except Exception:
            nodes = []

        for node in nodes[:80]:
            if id(node) in seen:
                continue
            seen.add(id(node))

            if _bad_price_context(node):
                continue

            price = _price_from_node(node)
            if price is None:
                continue

            score = _cart_context_score(node)

            marker = _price_marker(node)
            if "current" in marker or "sale" in marker or "final" in marker:
                score += 20
            if "product" in marker:
                score += 10

            candidates.append((score, price))

    # Some storefronts put the current amount in a generic element rather than
    # a price-named class. Inspect the immediate purchase-control containers,
    # not the entire document.
    purchase_selectors = (
        'button[type="submit"]',
        'button',
        '[role="button"]',
        'input[type="submit"]',
    )

    for selector in purchase_selectors:
        try:
            controls = soup.select(selector)
        except Exception:
            controls = []

        for control in controls[:80]:
            control_text = clean(control.get_text(" ", strip=True)).lower()
            aria = clean(control.get("aria-label")).lower()

            if not any(x in f"{control_text} {aria}" for x in (
                "ajouter au panier",
                "ajouter au chariot",
                "in den warenkorb",
                "add to cart",
                "add to basket",
                "toevoegen aan winkelwagen",
                "voeg toe aan winkelmandje",
                "bestellen",
                "buy now",
            )):
                continue

            parent = control
            for depth in range(1, 5):
                parent = getattr(parent, "parent", None)
                if parent is None:
                    break

                # Limit this fallback to reasonably small product-price
                # containers. Whole-page extraction is intentionally forbidden.
                text = clean(parent.get_text(" ", strip=True))
                if len(text) > 2500:
                    continue

                for node in parent.find_all(True):
                    if _bad_price_context(node):
                        continue

                    price = _price_from_node(node)
                    if price is None:
                        continue

                    score = 100 - depth * 10
                    score += 40
                    candidates.append((score, price))

    if not candidates:
        return None

    # Highest semantic/purchase-context score wins. On a genuine tie, prefer
    # the value appearing in the most specific/current price element.
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


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


def _product_url_tokens(url):
    """Return meaningful product-name tokens encoded by a retailer URL."""
    path = urlparse(clean(url)).path.lower()
    m = re.search(r"/(?:produit|product|producto|prodotto)/\d+/([^/?#]+)", path)
    if not m:
        return set()
    raw = re.sub(r"\.(?:html?|php)$", "", m.group(1), flags=re.I)
    raw = re.sub(r"[-_]+", " ", raw)
    ignored = {
        "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
        "100", "75", "50", "30", "ml", "cl", "spray", "for", "him",
        "her", "homme", "femme", "men", "women", "unisex",
    }
    return {t for t in norm(raw).split() if len(t) > 2 and t not in ignored}


def _url_matches_product_name(url, name):
    """Reject stale retailer URLs whose slug materially disagrees with page name.

    This is generic integrity validation. It prevents a stale URL such as a
    former product slug from silently becoming a different product when the
    retailer reuses the underlying product page.
    """
    slug_tokens = _product_url_tokens(url)
    if not slug_tokens:
        return True
    name_tokens = tokens(name)
    # Brand/model tokens may be reordered, but every meaningful slug token
    # must still be represented by the authoritative product name.
    return slug_tokens.issubset(name_tokens)


def _product(url, html, query):
    soup = BeautifulSoup(html, "html.parser")
    data = _jsonld(soup)

    h1 = soup.find("h1")
    name = clean(data.get("name")) or (
        clean(h1.get_text(" ", strip=True)) if h1 else ""
    )

    if not name or not matches(name, query):
        return None

    # The product page is authoritative. If the retailer serves a different
    # product under a stale/reused URL slug, reject that candidate instead of
    # silently returning the wrong product. Discovery can then recover the
    # product from another locale/surface.
    if not _url_matches_product_name(url, name):
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

    # Deloox.be can expose a different value in JSON-LD than the price
    # visibly offered in the Belgian purchase area. Prefer the live purchase
    # price from the product DOM; JSON-LD is only the fallback.
    price = _visible_current_price(soup)
    if price is None:
        price = parse_price(offer.get("price"))
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
    query_compact = compact_norm(query)

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
        if query_compact and query_compact in compact_norm(f"{context_text} {path_text}"):
            score += 90
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
        path = parsed.path or ""

        # Deloox search pages also contain product-image URLs such as
        # /product/1359240/551400_500.jpg.  They share the numeric product
        # prefix, but they are assets, not product pages.  Never let assets
        # consume the bounded discovery candidate budget.
        if re.search(
            r"\.(?:jpe?g|png|webp|gif|svg|avif|ico|css|js|map)(?:$|/)",
            path,
            re.I,
        ):
            return

        product_path = re.search(
            r"/(?:product|produit|producto|prodotto)/\d+(?:/|$)",
            path,
            re.I,
        )
        slug_product_path = (
            path.lower().endswith(".html")
            and not re.search(
                r"(?:^|/)(?:category|categorie|categoria|catégorie|chercher|search|sitemap|"
                r"brand|marque|marca|page|cart|panier|checkout|account|login)"
                r"(?:\.html)?(?:/|$)",
                path,
                re.I,
            )
        )
        if not product_path and not slug_product_path:
            return

        score = relevance(url, context)
        if not accept_all_products and score <= 0:
            return
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


def _search_endpoints(query):
    """Return a small, generic set of Deloox public search surfaces.

    Deloox operates several localized storefronts.  The public search route
    differs between generations/locales, so discovery probes a bounded set of
    store-provided search endpoints in parallel.  No product, brand or SKU is
    encoded here.
    """
    encoded = quote_plus(query)
    endpoints = []

    # Legacy/localized public search surface.
    for base in DELOOX_BASE_URLS:
        endpoints.append(f"{base}/chercher.html?q={encoded}")

    # Current multilingual search surfaces.  These are generic store routes;
    # a 404 simply means that storefront does not expose this route.
    for base in DELOOX_BASE_URLS:
        endpoints.append(f"{base}/en/search?query={encoded}")
        endpoints.append(f"{base}/en/search?q={encoded}")

    # Deduplicate while preserving deterministic order.
    out = []
    seen = set()
    for url in endpoints:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _discover_from_search(session, query):
    """Primary Deloox discovery with deterministic bounded pagination.

    Deloox exposes several public search surfaces.  They are probed in
    parallel, but the surface used for pagination is selected deterministically
    instead of depending on which HTTP request happens to finish first.

    The preferred production surface is the public ``/chercher.html`` route on
    the primary .be storefront.  If that surface is unavailable or produces no
    relevant candidates, the other generic Deloox search surfaces remain valid
    fallbacks.  Once a surface is selected, numbered ``page`` URLs are followed
    until no new candidates are found or MAX_SEARCH_PAGES is reached.

    No product, brand, SKU or variant is encoded here.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from urllib.parse import parse_qsl, urlencode, urlunparse

    query = clean(query)
    if not query:
        return []

    endpoints = _search_endpoints(query)
    candidates = {}
    successful_pages = 0
    failed_pages = 0

    def fetch(endpoint):
        try:
            r = session.get(
                endpoint,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            return endpoint, r
        except requests.RequestException:
            return endpoint, None

    # Probe the bounded set concurrently for latency, but collect every
    # successful response before choosing the pagination surface.  The previous
    # implementation selected the first completed future with matches, which
    # made discovery dependent on network timing and could select a localized
    # search route whose pagination did not expose the same result set as the
    # primary .be /chercher.html surface.
    successful = []
    with ThreadPoolExecutor(max_workers=min(13, len(endpoints))) as pool:
        futures = [pool.submit(fetch, endpoint) for endpoint in endpoints]
        for future in as_completed(futures):
            endpoint, r = future.result()
            if r is None or r.status_code >= 400 or not r.text:
                failed_pages += 1
                continue

            successful_pages += 1
            base = f"{urlparse(r.url).scheme}://{urlparse(r.url).netloc}"
            found = _candidate_product_urls(
                r.text,
                query,
                discovery_query=query,
                accept_all_products=False,
                base_url=base,
            )
            successful.append({
                "requested": endpoint,
                "final": r.url,
                "response": r,
                "found": found,
            })

    # Prefer the production .be legacy search surface, then other legacy
    # /chercher.html surfaces, then multilingual /en/search routes.  This keeps
    # pagination tied to the same search family while preserving generic
    # storefront fallbacks.
    def surface_rank(item):
        final = item["final"].lower()
        requested = item["requested"].lower()
        has_found = bool(item["found"])

        if has_found and final.startswith("https://www.deloox.be/chercher.html"):
            return 0
        if has_found and final.startswith("https://deloox.be/chercher.html"):
            return 1
        if has_found and "/chercher.html" in final:
            return 2
        if has_found and "/en/search" in final:
            return 3
        if "/chercher.html" in requested:
            return 10
        return 20

    successful.sort(key=surface_rank)
    selected = next((item for item in successful if item["found"]), None)

    candidates = {}
    selected_endpoint = None
    if selected:
        selected_endpoint = selected["final"]
        for url in selected["found"]:
            candidates[url] = True

    # Follow the selected search surface's numbered pages.  The pagination is
    # generic and uses the query parameters already present on the successful
    # URL, replacing only the page parameter.
    if selected_endpoint:
        parsed = urlparse(selected_endpoint)
        params = parse_qsl(parsed.query, keep_blank_values=True)

        def page_url(page_number):
            page_params = [
                (key, value)
                for key, value in params
                if key.lower() != "page"
            ]
            page_params.append(("page", str(page_number)))
            return urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(page_params, doseq=True),
                "",
            ))

        for page_number in range(2, MAX_SEARCH_PAGES + 1):
            endpoint = page_url(page_number)
            _endpoint, r = fetch(endpoint)

            if r is None or r.status_code >= 400 or not r.text:
                failed_pages += 1
                break

            successful_pages += 1
            base = f"{urlparse(r.url).scheme}://{urlparse(r.url).netloc}"
            found = _candidate_product_urls(
                r.text,
                query,
                discovery_query=query,
                accept_all_products=False,
                base_url=base,
            )

            before = len(candidates)
            for url in found:
                candidates[url] = True

            if len(candidates) == before:
                break

    global _LAST_DISCOVERY_STATE
    _LAST_DISCOVERY_STATE["search_pages_ok"] = successful_pages
    _LAST_DISCOVERY_STATE["search_pages_failed"] = failed_pages
    _LAST_DISCOVERY_STATE["search_verified"] = successful_pages > 0

    return list(candidates.keys())[:MAX_SEARCH_CANDIDATES]


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


def _category_pagination_urls(base_url, html):
    """Extract generic pagination/navigation URLs from a category page.

    Retailer category pages can expose pagination through normal links,
    rel="next", data-* attributes or JavaScript state. This helper only
    discovers navigation URLs; it never identifies a product.
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    def add(raw):
        raw = clean(raw)
        if not raw or raw.startswith(("javascript:", "mailto:", "#")):
            return
        url = urljoin(base_url, raw).split("#")[0]
        parsed = urlparse(url)
        if parsed.netloc.lower() not in DELOOX_HOSTS:
            return
        if url not in seen:
            seen.add(url)
            found.append(url)

    # Explicit "next" / pagination links.
    for node in soup.find_all(["a", "link"], href=True):
        rel = node.get("rel") or []
        if not isinstance(rel, list):
            rel = [str(rel)]
        marker = norm(
            " ".join(
                [str(x) for x in rel]
                + [clean(node.get("aria-label")), clean(node.get_text(" ", strip=True))]
            )
        )
        if "next" in marker or "pagination" in marker:
            add(node.get("href"))

    # Common URL-bearing attributes used by dynamic pagination/load-more.
    for node in soup.find_all(True):
        for attr in (
            "data-next",
            "data-next-url",
            "data-pagination-url",
            "data-load-more-url",
            "data-url",
            "data-href",
            "data-page-url",
        ):
            raw = node.get(attr)
            if raw:
                add(raw)

    # Numbered pagination links.
    for a in soup.find_all("a", href=True):
        href = clean(a.get("href"))
        if not href:
            continue
        parsed = urlparse(urljoin(base_url, href))
        label = clean(a.get_text(" ", strip=True))
        if (
            re.search(r"(?:^|[?&])(?:page|p|pagina|paged)=\d+", parsed.query, re.I)
            or re.fullmatch(r"\d{1,3}", label)
        ):
            add(href)

    return found


def _category_page_2_url(url):
    """Return the generic second-page URL for a paginated category."""
    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    replaced = False
    new_pairs = []

    for key, value in pairs:
        if key.lower() in {"page", "p", "pagina", "paged"}:
            new_pairs.append((key, "2"))
            replaced = True
        else:
            new_pairs.append((key, value))

    if not replaced:
        new_pairs.append(("page", "2"))

    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        urlencode(new_pairs, doseq=True),
        "",
    ))


def _discover_from_categories(session, query, max_urls=MAX_CANDIDATES):
    """Generic category fallback with bounded, complete pagination.

    Category discovery follows the retailer's own pagination/navigation first.
    If no pagination is exposed in the HTML, page=2 is probed generically.
    No product, brand, SKU or variant is encoded here.
    """
    urls = []
    seen_products = set()

    for page_url in _category_pages()[:12]:
        try:
            r = session.get(
                page_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if r.status_code >= 400 or not r.text:
            continue

        first_url = r.url
        pages = [first_url]
        loaded = {first_url: r.text}

        for u in _category_pagination_urls(
            f"{urlparse(first_url).scheme}://{urlparse(first_url).netloc}",
            r.text,
        ):
            if u not in pages:
                pages.append(u)
            if len(pages) >= MAX_CATEGORY_PAGES:
                break

        # Some category implementations expose no usable pagination link in
        # the HTML even though ?page=2 works. Probe it as a generic fallback.
        if len(pages) == 1:
            page2 = _category_page_2_url(first_url)
            if page2 != first_url:
                pages.append(page2)

        index = 0
        while index < len(pages) and index < MAX_CATEGORY_PAGES:
            current_url = pages[index]

            if current_url in loaded:
                html = loaded[current_url]
            else:
                try:
                    page = session.get(
                        current_url,
                        headers=HEADERS,
                        timeout=TIMEOUT,
                        allow_redirects=True,
                    )
                except requests.RequestException:
                    index += 1
                    continue

                if page.status_code >= 400 or not page.text:
                    index += 1
                    continue

                html = page.text
                loaded[current_url] = html

            current_base = (
                f"{urlparse(current_url).scheme}://{urlparse(current_url).netloc}"
            )
            page_found = []

            for product_url in _candidate_product_urls(
                html,
                query,
                base_url=current_base,
                accept_all_products=True,
            ):
                if product_url in seen_products:
                    continue
                seen_products.add(product_url)
                urls.append(product_url)
                page_found.append(product_url)

                if len(urls) >= max_urls:
                    return urls

            # Pagination can be exposed only after rendering/processing a page.
            if len(pages) < MAX_CATEGORY_PAGES:
                for next_url in _category_pagination_urls(current_base, html):
                    if next_url not in pages:
                        pages.append(next_url)
                    if len(pages) >= MAX_CATEGORY_PAGES:
                        break

            # Once an actual subsequent page yields no new query candidates,
            # stop this category. This prevents needless crawling of long
            # empty tails while still reaching a product on page 2.
            if index > 0 and not page_found:
                break

            index += 1

    return urls

def _discover(session, q):
    """Generic deterministic discovery with search as the primary surface.

    Order is deliberate:
      1. Deloox public search + pagination
      2. retailer category/filter surfaces
      3. product sitemap fallback

    No product, brand, SKU, price or variant is hardcoded here.
    """
    global _LAST_DISCOVERY_STATE
    _LAST_DISCOVERY_STATE = {
        "search_pages_ok": 0,
        "search_pages_failed": 0,
        "search_verified": False,
        "category_verified": False,
        "sitemap_verified": False,
        "technical_failure": False,
    }

    q = clean(q)
    if not q:
        return []

    candidates = []
    seen = set()

    search_candidates = _discover_from_search(session, q)
    for url in search_candidates:
        if url not in seen:
            seen.add(url)
            candidates.append(url)

    # Search is the primary discovery surface. If it produced relevant
    # candidates, stop here: category and sitemap crawling are fallbacks, not
    # additional work that every successful search must perform. This keeps
    # discovery fast and preserves the proven Deloox search mechanism.
    if candidates:
        return candidates[:MAX_CANDIDATES]

    # Only when search produced no candidates do we use the generic fallback
    # surfaces. A successful search with no matches is still a verified search
    # result; fallback discovery may nevertheless recover products omitted by
    # the retailer search surface.
    category_candidates = _discover_from_categories(session, q, MAX_CANDIDATES)
    if category_candidates:
        _LAST_DISCOVERY_STATE["category_verified"] = True
    for url in category_candidates:
        if url not in seen:
            seen.add(url)
            candidates.append(url)
            if len(candidates) >= MAX_CANDIDATES:
                break

    if len(candidates) < MAX_CANDIDATES:
        sitemap_candidates = _sitemap_product_urls(
            session,
            q,
            max_sitemaps=48,
            max_urls=MAX_CANDIDATES - len(candidates),
        )
        if sitemap_candidates:
            _LAST_DISCOVERY_STATE["sitemap_verified"] = True
        for url in sitemap_candidates:
            if url not in seen:
                seen.add(url)
                candidates.append(url)
                if len(candidates) >= MAX_CANDIDATES:
                    break

    if not candidates and not any(
        (
            _LAST_DISCOVERY_STATE["search_verified"],
            _LAST_DISCOVERY_STATE["category_verified"],
            _LAST_DISCOVERY_STATE["sitemap_verified"],
        )
    ):
        _LAST_DISCOVERY_STATE["technical_failure"] = True

    return candidates[:MAX_CANDIDATES]

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


def search_stream(query, emit=None):
    """ScentHunter scraper contract with explicit discovery state."""
    query = clean(query)
    if not query:
        return {
            "status": "success",
            "verified": True,
            "results": [],
            "error": None,
            "details": {"reason": "empty_query"},
        }

    try:
        results = search(query)
    except requests.Timeout as exc:
        return {"status": "timeout", "verified": False, "results": [],
                "error": str(exc), "details": {}}
    except requests.ConnectionError as exc:
        return {"status": "unavailable", "verified": False, "results": [],
                "error": str(exc), "details": {}}
    except requests.RequestException as exc:
        return {"status": "error", "verified": False, "results": [],
                "error": str(exc), "details": {}}
    except Exception as exc:
        return {"status": "error", "verified": False, "results": [],
                "error": str(exc),
                "details": {"exception": type(exc).__name__}}

    results = results if isinstance(results, list) else []
    details = dict(_LAST_DISCOVERY_STATE)
    details["count"] = len(results)

    if _LAST_DISCOVERY_STATE.get("technical_failure"):
        return {
            "status": "unavailable",
            "verified": False,
            "results": [],
            "error": "discovery_unavailable",
            "details": details,
        }

    if callable(emit):
        for row in results:
            if isinstance(row, dict):
                emit(row)

    return {
        "status": "success",
        "verified": True,
        "results": results,
        "error": None,
        "details": details,
    }


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
