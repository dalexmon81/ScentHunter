"""Deloox adapter for ScentHunter.

Discovery is deliberately independent from Deloox's internal search.
Product URLs are discovered from:
1. dedicated Product Line/category pages;
2. Deloox search pages (when available);
3. product/category XML sitemaps;
4. generic fragrance categories.

Discovery only produces candidate product URLs. The product page is then
fetched and validated by _product().
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
TIMEOUT = 10
DISCOVERY_TIMEOUT = 5
DEBUG_DISCOVERY = os.getenv("DELOOX_DEBUG", "1") != "0"
MATCH_TRACE_LIMIT = int(os.getenv("DELOOX_MATCH_TRACE_LIMIT", "12"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
}

CATALOG_URL = BASE_URL + "/en/category/1025540/trending.html?page=60"
CATALOG_FILTER_LINKS = None

CATEGORY_ROOTS = (
    BASE_URL + "/category/1000003/fragrances.html",
    BASE_URL + "/category/1075639/womens-fragrances.html",
    BASE_URL + "/category/1075660/womens-perfume.html",
    BASE_URL + "/category/1000054/mens-fragrances.html",
    BASE_URL + "/category/1025540/trending.html",
)

SITEMAP_ROOTS = (
    BASE_URL + "/sitemap.xml",
    BASE_URL + "/sitemap_index.xml",
    BASE_URL + "/sitemap-index.xml",
    BASE_URL + "/en/sitemap.xml",
)


def _dbg(stage, **data):
    if not DEBUG_DISCOVERY:
        return
    print(
        "[DELOOX_DEBUG] "
        + json.dumps(
            {"stage": stage, **data},
            ensure_ascii=False,
            default=str,
        ),
        flush=True,
    )


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(v).lower())).strip()


def tokens(v):
    return {x for x in norm(v).split() if len(x) > 1}


def query_tokens(v):
    return tokens(v)


def _exact_token_match_score(text, q):
    wanted = tokens(q)
    actual = tokens(text)
    if not wanted or not actual:
        return 0
    return sum(token in actual for token in wanted)


def matches(text, q):
    wanted = tokens(q)
    return bool(wanted) and _exact_token_match_score(text, q) == len(wanted)


def size_ml(*values):
    m = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        " ".join(clean(x) for x in values),
        re.I,
    )
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    if m.group(2).lower() == "cl":
        n *= 10
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
    offers = data.get("offers") if isinstance(data, dict) else None
    if isinstance(offers, dict):
        offers = [offers]
    if isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            raw = (
                offer.get("availability")
                or offer.get("availabilityStatus")
                or offer.get("stock")
            )
            if not raw:
                continue
            t = norm(raw)
            if any(x in t for x in ("instock", "in stock", "available")):
                return "in_stock"
            if any(
                x in t
                for x in (
                    "outofstock", "out of stock", "soldout",
                    "sold out", "unavailable", "not available",
                )
            ):
                return "out_of_stock"

    for tag in soup.select(
        '[itemprop="availability"], '
        'meta[property="product:availability"], '
        'meta[name="availability"]'
    ):
        raw = tag.get("content") or tag.get_text(" ", strip=True)
        t = norm(raw)
        if any(x in t for x in ("instock", "in stock", "available")):
            return "in_stock"
        if any(
            x in t
            for x in (
                "outofstock", "out of stock", "soldout",
                "sold out", "unavailable", "not available",
            )
        ):
            return "out_of_stock"

    for node in soup.find_all(
        string=re.compile(
            r"\b(?:in stock|out of stock|sold out|not available|unavailable)\b",
            re.I,
        )
    ):
        t = norm(node)
        if any(x in t for x in ("out of stock", "sold out", "not available", "unavailable")):
            return "out_of_stock"
        if "in stock" in t:
            return "in_stock"
    return "unknown"


def _selected_size(soup, data, h1_name):
    m = re.search(r"(?<!\d)(\d{1,4})\s*ml\b", h1_name or "", re.I)
    if m:
        return int(m.group(1))

    for selector in (
        'input[type="radio"][checked]',
        'input[type="radio"][aria-checked="true"]',
        'input[checked][name*="size" i]',
        "option[selected]",
        '[aria-selected="true"]',
    ):
        for node in soup.select(selector):
            blob = " ".join(
                clean(x)
                for x in (
                    node.get("value"),
                    node.get("aria-label"),
                    node.get("data-value"),
                    node.get("data-size"),
                    node.get_text(" ", strip=True),
                    node.parent.get_text(" ", strip=True) if node.parent else "",
                    node.parent.parent.get_text(" ", strip=True)
                    if node.parent and node.parent.parent else "",
                )
            )
            m = re.search(r"(?<!\d)(\d{1,4})\s*ml\b", blob, re.I)
            if m:
                return int(m.group(1))

    structured_name = clean(data.get("name")) if isinstance(data, dict) else ""
    m = re.search(r"(?<!\d)(\d{1,4})\s*ml\b", structured_name, re.I)
    return int(m.group(1)) if m else None


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
            x_type = x.get("@type")
            if (
                x_type == "Product"
                or (isinstance(x_type, list) and "Product" in x_type)
                or "offers" in x
            ):
                return x
            if isinstance(x.get("@graph"), list):
                stack.extend(x["@graph"])
    return {}


def _product(url, html, query):
    soup = BeautifulSoup(html, "html.parser")
    data = _jsonld(soup)
    h1 = soup.find("h1")
    h1_name = clean(h1.get_text(" ", strip=True)) if h1 else ""
    name = h1_name or clean(data.get("name"))
    if not name:
        return None

    # Validation belongs here, after discovery.
    if not matches(name, query):
        return None

    text = soup.get_text(" ", strip=True)
    product_line = ""
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
    product_concentration = concentration(name)

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
                "value": product_concentration,
                "source": "product_name",
            } if product_concentration else None,
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


def _product_rejection_reason(url, html, query):
    soup = BeautifulSoup(html, "html.parser")
    data = _jsonld(soup)
    h1 = soup.find("h1")
    name = clean(h1.get_text(" ", strip=True)) if h1 else clean(data.get("name"))
    if not name:
        return "missing_product_name"
    if not matches(name, query):
        return f"name_mismatch: {name}"
    offers = data.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    offer = next((x for x in offers if isinstance(x, dict)), {})
    price = parse_price(offer.get("price"))
    if price is None:
        price = parse_price(soup.get_text(" ", strip=True))
    if price is None:
        return "missing_price"
    return None


def _is_product_url(url):
    try:
        return (
            isinstance(url, str)
            and urlparse(url).netloc.lower() in {"deloox.com", "www.deloox.com"}
            and "/product/" in urlparse(url).path.lower()
        )
    except Exception:
        return False


def _normalize_product_url(raw_url):
    if not raw_url:
        return None
    raw_url = clean(raw_url).replace("\\/", "/")
    if raw_url.startswith(("javascript:", "mailto:", "#")):
        return None
    url = urljoin(BASE_URL, raw_url).split("#")[0].split("?")[0]
    return url if _is_product_url(url) else None


def _product_url_slug_matches(url, query):
    """URL-only discovery signal. Never substitutes for final page validation."""
    return bool(tokens(query)) and tokens(query).issubset(tokens(urlparse(url).path))


def _product_url_context(blob, start, end):
    left = blob.rfind("{", 0, start)
    right = blob.find("}", end)
    if left >= 0 and right >= end and right - left <= 5000:
        obj = blob[left:right + 1]
        for pattern in (
            r'"(?:name|productName|product_name|title|productTitle)"\s*:\s*"([^"]{1,400})"',
            r"'(?:name|productName|product_name|title|productTitle)'\s*:\s*'([^']{1,400})'",
        ):
            m = re.search(pattern, obj, re.I)
            if m:
                return clean(m.group(1))
    return ""


def _product_card_context(anchor, query):
    node = anchor
    fallback = ""
    for _ in range(6):
        node = node.parent if node is not None else None
        if node is None:
            break
        context = clean(node.get_text(" ", strip=True))
        if not context or len(context) > 6000:
            continue
        attrs = " ".join(
            clean(x)
            for x in (
                node.get("class", ""),
                node.get("id", ""),
                node.get("data-product", ""),
                node.get("data-product-name", ""),
                node.get("data-testid", ""),
            )
            if clean(x)
        )
        if node.name in {"body", "html"}:
            break
        is_card = (
            any(x in attrs.lower() for x in ("product", "card", "item"))
            or node.name in {"article", "li"}
        )
        if is_card and matches(context, query):
            return context
        if is_card and not fallback:
            fallback = context
    return fallback


def _extract_product_urls(html, query=None, allow_opaque=False):
    """Discover candidates without requiring card text.

    A product URL is accepted when either:
    - its nearby card/structured context matches the query; OR
    - the URL slug itself contains all query tokens.

    `allow_opaque` remains available for diagnostics, but normal discovery
    keeps opaque numeric /product/ URLs out so the parser is not flooded.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    q_tokens = tokens(query or "")
    if not q_tokens:
        return []

    found, seen = [], set()
    stats = {
        "anchor_product_hrefs": 0,
        "duplicate_urls": 0,
        "rejected_non_deloox": 0,
        "rejected_not_product": 0,
        "rejected_query_mismatch": 0,
        "accepted_total": 0,
        "accepted_by_url_slug": 0,
        "accepted_by_context": 0,
    }
    trace_count = 0
    samples = []
    rejected = []

    def add(raw_url, context="", source="unknown"):
        nonlocal trace_count
        url = _normalize_product_url(raw_url)
        if not url:
            if raw_url and "/product/" in str(raw_url).lower():
                stats["rejected_non_deloox"] += 1
            return

        stats["anchor_product_hrefs"] += 1
        if len(samples) < 10:
            samples.append(url)
        if url in seen:
            stats["duplicate_urls"] += 1
            return

        context_match = matches(context, query)
        slug_match = _product_url_slug_matches(url, query)
        match_result = context_match or slug_match

        if trace_count < MATCH_TRACE_LIMIT:
            _dbg(
                "product_url_match_trace",
                query=query,
                query_tokens=sorted(q_tokens),
                source=source,
                url=url,
                context=clean(context)[:500],
                normalized_context=norm(context)[:500],
                normalized_url=norm(url),
                context_match=context_match,
                slug_match=slug_match,
                match_result=match_result,
                allow_opaque=allow_opaque,
            )
            trace_count += 1

        if not match_result and not allow_opaque:
            stats["rejected_query_mismatch"] += 1
            if len(rejected) < 10:
                rejected.append({
                    "source": source,
                    "url": url,
                    "context": clean(context)[:500],
                    "normalized_url": norm(url),
                })
            return

        seen.add(url)
        found.append(url)
        stats["accepted_total"] += 1
        if slug_match:
            stats["accepted_by_url_slug"] += 1
        else:
            stats["accepted_by_context"] += 1

    for a in soup.find_all("a", href=True):
        href = clean(a.get("href", ""))
        if "/product/" not in href.lower():
            continue
        context = " ".join(
            clean(x)
            for x in (
                a.get_text(" ", strip=True),
                a.get("aria-label", ""),
                a.get("title", ""),
                a.get("data-name", ""),
                a.get("data-product-name", ""),
            )
            if clean(x)
        )
        if not matches(context, query):
            card = _product_card_context(a, query)
            if card:
                context = card
        add(href, context, "anchor")

    raw = (html or "").replace("\\\\/", "/").replace("\\/", "/")
    patterns = (
        r'https?://(?:www\.)?deloox\.com[^"\'<> \t\r\n]*/product/[^"\'<> \t\r\n]+',
        r'(?<![A-Za-z0-9])(?:/|(?:en|it|nl)/)product/[^"\'<> \t\r\n]+',
    )

    for tag in soup.find_all(["script", "div", "article", "li"]):
        blob = tag.get_text() if tag.name == "script" else tag.get_text(" ", strip=True)
        if "/product/" not in blob.lower():
            continue
        for pattern in patterns:
            for m in re.finditer(pattern, blob, re.I):
                add(
                    m.group(0),
                    _product_url_context(blob, m.start(), m.end()),
                    tag.name,
                )

    for pattern in patterns:
        for m in re.finditer(pattern, raw, re.I):
            add(
                m.group(0),
                _product_url_context(raw, m.start(), m.end()),
                "raw_html",
            )

    _dbg(
        "product_url_extraction_debug",
        html_bytes=len(html or ""),
        query=query,
        query_tokens=sorted(q_tokens),
        **stats,
        final_product_urls=len(found[:80]),
        sample_raw_product_urls=samples,
        sample_rejected_query=rejected,
    )
    return found[:80]


