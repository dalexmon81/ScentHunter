"""Deloox scraper for ScentHunter.

Discovery is generic:
- Deloox search result pages
- Deloox category pages
- XML sitemaps

Discovery only finds candidate product URLs. Every candidate is fetched and
validated by the product-page parser before it can become a result.
"""

from __future__ import annotations

import json
import os
import re
from collections import deque
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
TIMEOUT = 10
DISCOVERY_TIMEOUT = 6
MAX_CANDIDATES = 160

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

CATEGORY_ROOTS = (
    f"{BASE_URL}/category/1000003/fragrances.html",
    f"{BASE_URL}/category/1075639/womens-fragrances.html",
    f"{BASE_URL}/category/1075660/womens-perfume.html",
    f"{BASE_URL}/category/1000054/mens-fragrances.html",
    f"{BASE_URL}/category/1025540/trending.html",
)

SITEMAP_ROOTS = (
    f"{BASE_URL}/sitemap.xml",
    f"{BASE_URL}/sitemap_index.xml",
    f"{BASE_URL}/sitemap-index.xml",
    f"{BASE_URL}/en/sitemap.xml",
)

PRODUCT_RE = re.compile(
    r'https?://(?:www\.)?deloox\.com[^"\'<>\s]*/product/[^"\'<>\s]+'
    r'|(?<![A-Za-z0-9])(?:/|(?:en|it|nl)/)product/[^"\'<>\s]+',
    re.I,
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


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(value).lower())).strip()


def tokens(value):
    return {x for x in norm(value).split() if len(x) > 1}


def matches(text, query):
    wanted = tokens(query)
    actual = tokens(text)
    return bool(wanted) and wanted.issubset(actual)


NON_FRAGRANCE = (
    "body mist", "body spray", "body lotion", "body cream", "body oil",
    "body wash", "shower gel", "shower oil", "hand cream", "deodorant",
    "after shave", "aftershave", "hair mist", "hair spray", "soap",
)


def query_wants_non_fragrance(query):
    wanted = tokens(query)
    return any(tokens(phrase).issubset(wanted) for phrase in NON_FRAGRANCE)


def contains_non_fragrance(text):
    actual = norm(text)
    return any(
        re.search(r"\b" + re.escape(norm(phrase)).replace(r"\ ", r"\s+") + r"\b", actual)
        for phrase in NON_FRAGRANCE
    )


def product_name_is_valid(name, query):
    return (
        matches(name, query)
        and (
            query_wants_non_fragrance(query)
            or not contains_non_fragrance(name)
        )
    )


def size_ml(*values):
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        " ".join(clean(x) for x in values),
        re.I,
    )
    if not match:
        return None
    number = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        number *= 10
    return int(number) if number.is_integer() else number


def concentration(*values):
    text = norm(" ".join(clean(x) for x in values))
    if re.search(r"\beau de toilette\b|\bedt\b", text):
        return "Eau de Toilette"
    if re.search(r"\beau de parfum\b|\bedp\b", text):
        return "Eau de Parfum"
    if re.search(r"\bextrait(?: de parfum)?\b", text):
        return "Extrait de Parfum"
    return None


def parse_price(value):
    match = re.search(
        r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?",
        clean(value),
    )
    if not match:
        return None
    try:
        return round(float(match.group(1).replace(",", ".")), 2)
    except ValueError:
        return None


def _get(session, url, timeout=TIMEOUT):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        _dbg("http_error", url=url, error=f"{type(exc).__name__}: {exc}")
        return None


