"""Deloox scraper - rebuilt from the working scraper architecture.

Design borrowed from the working ParfumZentrum / Orioudh / Bplatz scrapers:
    query variants -> candidate URL discovery -> strict product validation
    -> structured product extraction -> deduplication.

Important: there are NO product-name exceptions (for example Liquid Brun).
"""
from __future__ import annotations

import json
import re
from itertools import combinations
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
TIMEOUT = 12
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-GB,en;q=0.9,it;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
    "spray", "ml", "for", "by", "pour", "the", "and", "men",
    "man", "women", "woman", "herren", "damen",
}

NON_PERFUME_WORDS = {
    "gift set", "set regalo", "coffret", "bundle", "deodorant",
    "deo spray", "shower gel", "body lotion", "after shave",
    "aftershave", "travel set", "discovery set", "kit",
}


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value) -> str:
    value = clean(value).lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def query_tokens(query: str):
    return [
        x for x in norm(query).split()
        if x and x not in IGNORED_QUERY_WORDS
    ]


def matches_name(name: str, query: str) -> bool:
    wanted = query_tokens(query)
    have = set(norm(name).split())
    return bool(wanted) and all(token in have for token in wanted)


def relevant_text(text: str, query: str) -> bool:
    """Looser discovery match: tokens may be in a URL/card context."""
    wanted = query_tokens(query)
    haystack = norm(text)
    return bool(wanted) and all(token in haystack for token in wanted)


def candidate_queries(query: str):
    """Small, deterministic query ladder like the working scrapers."""
    raw = clean(query)
    n = norm(raw)
    if not n:
        return []

    out = []

    def add(value):
        value = clean(value)
        key = norm(value)
        if value and key and key not in {norm(x) for x in out}:
            out.append(value)

    add(raw)

    tokens = query_tokens(raw)
    if tokens:
        add(" ".join(tokens))

    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        n,
    )
    if compact != n:
        add(compact)

    # Individual meaningful tokens help when Deloox's search engine is poor
    # with multi-word names. The final product page still performs strict
    # validation, so discovery can be broad without corrupting results.
    for token in tokens:
        if len(token) >= 3:
            add(token)

    # Also try adjacent pairs for names such as "French Avenue Liquid Brun".
    for a, b in combinations(tokens, 2):
        if len(a) >= 3 and len(b) >= 3:
            add(f"{a} {b}")
        if len(out) >= 10:
            break

    return out[:10]


def _absolute_product_url(raw_url: str):
    raw_url = clean(raw_url).replace("\\/", "/")
    if not raw_url or raw_url.startswith(("javascript:", "mailto:", "#")):
        return None
    url = urljoin(BASE_URL, raw_url).split("#")[0].split("?")[0]
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
        return None
    if "/product/" not in parsed.path.lower():
        return None
    return url


def _absolute_category_url(raw_url: str):
    raw_url = clean(raw_url).replace("\\/", "/")
    if not raw_url or raw_url.startswith(("javascript:", "mailto:", "#")):
        return None
    url = urljoin(BASE_URL, raw_url).split("#")[0].split("?")[0]
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
        return None
    if "/category/" not in parsed.path.lower():
        return None
    return url