def _product_urls_by_slug(html, query):
    """Independent URL-only discovery used by category/search/sitemap pages."""
    q_tokens = tokens(query)
    if not q_tokens:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    found, seen = [], set()

    def add(raw_url):
        url = _normalize_product_url(raw_url)
        if not url or url in seen:
            return
        if not _product_url_slug_matches(url, query):
            return
        seen.add(url)
        found.append(url)

    for a in soup.find_all("a", href=True):
        if "/product/" in clean(a.get("href", "")).lower():
            add(a.get("href"))

    raw = (html or "").replace("\\\\/", "/").replace("\\/", "/")
    patterns = (
        r'https?://(?:www\.)?deloox\.com[^"\'<> \t\r\n]*/product/[^"\'<> \t\r\n]+',
        r'(?<![A-Za-z0-9])(?:/|(?:en|it|nl)/)product/[^"\'<> \t\r\n]+',
    )
    for pattern in patterns:
        for m in re.finditer(pattern, raw, re.I):
            add(m.group(0))
    return found[:80]


def _absolute_category_url(raw_url):
    if not raw_url:
        return None
    url = urljoin(BASE_URL, clean(raw_url).replace("\\/", "/")).split("#")[0].split("?")[0]
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
        return None
    if "/category/" not in parsed.path.lower() or not parsed.path.lower().endswith(".html"):
        return None
    return url