def _is_product_url(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return (
        parsed.netloc.lower() in {"deloox.com", "www.deloox.com"}
        and "/product/" in parsed.path.lower()
    )


def _normalize_product_url(raw_url):
    if not raw_url:
        return None
    raw_url = clean(raw_url).replace("\\/", "/")
    if raw_url.startswith(("javascript:", "mailto:", "#")):
        return None
    url = urljoin(BASE_URL, raw_url).split("#")[0].split("?")[0]
    return url if _is_product_url(url) else None


def _product_slug_matches(url, query):
    wanted = tokens(query)
    return bool(wanted) and wanted.issubset(tokens(urlparse(url).path))


def _product_context(anchor):
    values = [
        anchor.get_text(" ", strip=True),
        anchor.get("aria-label"),
        anchor.get("title"),
        anchor.get("data-name"),
        anchor.get("data-product-name"),
    ]
    return clean(" ".join(x for x in values if clean(x)))


def _card_context(anchor):
    node = anchor
    fallback = ""
    for _ in range(7):
        node = node.parent if node is not None else None
        if node is None:
            break

        text = clean(node.get_text(" ", strip=True))
        if not text or len(text) > 6000:
            continue

        attrs = clean(
            " ".join(
                str(node.get(key, ""))
                for key in (
                    "class",
                    "id",
                    "data-product",
                    "data-product-name",
                    "data-testid",
                )
            )
        )
        is_card = (
            node.name in {"article", "li"}
            or any(x in attrs.lower() for x in ("product", "card", "item"))
        )

        if is_card and not fallback:
            fallback = text
        if is_card:
            return text

    return fallback


def _structured_context(blob, start, end):
    left = blob.rfind("{", 0, start)
    right = blob.find("}", end)
    if left < 0 or right < end or right - left > 5000:
        return ""

    obj = blob[left:right + 1]
    for pattern in (
        r'"(?:name|productName|product_name|title|productTitle)"\s*:\s*"([^"]{1,400})"',
        r"'(?:name|productName|product_name|title|productTitle)'\s*:\s*'([^']{1,400})'",
    ):
        match = re.search(pattern, obj, re.I)
        if match:
            return clean(match.group(1))
    return ""


def _extract_product_urls(html, query=None):
    """Extract product URLs without making card text a discovery gate.

    A candidate is kept when:
    - its URL slug contains the query tokens; OR
    - its surrounding card/structured context contains the query tokens.

    This is only discovery. Final validation is done on the product page.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    query = clean(query)
    wanted = tokens(query)
    if not wanted:
        return []

    found, seen = [], set()
    trace_count = 0

    def add(raw_url, context="", source="unknown"):
        nonlocal trace_count

        url = _normalize_product_url(raw_url)
        if not url or url in seen:
            return

        slug_match = _product_slug_matches(url, query)
        context_match = matches(context, query)

        if DEBUG_DISCOVERY and trace_count < MATCH_TRACE_LIMIT:
            _dbg(
                "product_url_match",
                source=source,
                url=url,
                context=clean(context)[:400],
                slug_match=slug_match,
                context_match=context_match,
            )
            trace_count += 1

        if not (slug_match or context_match):
            return

        seen.add(url)
        found.append(url)

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if "/product/" not in href.lower():
            continue
        context = _product_context(anchor)
        if not matches(context, query):
            context = _card_context(anchor) or context
        add(href, context, "anchor")

    raw = (html or "").replace("\\\\/", "/").replace("\\/", "/")
    for tag in soup.find_all(["script", "div", "article", "li"]):
        blob = tag.get_text() if tag.name == "script" else tag.get_text(" ", strip=True)
        if "/product/" not in blob.lower():
            continue
        for match in PRODUCT_RE.finditer(blob):
            add(
                match.group(0),
                _structured_context(blob, match.start(), match.end()),
                tag.name,
            )

    for match in PRODUCT_RE.finditer(raw):
        add(
            match.group(0),
            _structured_context(raw, match.start(), match.end()),
            "raw_html",
        )

    return found[:MAX_CANDIDATES]


def _product_urls_by_slug(html, query):
    wanted = tokens(query)
    if not wanted:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    found, seen = [], set()

    def add(raw_url):
        url = _normalize_product_url(raw_url)
        if not url or url in seen or not _product_slug_matches(url, query):
            return
        seen.add(url)
        found.append(url)

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if "/product/" in href.lower():
            add(href)

    raw = (html or "").replace("\\\\/", "/").replace("\\/", "/")
    for match in PRODUCT_RE.finditer(raw):
        add(match.group(0))

    return found[:MAX_CANDIDATES]


def _category_slug(url):
    value = urlparse(url).path.rsplit("/", 1)[-1]
    return value[:-5] if value.lower().endswith(".html") else value


def _absolute_category_url(raw_url):
    if not raw_url:
        return None
    url = urljoin(BASE_URL, clean(raw_url).replace("\\/", "/"))
    url = url.split("#")[0].split("?")[0]
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
        return None
    if "/category/" not in parsed.path.lower() or not parsed.path.lower().endswith(".html"):
        return None
    return url


def _category_score(url, label, query):
    wanted = tokens(query)
    if not wanted:
        return 0
    values = tokens(_category_slug(url)) | tokens(label)
    return len(wanted & values)


def _extract_category_links(html, query):
    soup = BeautifulSoup(html or "", "html.parser")
    found, seen = [], set()

    for anchor in soup.find_all("a", href=True):
        url = _absolute_category_url(anchor.get("href"))
        if not url or url in seen:
            continue

        label = clean(
            " ".join(
                x
                for x in (
                    anchor.get_text(" ", strip=True),
                    anchor.get("aria-label"),
                    anchor.get("title"),
                    anchor.get("data-name"),
                    anchor.get("data-category-name"),
                )
                if clean(x)
            )
        )
        score = _category_score(url, label, query)
        if score:
            seen.add(url)
            found.append((score, url, label))

    found.sort(key=lambda item: (-item[0], len(item[1])))
    return found


def _sitemap_product_urls(session, query, max_sitemaps=64):
    wanted = tokens(query)
    if not wanted:
        return []

    pending = deque(SITEMAP_ROOTS)
    seen_sitemaps = set()
    found, seen_products = [], set()

    while pending and len(seen_sitemaps) < max_sitemaps:
        sitemap_url = pending.popleft()
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        response = _get(session, sitemap_url, DISCOVERY_TIMEOUT)
        if response is None:
            continue

        body = (response.text or "").lstrip()
        if not body.startswith(("<?xml", "<urlset", "<sitemapindex")):
            continue

        soup = BeautifulSoup(response.text, "xml")
        children = []

        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())
            if not value:
                continue

            low = value.lower()
            if "/product/" in low:
                url = _normalize_product_url(value)
                if (
                    url
                    and _product_slug_matches(url, query)
                    and url not in seen_products
                ):
                    seen_products.add(url)
                    found.append(url)
                continue

            if low.endswith(".xml") or "sitemap" in low:
                if value not in seen_sitemaps:
                    children.append(value)

        children.sort(
            key=lambda value: (
                0
                if any(
                    word in value.lower()
                    for word in ("product", "products", "perfume", "fragrance")
                )
                else 1,
                value.lower(),
            )
        )
        pending.extendleft(reversed(children))

        if len(found) >= MAX_CANDIDATES:
            break

    _dbg(
        "product_sitemap_done",
        query=query,
        sitemap_count=len(seen_sitemaps),
        count=len(found),
        sample=found[:20],
    )
    return found[:MAX_CANDIDATES]


def _discover_from_page(session, url, query, source):
    response = _get(session, url, DISCOVERY_TIMEOUT)
    if response is None:
        return []

    candidates = _extract_product_urls(response.text, query)
    slug_candidates = _product_urls_by_slug(response.text, query)

    for candidate in slug_candidates:
        if candidate not in candidates:
            candidates.append(candidate)

    _dbg(
        "discovery_page",
        source=source,
        url=url,
        status=response.status_code,
        candidates=len(candidates),
        sample=candidates[:20],
    )
    return candidates[:MAX_CANDIDATES]


def _discover(session, query):
    """Generic discovery. No product-specific seeds or exceptions."""
    query = clean(query)
    urls, seen = [], set()

    def add_many(items, source):
        added = 0
        for url in items or []:
            url = _normalize_product_url(url)
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
            added += 1
            if len(urls) >= MAX_CANDIDATES:
                break
        _dbg(
            "discovery_merge",
            source=source,
            added=added,
            total=len(urls),
        )
        return len(urls) >= MAX_CANDIDATES

    # 1. Deloox's own search endpoints.
    for endpoint in (
        f"{BASE_URL}/en/search?q={quote_plus(query)}",
        f"{BASE_URL}/en/search?query={quote_plus(query)}",
        f"{BASE_URL}/en/search?search={quote_plus(query)}",
        f"{BASE_URL}/en/search?term={quote_plus(query)}",
    ):
        if add_many(
            _discover_from_page(session, endpoint, query, "search"),
            "search",
        ):
            return urls[:MAX_CANDIDATES]

    # 2. Product sitemap. URL slug is only a discovery signal.
    if add_many(
        _sitemap_product_urls(session, query),
        "product_sitemap",
    ):
        return urls[:MAX_CANDIDATES]

    # 3. Generic fragrance/category pages.
    for category_url in CATEGORY_ROOTS:
        if add_many(
            _discover_from_page(
                session,
                category_url,
                query,
                "category",
            ),
            "category",
        ):
            return urls[:MAX_CANDIDATES]

    _dbg(
        "discovery_done",
        query=query,
        count=len(urls),
        urls=urls[:30],
    )
    return urls[:MAX_CANDIDATES]


def _jsonld(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            item_type = item.get("@type")
            if (
                item_type == "Product"
                or (
                    isinstance(item_type, list)
                    and "Product" in item_type
                )
                or "offers" in item
            ):
                return item

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)

    return {}


def _availability(data, soup):
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
            text = norm(raw)
            if "instock" in text or "in stock" in text or "available" in text:
                return "in_stock"
            if any(
                x in text
                for x in (
                    "outofstock",
                    "out of stock",
                    "soldout",
                    "sold out",
                    "unavailable",
                    "not available",
                )
            ):
                return "out_of_stock"

    for node in soup.select(
        '[itemprop="availability"], '
        'meta[property="product:availability"], '
        'meta[name="availability"]'
    ):
        text = norm(node.get("content") or node.get_text(" ", strip=True))
        if "instock" in text or "in stock" in text or "available" in text:
            return "in_stock"
        if any(
            x in text
            for x in (
                "outofstock",
                "out of stock",
                "soldout",
                "sold out",
                "unavailable",
                "not available",
            )
        ):
            return "out_of_stock"

    return "unknown"


def _selected_size(soup, data, name):
    value = size_ml(name)
    if value is not None:
        return value

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
                )
                if clean(x)
            )
            value = size_ml(blob)
            if value is not None:
                return value

    return size_ml(data.get("name") if isinstance(data, dict) else "")


def _product(url, html, query):
    soup = BeautifulSoup(html, "html.parser")
    data = _jsonld(soup)

    h1 = soup.find("h1")
    h1_name = clean(h1.get_text(" ", strip=True)) if h1 else ""
    name = h1_name or clean(data.get("name"))

    if not name or not product_name_is_valid(name, query):
        return None

    text = soup.get_text(" ", strip=True)

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

    product_line = ""
    match = re.search(
        r"product line\s+(.+?)(?:for whom|fragrance type|season|spray|article number)",
        text,
        re.I,
    )
    if match:
        product_line = clean(match.group(1))

    gtin = clean(data.get("gtin13") or data.get("gtin") or "") or None
    mpn = clean(data.get("mpn") or "") or None
    sku = clean(data.get("sku") or "") or None

    image = data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None

    availability = _availability(data, soup)
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
            "availability": availability,
        },
        "provenance": {
            "source_page": url,
            "product_source": "jsonld_or_page",
        },
        "raw_data": {"jsonld": data},
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": availability == "in_stock",
    }


def _product_rejection_reason(html, query):
    soup = BeautifulSoup(html, "html.parser")
    data = _jsonld(soup)
    h1 = soup.find("h1")
    name = clean(h1.get_text(" ", strip=True)) if h1 else clean(data.get("name"))

    if not name:
        return "missing_product_name"
    if not product_name_is_valid(name, query):
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


def diagnostic_discovery(query):
    query = clean(query)
    session = requests.Session()
    try:
        discovered = _discover(session, query)
        return {
            "query": query,
            "discovered": discovered,
            "count": len(discovered),
        }
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
        _dbg(
            "search_discovered",
            query=query,
            count=len(discovered),
            urls=discovered[:50],
        )

        for url in discovered:
            response = _get(session, url, TIMEOUT)
            if response is None:
                continue

            item = _product(url, response.text, query)
            if not item:
                _dbg(
                    "product_rejected",
                    query=query,
                    url=url,
                    reason=_product_rejection_reason(
                        response.text,
                        query,
                    ),
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

        _dbg(
            "search_done",
            query=query,
            result_count=len(results),
        )
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

    payload = (
        diagnostic_discovery(args.query)
        if args.diagnose
        else search(args.query)
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