def _extract_product_urls(html: str, query: str, allow_opaque=False):
    """Extract product URLs and score them using the *product-card context*.

    Deloox often puts the product URL on an image-only <a>.  In that case
    ``a.get_text()`` is empty even though the product name is present in the
    same card (usually a parent/sibling node).  The old extractor therefore
    classified real matches as opaque and, when the page contained many
    products, they could be pushed out of the candidate window.

    The product page remains authoritative; this function only decides which
    URLs deserve to be fetched first.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    candidates = []
    seen = set()
    wanted = query_tokens(query)

    def add(raw_url, context=""):
        url = _absolute_product_url(raw_url)
        if not url or url in seen:
            return

        score_text = norm(f"{context} {url}")
        score = sum(1 for token in wanted if token in score_text)

        if score == 0 and not allow_opaque:
            return

        seen.add(url)
        candidates.append((score, url))

    # IMPORTANT: product links are frequently image-only.  Score the link
    # together with the surrounding product-card text, not just the <a>.
    for a in soup.find_all("a", href=True):
        context_parts = [a.get_text(" ", strip=True)]

        node = a
        for _ in range(3):
            node = node.parent
            if not node or not getattr(node, "get_text", None):
                break
            context_parts.append(node.get_text(" ", strip=True))

        add(a.get("href"), " ".join(context_parts))

    # Also scan inline JSON/HTML.  Use a small window around each URL so that
    # product names stored beside opaque numeric product URLs can score.
    raw = (html or "").replace("\\/", "/")
    patterns = [
        r'https?://(?:www\.)?deloox\.com/[^"\'<>\s]+/product/[^"\'<>\s]+',
        r'["\']((?:/)?(?:[a-z]{2}/)?product/[^"\']+)["\']',
        r'["\'](\/product\/[^"\']+)["\']',
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, raw, re.I):
            raw_url = match.group(1) if match.lastindex else match.group(0)
            start = max(0, match.start() - 1800)
            end = min(len(raw), match.end() + 1800)
            add(raw_url, raw[start:end])

    # Highest relevance first.  This is critical when a category page has
    # hundreds of products: the requested product must not be lost behind the
    # first arbitrary 80 cards.
    candidates.sort(key=lambda x: (-x[0], len(x[1])))
    return [url for _, url in candidates]


def _extract_category_urls(html: str):
    """Extract candidate category URLs from a search or page HTML."""
    soup = BeautifulSoup(html or "", "html.parser")
    seen = set()
    cats = []

    def add(raw_url, context=""):
        url = _absolute_category_url(raw_url)
        if not url or url in seen:
            return
        seen.add(url)
        cats.append(url)

    # anchors
    for a in soup.find_all("a", href=True):
        add(a.get("href"), a.get_text(" ", strip=True))

    # scan inline for category patterns
    raw = (html or "").replace("\\/", "/")
    for raw_url in re.findall(r'["\']((?:/)?(?:[a-z]{2}/)?category/[^"\']+\.html)["\']', raw, re.I):
        add(raw_url)

    return cats


def _discover_from_search(session: requests.Session, query: str, max_urls=80):
    """Search-driven discovery, modelled after Bplatz/Orioudh.

    Improvements:
     - scan search page for product anchors and category anchors
     - if no product anchors, follow relevant categories (token-match)
     - detect inline XHR / fetch / axios endpoints and try them (lightweight)
    """
    endpoints = (
        BASE_URL + "/en/search?query={}",
        BASE_URL + "/en/search?search={}",
        BASE_URL + "/en/search?q={}",
        BASE_URL + "/en?search={}",
        BASE_URL + "/search?query={}",
        BASE_URL + "/search?q={}",
    )

    urls = []
    seen = set()

    for search_query in candidate_queries(query):
        encoded = quote_plus(search_query)
        for template in endpoints:
            try:
                r = session.get(
                    template.format(encoded),
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException:
                continue

            if r.status_code >= 400 or not r.text:
                continue

            html = r.text
            # 1) try to extract product anchors directly
            found = _extract_product_urls(html, query, allow_opaque=True)
            print(f"DELOOX: search '{search_query}' -> found {len(found)} product anchors via anchors/regex")
            for url in found:
                if url in seen:
                    continue
                seen.add(url)
                urls.append(url)
                if len(urls) >= max_urls:
                    return urls

            # 2) attempt to find inline XHR/api endpoints and call them
            # search for common patterns: fetch('/en/...'), axios.get('/...'), $.ajax('/...')
            xhr_candidates = set()
            for m in re.finditer(r"(?:fetch|axios\.get|\$\.ajax)\s*\(\s*['\"]([^'\"]+)['\"]", html, re.I):
                href = m.group(1)
                if "product" in href.lower() or "search" in href.lower() or "category" in href.lower() or "productlist" in href.lower():
                    api = urljoin(BASE_URL, href)
                    xhr_candidates.add(api)
            # also scan for possible API urls in raw text
            for m in re.finditer(r'["\'](\/(?:en\/)?(?:search|productlist|catalog|suggest|category)[^"\']+)["\']', html, re.I):
                api = urljoin(BASE_URL, m.group(1))
                xhr_candidates.add(api)

            if xhr_candidates:
                print(f"DELOOX: found {len(xhr_candidates)} possible XHR endpoints; trying up to 4")
            tried = 0
            for api in list(xhr_candidates)[:4]:
                tried += 1
                try:
                    rr = session.get(api, headers=HEADERS, timeout=TIMEOUT)
                except requests.RequestException:
                    continue
                if rr.status_code != 200 or not rr.text:
                    continue
                # parse the API response for product or category urls
                new_products = _extract_product_urls(rr.text, query, allow_opaque=True)
                new_categories = _extract_category_urls(rr.text)
                print(f"DELOOX: XHR {api} -> products {len(new_products)}, categories {len(new_categories)}")
                for url in new_products:
                    if url not in seen:
                        seen.add(url)
                        urls.append(url)
                        if len(urls) >= max_urls:
                            return urls
                for url in new_categories:
                    # follow these categories below if no direct products found
                    if url not in seen:
                        seen.add(url)
                        # we'll store category to follow in next step
                        urls.append(url)
                        if len(urls) >= max_urls:
                            return urls

            # 3) if no product anchors found on this search page, try categories present on the page
            if not found:
                cats = _extract_category_urls(html)
                print(f"DELOOX: search '{search_query}' -> found {len(cats)} category anchors")
                # score categories by token overlap in anchor text/href
                scored = []
                wanted = query_tokens(query)
                for c in cats:
                    # prefer categories whose slug or label contains tokens
                    score = sum(1 for t in wanted if t in norm(c))
                    if score < 1:
                        # still consider low-score category if it contains some query token
                        if any(t in c.lower() for t in wanted):
                            score = 1
                    if score > 0:
                        scored.append((score, c))
                scored.sort(key=lambda x: (-x[0], len(x[1])))
                # follow top category pages
                for _, cat_url in scored[:10]:
                    try:
                        page = session.get(cat_url, headers=HEADERS, timeout=TIMEOUT)
                    except requests.RequestException:
                        continue
                    if page.status_code >= 400 or not page.text:
                        continue
                    # extract products from category page
                    cat_products = _extract_product_urls(page.text, query, allow_opaque=True)
                    print(f"DELOOX: followed category {cat_url} -> found {len(cat_products)} products")
                    for p in cat_products:
                        if p not in seen:
                            seen.add(p)
                            urls.append(p)
                            if len(urls) >= max_urls:
                                return urls

    return urls


def _discover_search_form(session: requests.Session, query: str, max_urls=50):
    """Use Deloox's own current search form when it is discoverable."""
    try:
        r = session.get(BASE_URL + "/", headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return []
    if r.status_code >= 400:
        return []

    soup = BeautifulSoup(r.text or "", "html.parser")
    forms = []

    for form in soup.find_all("form"):
        action = urljoin(BASE_URL + "/", form.get("action") or "")
        method = (form.get("method") or "get").lower()
        if method != "get":
            continue

        qname = None
        for inp in form.find_all("input"):
            name = clean(inp.get("name"))
            typ = clean(inp.get("type")).lower()
            if name and (
                typ in {"search", "text"}
                or name.lower() in {"q", "query", "search", "keyword", "term"}
            ):
                qname = name
                break

        if qname:
            forms.append((action, qname))

    urls = []
    seen = set()
    for action, qname in forms[:2]:
        for search_query in candidate_queries(query)[:5]:
            try:
                r = session.get(
                    action,
                    params={qname: search_query},
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException:
                continue
            if r.status_code >= 400:
                continue
            for url in _extract_product_urls(r.text, query, allow_opaque=True):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
                    if len(urls) >= max_urls:
                        return urls
    return urls


def _category_seed_pages():
    # Generic category entry points only. No product-specific exceptions.
    return (
        BASE_URL + "/category/1075660/womens-perfume.html",
        BASE_URL + "/category/1075750/mens-perfume.html",
    )


def _discover_from_categories(session: requests.Session, query: str, max_urls=60):
    urls = []
    seen = set()

    for category_url in _category_seed_pages():
        try:
            r = session.get(category_url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue

        # First use product cards already present on the category page.
        for url in _extract_product_urls(r.text, query, allow_opaque=True):
            if url not in seen:
                seen.add(url)
                urls.append(url)
                if len(urls) >= max_urls:
                    return urls

        # Then inspect category/product-line links and follow only relevant ones.
        soup = BeautifulSoup(r.text or "", "html.parser")
        links = []
        link_seen = set()
        wanted = query_tokens(query)

        for a in soup.find_all("a", href=True):
            href = urljoin(category_url, a.get("href", ""))
            parsed = urlparse(href)
            if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
                continue
            if "/category/" not in parsed.path.lower():
                continue
            label = a.get_text(" ", strip=True)
            score_text = norm(f"{label} {href}")
            score = sum(1 for token in wanted if token in score_text)
            if score <= 0 or href in link_seen:
                continue
            link_seen.add(href)
            links.append((score, href))

        links.sort(key=lambda x: (-x[0], len(x[1])))
        for _, page_url in links[:12]:
            try:
                page = session.get(page_url, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException:
                continue
            if page.status_code >= 400:
                continue
            for url in _extract_product_urls(page.text, query, allow_opaque=True):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
                    if len(urls) >= max_urls:
                        return urls

    return urls


def _sitemap_product_urls(session: requests.Session, query: str, max_sitemaps=20, max_urls=80):
    """Sitemap discovery modelled after ParfumZentrum."""
    wanted = query_tokens(query)
    if not wanted:
        return []

    roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )

    pending = list(roots)
    seen_maps = set()
    found = []
    seen_products = set()

    while pending and len(seen_maps) < max_sitemaps and len(found) < max_urls:
        sitemap_url = pending.pop(0)
        if sitemap_url in seen_maps:
            continue
        seen_maps.add(sitemap_url)

        try:
            r = session.get(sitemap_url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue

        body = r.text or ""
        if "<loc" not in body.lower():
            continue

        soup = BeautifulSoup(body, "xml")
        for loc in soup.find_all("loc"):
            url = clean(loc.get_text())
            if not url:
                continue
            low = url.lower()

            if "/product/" in low:
                score = sum(1 for token in wanted if token in norm(url))
                if score >= max(1, len(wanted) - 1) and url not in seen_products:
                    seen_products.add(url)
                    found.append(url)
                    if len(found) >= max_urls:
                        break
            elif low.endswith(".xml") or "sitemap" in low:
                if url not in seen_maps:
                    pending.append(url)

    return found


def discover(session: requests.Session, query: str):
    """Unified discovery pipeline. No product-specific branch."""
    urls = []
    seen = set()

    # 1. Search is the primary discovery mechanism, as in Bplatz/Orioudh.
    for url in _discover_from_search(session, query, max_urls=80):
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= 80:
            return urls

    # 2. Use Deloox's own form if search URLs were incomplete.
    for url in _discover_search_form(session, query, max_urls=50):
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= 80:
            return urls

    # 3. Generic category discovery.
    for url in _discover_from_categories(session, query, max_urls=60):
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= 80:
            return urls

    # 4. Sitemap discovery, like ParfumZentrum.
    for url in _sitemap_product_urls(session, query, max_sitemaps=20, max_urls=80):
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= 80:
            break

    return urls[:80]


def _jsonld_product(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        queue = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            typ = item.get("@type")
            if typ == "Product" or "offers" in item:
                return item
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
    return {}


def parse_price(value):
    if value in (None, ""):
        return None
    m = re.search(r"\d{1,5}(?:[.,]\d{1,2})?", clean(value))
    if not m:
        return None
    try:
        n = float(m.group(0).replace(",", "."))
    except ValueError:
        return None
    return round(n, 2) if 0 < n < 10000 else None


def _availability(soup, offer):
    # Structured data first: never let unrelated recommendation cards decide.
    if isinstance(offer, dict):
        raw = norm(offer.get("availability") or "")
        if raw:
            if any(x in raw for x in ("outofstock", "soldout", "discontinued", "unavailable")):
                return "out_of_stock"
            if any(x in raw for x in ("instock", "limitedavailability", "preorder")):
                return "in_stock"

    scoped = []
    selectors = [
        '[itemprop="availability"]',
        '[class*="availability" i]',
        '[class*="stock" i]',
        '[class*="add-to-cart" i]',
        '[class*="buy" i]',
        'button[type="submit"]',
    ]
    seen = set()
    for selector in selectors:
        try:
            nodes = soup.select(selector)
        except Exception:
            nodes = []
        for node in nodes[:20]:
            if id(node) in seen:
                continue
            seen.add(id(node))
            scoped.append(clean(node.get("content") or node.get("aria-label") or node.get_text(" ", strip=True)))

    text = norm(" ".join(scoped))
    if text:
        if any(x in text for x in ("sold out", "out of stock", "not available", "unavailable")):
            return "out_of_stock"
        if any(x in text for x in ("in stock", "available", "add to cart", "add to basket", "buy now", "bestellen")):
            return "in_stock"

    return "unknown"


def _extract_product(url: str, html: str, query: str):
    soup = BeautifulSoup(html or "", "html.parser")
    data = _jsonld_product(soup)

    h1 = soup.find("h1")
    h1_name = clean(h1.get_text(" ", strip=True)) if h1 else ""
    name = clean(data.get("name")) or h1_name

    # The product page, not the search URL, is authoritative.
    if not name or not matches_name(name, query):
        return None

    # Explicitly reject obvious non-product variants unless requested.
    name_n = norm(name)
    q_n = norm(query)
    if any(norm(x) in name_n and norm(x) not in q_n for x in NON_PERFUME_WORDS):
        return None

    brand = data.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    brand = clean(brand)

    offers = data.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    elif not isinstance(offers, list):
        offers = []
    offer = next((x for x in offers if isinstance(x, dict)), {})

    price = parse_price(offer.get("price"))
    if price is None:
        # Product-level semantic fields before any broad page-text fallback.
        for selector in (
            '[itemprop="price"]',
            'meta[property="product:price:amount"]',
            'meta[itemprop="price"]',
            'meta[name="price"]',
        ):
            node = soup.select_one(selector)
            if node:
                price = parse_price(node.get("content") or node.get_text(" ", strip=True))
                if price is not None:
                    break
    if price is None:
        return None

    image = data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    image = urljoin(url, str(image)) if image else ""

    size = None
    m = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", name, re.I)
    if m:
        size = float(m.group(1).replace(",", "."))
        if m.group(2).lower() == "cl":
            size *= 10
        if size.is_integer():
            size = int(size)

    concentration = None
    n = norm(name)
    if "eau de toilette" in n or " edt" in f" {n}":
        concentration = "Eau de Toilette"
    elif "eau de parfum" in n or " edp" in f" {n}":
        concentration = "Eau de Parfum"
    elif "extrait" in n:
        concentration = "Extrait de Parfum"

    gtin = clean(data.get("gtin13") or data.get("gtin") or "") or None
    sku = clean(data.get("sku") or "") or None
    mpn = clean(data.get("mpn") or "") or None
    avail = _availability(soup, offer)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand,
            "url": url,
            "image": image,
        },
        "identity": {
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
            "mpn": {"value": mpn, "source": "jsonld"} if mpn else None,
            "sku": {"value": sku, "source": "jsonld"} if sku else None,
            "store_product_id": {"value": sku, "source": "deloox_sku"} if sku else None,
        },
        "attributes": {
            "size_ml": {"value": size, "source": "product_name"} if size is not None else None,
            "concentration": {"value": concentration, "source": "product_name"} if concentration else None,
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
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
        # Unknown is deliberately NOT treated as out-of-stock.
        "available": avail != "out_of_stock",
    }


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    results = []
    seen = set()
    try:
        candidate_urls = discover(session, query)
        print(f"DELOOX: discover returned {len(candidate_urls)} candidate urls for query '{query}'")
        for url in candidate_urls:
            # some discovery results might be category urls - skip non-product URLs here
            if "/product/" not in url:
                continue
            try:
                r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException:
                continue
            if r.status_code >= 400:
                continue

            item = _extract_product(url, r.text, query)
            if not item:
                continue

            sku = item.get("identity", {}).get("sku")
            sku_value = sku.get("value") if isinstance(sku, dict) else sku
            key = (url, sku_value, norm(item.get("name")))
            if key in seen:
                continue
            seen.add(key)
            results.append(item)

        results.sort(key=lambda x: (x.get("offer", {}).get("price") is None, x.get("offer", {}).get("price") or 0))
        return results
    finally:
        session.close()


def scrape(query):
    return search(query)