def _category_slug(url):
    slug = urlparse(url).path.rsplit("/", 1)[-1]
    return slug[:-5] if slug.lower().endswith(".html") else slug


def _category_score(url, label, query):
    wanted = tokens(query)
    if not wanted:
        return 0
    slug = tokens(_category_slug(url))
    label_tokens = tokens(label)
    if norm(query) == norm(label):
        return 300
    if norm(query) == norm(_category_slug(url)):
        return 290
    label_matches = len(wanted & label_tokens)
    slug_matches = len(wanted & slug)
    best = max(label_matches, slug_matches)
    if best == len(wanted):
        return 200 + best * 10
    return best * 10


def _extract_category_links(html):
    soup = BeautifulSoup(html or "", "html.parser")
    found, seen = [], set()
    for a in soup.find_all("a", href=True):
        url = _absolute_category_url(a.get("href"))
        if not url or url in seen:
            continue
        seen.add(url)
        found.append((url, clean(a.get_text(" ", strip=True))))
    return found


_CATEGORY_RE = re.compile(
    r'https?://(?:www\.)?deloox\.com(?:/(?:en|it|nl))?/category/\d+/[^"\'<> \t\r\n]+\.html'
    r'|(?<![A-Za-z0-9])/(?:en|it|nl)/category/\d+/[^"\'<> \t\r\n]+\.html'
    r'|(?<![A-Za-z0-9])/category/\d+/[^"\'<> \t\r\n]+\.html',
    re.I,
)


def _extract_category_links_from_html(html, query, source_url=""):
    raw = (html or "").replace("\\\\/", "/").replace("\\/", "/")
    candidates = {}

    def add(raw_url, label=""):
        url = _absolute_category_url(raw_url)
        if not url:
            return
        score = _category_score(url, label, query)
        if score <= 0:
            return
        old = candidates.get(url)
        if old is None or score > old["score"]:
            candidates[url] = {
                "url": url,
                "label": clean(label),
                "score": score,
            }

    soup = BeautifulSoup(raw, "html.parser")
    for a in soup.find_all("a", href=True):
        href = clean(a.get("href", ""))
        if "/category/" not in href.lower():
            continue
        label = " ".join(
            clean(x)
            for x in (
                a.get_text(" ", strip=True),
                a.get("aria-label", ""),
                a.get("title", ""),
                a.get("data-name", ""),
                a.get("data-category-name", ""),
            )
            if clean(x)
        )
        add(href, label)

    for m in _CATEGORY_RE.finditer(raw):
        local = raw[max(0, m.start() - 2500):min(len(raw), m.end() + 2500)]
        label = ""
        for pattern in (
            r'"(?:name|categoryName|category_name|title|label)"\s*:\s*"([^"]{1,300})"',
            r"'(?:name|categoryName|category_name|title|label)'\s*:\s*'([^']{1,300})'",
        ):
            nm = re.search(pattern, local, re.I)
            if nm:
                label = clean(nm.group(1))
                break
        add(m.group(0), label)

    result = sorted(candidates.values(), key=lambda x: (-x["score"], len(x["url"])))
    _dbg(
        "category_link_extraction",
        query=query,
        source=source_url,
        count=len(result),
        matches=result[:20],
    )
    return result


def _catalog_filter_links(session):
    global CATALOG_FILTER_LINKS
    if CATALOG_FILTER_LINKS is not None:
        return CATALOG_FILTER_LINKS

    found, seen = [], set()
    pages = (
        CATALOG_URL,
        BASE_URL + "/en/category/1025540/trending.html?page=1",
        BASE_URL + "/en/category/1025540/trending.html",
    )

    for page_url in pages:
        try:
            r = session.get(page_url, headers=HEADERS, timeout=DISCOVERY_TIMEOUT)
        except requests.RequestException as exc:
            _dbg("catalog_fetch_error", url=page_url, error=f"{type(exc).__name__}: {exc}")
            continue
        _dbg("catalog_fetch", url=page_url, status=r.status_code, bytes=len(r.text or ""))
        if r.status_code >= 400:
            continue
        for url, label in _extract_category_links(r.text):
            if url in seen:
                continue
            seen.add(url)
            found.append((label, url))

    CATALOG_FILTER_LINKS = found
    _dbg("catalog_links_discovered", count=len(found), sample=found[:30])
    return found


def _sitemap_category_urls(session, query, max_sitemaps=32, max_urls=100):
    wanted = tokens(query)
    if not wanted:
        return []

    pending = deque(SITEMAP_ROOTS)
    seen_sitemaps, found, seen_urls = set(), [], set()

    while pending and len(seen_sitemaps) < max_sitemaps and len(found) < max_urls:
        sitemap_url = pending.popleft()
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
                if value not in seen_sitemaps:
                    pending.append(value)
                continue
            parsed = urlparse(value)
            if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
                continue
            path = parsed.path.lower()
            if "/category/" not in path or not path.endswith(".html"):
                continue
            if not wanted.issubset(tokens(_category_slug(value))):
                continue
            value = value.split("#")[0].split("?")[0]
            if value not in seen_urls:
                seen_urls.add(value)
                found.append(value)
                if len(found) >= max_urls:
                    break

    _dbg("sitemap_category_discovery_done", query=query, count=len(found), urls=found[:20])
    return found


def _sitemap_product_urls(session, query, max_sitemaps=64, max_urls=80):
    """Strong product-sitemap source.

    Sitemap traversal is prioritized toward product-looking sitemap files.
    We do not require page/card text. The product URL slug is the discovery
    signal; _product() remains the final validator.
    """
    wanted = tokens(query)
    if not wanted:
        return []

    pending = deque(SITEMAP_ROOTS)
    seen_sitemaps, product_urls, seen_products = set(), [], set()

    while pending and len(seen_sitemaps) < max_sitemaps and len(product_urls) < max_urls:
        sitemap_url = pending.popleft()
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        try:
            r = session.get(sitemap_url, headers=HEADERS, timeout=DISCOVERY_TIMEOUT)
        except requests.RequestException as exc:
            _dbg("product_sitemap_fetch_error", url=sitemap_url, error=f"{type(exc).__name__}: {exc}")
            continue

        _dbg("product_sitemap_fetch", url=sitemap_url, status=r.status_code, bytes=len(r.text or ""))
        if r.status_code >= 400:
            continue

        body = (r.text or "").lstrip()
        if not body.startswith(("<?xml", "<urlset", "<sitemapindex")):
            continue

        soup = BeautifulSoup(r.text, "xml")
        child_sitemaps = []
        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())
            if not value:
                continue
            low = value.lower()
            if "/product/" in low:
                url = _normalize_product_url(value)
                if url and _product_url_slug_matches(url, query) and url not in seen_products:
                    seen_products.add(url)
                    product_urls.append(url)
                    if len(product_urls) >= max_urls:
                        break
                continue
            if low.endswith(".xml") or "sitemap" in low:
                if value not in seen_sitemaps:
                    child_sitemaps.append(value)

        # Product-specific sitemap files are visited before generic/category files.
        child_sitemaps.sort(
            key=lambda x: (
                0 if any(k in x.lower() for k in ("product", "products", "perfume", "fragrance")) else 1,
                x.lower(),
            )
        )
        pending.extendleft(reversed(child_sitemaps))

    _dbg(
        "product_sitemap_discovery_done",
        query=query,
        sitemap_count=len(seen_sitemaps),
        count=len(product_urls),
        urls=product_urls[:20],
    )
    return product_urls[:max_urls]


def _find_catalog_filter_url(session, query):
    wanted = tokens(query)
    if not wanted:
        return None
    candidates = []

    for page_url in (
        CATALOG_URL,
        BASE_URL + "/en/category/1025540/trending.html?page=1",
        BASE_URL + "/en/category/1025540/trending.html",
    ):
        try:
            r = session.get(page_url, headers=HEADERS, timeout=DISCOVERY_TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue
        for item in _extract_category_links_from_html(r.text, query, page_url):
            candidates.append((item["score"] + 1000, item["url"], item["label"], "live_catalogue"))

    for url in _sitemap_category_urls(session, query):
        candidates.append((_category_score(url, "", query) + 400, url, "", "sitemap"))

    for label, url in _catalog_filter_links(session):
        score = _category_score(url, label, query)
        if score > 0:
            candidates.append((score + 200, url, label, "catalog_links"))

    if not candidates:
        _dbg("catalog_match", query=query, url=None, reason="no_matching_category_discovered")
        return None

    best = max(candidates, key=lambda x: (x[0], -len(x[1])))
    if best[0] < 1200:
        _dbg("catalog_match_rejected", query=query, reason="weak_category_match", best_score=best[0])
        return None

    _dbg("catalog_match", query=query, url=best[1], label=best[2], source=best[3], score=best[0])
    return best[1]


def _discover_from_categories(session, query, max_urls=120):
    urls, seen = [], set()
    for root in CATEGORY_ROOTS:
        try:
            r = session.get(root, headers=HEADERS, timeout=DISCOVERY_TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue

        candidates = _extract_product_urls(r.text, query)
        for url in candidates:
            if url not in seen:
                seen.add(url)
                urls.append(url)
                if len(urls) >= max_urls:
                    return urls

        # URL-only discovery is intentionally separate from card extraction.
        for url in _product_urls_by_slug(r.text, query):
            if url not in seen:
                seen.add(url)
                urls.append(url)
                if len(urls) >= max_urls:
                    return urls
    return urls


def _discover(session, q):
    """Generic discovery.

    The order is:
      dedicated Product Line/category
      -> product sitemap
      -> search pages
      -> category sitemap/category pages
      -> broad categories

    Search is therefore optional rather than the gatekeeper.
    """
    urls, seen = [], set()

    def add_many(items, source):
        items = list(items or [])
        _dbg("discovery_candidates", query=q, source=source, count=len(items), sample=items[:20])
        for url in items:
            if not _is_product_url(url):
                continue
            if url not in seen:
                seen.add(url)
                urls.append(url)
                if len(urls) >= 80:
                    return True
        return False

    # 1. Dedicated Product Line/category.
    dedicated = _find_catalog_filter_url(session, q)
    if dedicated:
        try:
            page = session.get(dedicated, headers=HEADERS, timeout=DISCOVERY_TIMEOUT)
        except requests.RequestException as exc:
            page = None
            _dbg("dedicated_category_fetch_error", query=q, url=dedicated, error=f"{type(exc).__name__}: {exc}")
        if page is not None and page.status_code < 400:
            _dbg("dedicated_category_fetch", query=q, url=dedicated, status=page.status_code, bytes=len(page.text or ""))
            candidates = _extract_product_urls(page.text, q)
            # IMPORTANT: merge URL-only discovery even when context candidates exist.
            candidates += [u for u in _product_urls_by_slug(page.text, q) if u not in candidates]
            _dbg("dedicated_category_candidates", query=q, url=dedicated, count=len(candidates), sample=candidates[:20])
            if add_many(candidates, "dedicated_category"):
                return urls[:80]

    # 2. Product sitemap is a primary discovery source, not a final fallback.
    sitemap_candidates = _sitemap_product_urls(
        session, q, max_sitemaps=64, max_urls=80
    )
    if add_many(sitemap_candidates, "product_sitemap"):
        return urls[:80]

    # 3. Search pages remain useful, but failure is non-fatal.
    for endpoint in (
        BASE_URL + "/en/search?q=" + quote_plus(q),
        BASE_URL + "/en/search?query=" + quote_plus(q),
        BASE_URL + "/en/search?search=" + quote_plus(q),
        BASE_URL + "/en/search?term=" + quote_plus(q),
    ):
        try:
            r = session.get(endpoint, headers=HEADERS, timeout=DISCOVERY_TIMEOUT)
        except requests.RequestException as exc:
            _dbg("search_endpoint_error", query=q, url=endpoint, error=f"{type(exc).__name__}: {exc}")
            continue
        _dbg("search_endpoint", query=q, url=endpoint, status=r.status_code, bytes=len(r.text or ""))
        if r.status_code >= 400:
            continue

        candidates = _extract_product_urls(r.text, q)
        # Merge URL-only candidates regardless of whether context candidates exist.
        candidates += [u for u in _product_urls_by_slug(r.text, q) if u not in candidates]
        _dbg("search_product_candidates", query=q, source=endpoint, count=len(candidates), sample=candidates[:10])
        if add_many(candidates, "search"):
            return urls[:80]

    # 4. Category sitemap and actual category pages.
    for category_url in _sitemap_category_urls(session, q, max_sitemaps=32, max_urls=40):
        if category_url == dedicated:
            continue
        try:
            page = session.get(category_url, headers=HEADERS, timeout=DISCOVERY_TIMEOUT)
        except requests.RequestException:
            continue
        if page.status_code >= 400:
            continue
        candidates = _extract_product_urls(page.text, q)
        candidates += [u for u in _product_urls_by_slug(page.text, q) if u not in candidates]
        if add_many(candidates, "sitemap_category"):
            return urls[:80]

    # 5. Broad categories are the final HTML fallback.
    broad = _discover_from_categories(session, q, max_urls=80)
    add_many(broad, "broad_categories")

    _dbg("discovery_done", query=q, count=len(urls), urls=urls[:20])
    return urls[:80]


def diagnostic_discovery(query):
    session = requests.Session()
    out = {"query": query, "stages": []}
    try:
        t0 = time.monotonic()
        try:
            catalog_links = _catalog_filter_links(session)
            catalog_error = None
        except Exception as exc:
            catalog_links, catalog_error = [], f"{type(exc).__name__}: {exc}"

        out["catalog_discovery"] = {
            "url": CATALOG_URL,
            "seconds": round(time.monotonic() - t0, 3),
            "link_count": len(catalog_links),
            "matching_url": _find_catalog_filter_url(session, query) if not catalog_error else None,
            "error": catalog_error,
        }
        out["product_sitemap"] = _sitemap_product_urls(session, query, max_sitemaps=64, max_urls=80)
        out["category_sitemap"] = _sitemap_category_urls(session, query, max_sitemaps=32, max_urls=40)
        out["discovered"] = _discover(session, clean(query))
        return out
    finally:
        session.close()


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    results, seen = [], set()
    try:
        discovered = _discover(session, query)
        _dbg("search_discovered", query=query, count=len(discovered), urls=discovered[:50])

        for url in discovered:
            try:
                r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
                _dbg("product_fetch", query=query, url=url, status=r.status_code, bytes=len(r.text or ""))
            except requests.RequestException as exc:
                _dbg("product_fetch_error", query=query, url=url, error=f"{type(exc).__name__}: {exc}")
                continue

            if r.status_code >= 400:
                _dbg("product_rejected", query=query, url=url, reason=f"http_{r.status_code}")
                continue

            item = _product(url, r.text, query)
            if not item:
                _dbg(
                    "product_rejected",
                    query=query,
                    url=url,
                    reason=_product_rejection_reason(url, r.text, query) or "unknown",
                )
                continue

            sku = item["identity"].get("sku")
            sku_value = sku.get("value") if sku else None
            key = (url, sku_value)
            if key in seen:
                continue

            seen.add(key)
            results.append(item)
            _dbg(
                "product_accepted",
                query=query,
                url=url,
                name=item.get("name"),
                sku=sku_value,
                price=item.get("price"),
            )

        _dbg("search_done", query=query, result_count=len(results))
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
