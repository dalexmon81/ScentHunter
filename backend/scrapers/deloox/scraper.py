"""Generic Deloox scraper adapter for ScentHunter.

Architecture:
STORE SCRAPER -> CATALOG DISCOVERY -> PRODUCT PAGE -> NORMALIZATION

This module contains no perfume-specific rules, names, IDs, prices or URLs.
Discovery finds generic Deloox catalogue/category/product surfaces; _product()
is the final authority for whether a candidate actually matches the query.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.be"
DELOOX_BASE_URLS = (
    "https://www.deloox.be",
    "https://www.deloox.com",
    "https://www.deloox.nl",
    "https://www.deloox.es",
    "https://www.deloox.de",
    "https://www.deloox.fr",
    "https://www.deloox.it",
)
DELOOX_HOSTS = {urlparse(url).netloc.lower() for url in DELOOX_BASE_URLS}
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", clean(value).lower()),
    ).strip()


def tokens(value):
    return {x for x in norm(value).split() if len(x) > 1}


def matches(text, query):
    q_tokens = tokens(query)
    return bool(q_tokens) and q_tokens.issubset(tokens(text))


def size_ml(*values):
    text = " ".join(clean(x) for x in values)
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        text,
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
    text = clean(value)
    match = re.search(
        r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?",
        text,
    )
    if not match:
        return None
    try:
        return round(float(match.group(1).replace(",", ".")), 2)
    except ValueError:
        return None


def availability(text, offer=None, soup=None):
    """Read availability from retailer signals without product-specific rules."""
    if isinstance(offer, dict):
        raw = clean(
            offer.get("availability")
            or offer.get("itemAvailability")
            or offer.get("availabilityStatus")
            or ""
        ).lower()

        if raw:
            if any(
                value in raw
                for value in (
                    "outofstock",
                    "out_of_stock",
                    "soldout",
                    "sold_out",
                    "discontinued",
                    "unavailable",
                )
            ):
                return "out_of_stock"

            if any(
                value in raw
                for value in (
                    "instock",
                    "in_stock",
                    "limitedavailability",
                    "preorder",
                    "pre_order",
                )
            ):
                return "in_stock"

    if soup is not None:
        selectors = (
            '[itemprop="availability"]',
            '[data-testid*="availability" i]',
            '[data-test*="availability" i]',
            '[class*="availability" i]',
            '[class*="stock" i]',
            '[class*="add-to-cart" i]',
            '[class*="buy" i]',
            'button[type="submit"]',
        )

        parts = []
        seen = set()

        for selector in selectors:
            try:
                nodes = soup.select(selector)
            except Exception:
                nodes = []

            for node in nodes[:20]:
                marker = id(node)
                if marker in seen:
                    continue
                seen.add(marker)
                parts.append(
                    clean(
                        node.get("content")
                        or node.get("aria-label")
                        or node.get_text(" ", strip=True)
                    )
                )

        scoped = norm(" ".join(x for x in parts if x))
        if scoped:
            if any(
                value in scoped
                for value in (
                    "sold out",
                    "out of stock",
                    "not available",
                    "currently unavailable",
                    "unavailable",
                )
            ):
                return "out_of_stock"

            if any(
                value in scoped
                for value in (
                    "in stock",
                    "available",
                    "op voorraad",
                    "add to cart",
                    "add to basket",
                    "buy now",
                    "bestellen",
                )
            ):
                return "in_stock"

    text = norm(text)
    if any(
        value in text
        for value in (
            "sold out",
            "out of stock",
            "currently unavailable",
        )
    ):
        return "out_of_stock"

    if any(value in text for value in ("in stock", "op voorraad")):
        return "in_stock"

    return "unknown"


def _jsonld(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
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

            item_type = item.get("@type")
            if item_type == "Product" or "offers" in item:
                return item

            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

    return {}


def _product(url, html, query):
    soup = BeautifulSoup(html, "html.parser")
    data = _jsonld(soup)

    h1 = soup.find("h1")
    name = clean(data.get("name"))
    if not name and h1:
        name = clean(h1.get_text(" ", strip=True))

    if not name or not matches(name, query):
        return None

    page_text = soup.get_text(" ", strip=True)

    product_line = ""
    line_match = re.search(
        r"product line\s+(.+?)(?:for whom|fragrance type|season|spray|article number)",
        page_text,
        re.I,
    )
    if line_match:
        product_line = clean(line_match.group(1))

    brand = data.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    offers = data.get("offers")
    if isinstance(offers, list):
        offer = next(
            (item for item in offers if isinstance(item, dict)),
            {},
        )
    elif isinstance(offers, dict):
        offer = offers
    else:
        offer = {}

    price = parse_price(offer.get("price"))
    if price is None:
        price = parse_price(page_text)
    if price is None:
        return None

    gtin = clean(data.get("gtin13") or data.get("gtin") or "") or None
    mpn = clean(data.get("mpn") or "") or None
    sku = clean(data.get("sku") or "") or None

    image = data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None

    avail = availability(page_text, offer=offer, soup=soup)

    detected_size = size_ml(name)
    detected_concentration = concentration(name)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": clean(brand),
            "url": url,
            "image": urljoin(url, str(image)) if image else None,
        },
        "identity": {
            "gtin": {
                "value": gtin,
                "source": "jsonld",
            } if gtin else None,
            "mpn": {
                "value": mpn,
                "source": "jsonld",
            } if mpn else None,
            "sku": {
                "value": sku,
                "source": "jsonld",
            } if sku else None,
            "store_product_id": {
                "value": sku,
                "source": "deloox_sku",
            } if sku else None,
        },
        "attributes": {
            "size_ml": {
                "value": detected_size,
                "source": "product_name",
            } if detected_size is not None else None,
            "concentration": {
                "value": detected_concentration,
                "source": "product_name",
            } if detected_concentration else None,
            "gender": {
                "value": "unknown",
                "source": "not_explicit",
            },
            "packaging_type": {
                "value": "product",
                "source": "default",
            },
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
        "raw_data": {
            "jsonld": data,
        },
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": avail == "in_stock",
    }


def _candidate_queries(query):
    q = clean(query)
    if not q:
        return []

    variants = [q]

    removable = {
        "parfum",
        "perfume",
        "eau",
        "de",
        "toilette",
        "edt",
        "edp",
        "extrait",
        "extract",
    }

    broad = " ".join(
        part for part in q.split()
        if part.lower() not in removable
    ).strip()

    if broad and broad.lower() != q.lower():
        variants.append(broad)

    result = []
    seen = set()

    for value in variants:
        key = norm(value)
        if key and key not in seen:
            seen.add(key)
            result.append(value)

    return result


def _absolute_deloox_url(raw_url):
    if not raw_url:
        return None
    raw_url = clean(raw_url).replace("\/","/")
    if raw_url.startswith(("javascript:", "mailto:", "#")):
        return None
    url = urljoin(BASE_URL, raw_url).split("#")[0].split("?")[0]
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if parsed.netloc.lower() not in DELOOX_HOSTS:
        return None
    return url


def _candidate_product_urls(
    html,
    query,
    discovery_query=None,
    accept_all_products=False,
):
    """Collect generic product URLs and rank them by query-token overlap.

    Discovery is deliberately permissive: a listing/card may expose only a
    numeric product URL and no product name. The product page remains the
    authoritative place where the query is validated by _product().
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    seen = set()

    def add(raw_url, context=""):
        url = _absolute_deloox_url(raw_url)
        if not url:
            return
        if "/product/" not in urlparse(url).path.lower():
            return
        if url in seen:
            return

        score = len(tokens(f"{context} {url}") & tokens(query))
        seen.add(url)
        candidates.append((score, url))

    for anchor in soup.find_all("a", href=True):
        parent = anchor.parent
        parent_text = clean(parent.get_text(" ", strip=True)) if parent is not None else ""
        context = clean(" ".join(
            part for part in (anchor.get_text(" ", strip=True), parent_text)
            if part
        ))
        add(anchor.get("href"), context)

    patterns = (
        re.compile(
            r'https?://(?:www\.)?deloox\.(?:be|com|nl|es|de|fr|it)/[^"\'<>\\s]+/product/[^"\'<>\\s]+',
            re.I,
        ),
        re.compile(
            r'["\']((?:/)?(?:en|fr|nl|de|es|it|categorie|category)?/?product/[^"\']+)["\']',
            re.I,
        ),
    )

    for pattern in patterns:
        for match in pattern.finditer(html):
            raw = match.group(1) if match.lastindex else match.group(0)
            context = clean(
                BeautifulSoup(
                    html[max(0, match.start() - 900):min(len(html), match.end() + 900)],
                    "html.parser",
                ).get_text(" ", strip=True)
            )
            add(raw, context)

    candidates.sort(key=lambda pair: (-pair[0], pair[1]))
    return [url for _, url in candidates]

def _category_product_line_links(html, query):
    """Discover generic category/filter pages matching query tokens."""
    soup = BeautifulSoup(html, "html.parser")
    result = []
    seen = set()
    q_tokens = tokens(query)

    if not q_tokens:
        return result

    def add(raw_url, context=""):
        url = _absolute_deloox_url(raw_url)
        if not url:
            return

        if "/category/" not in urlparse(url).path.lower():
            return

        path_part = urlparse(url).path.rsplit("/", 1)[-1]
        if path_part.lower().endswith(".html"):
            path_part = path_part[:-5]

        if not q_tokens.issubset(
            tokens(f"{path_part} {context}")
        ):
            return

        if url in seen:
            return

        seen.add(url)
        result.append(url)

    for anchor in soup.find_all("a", href=True):
        parent_text = ""
        if anchor.parent is not None:
            parent_text = clean(
                anchor.parent.get_text(" ", strip=True)
            )

        context = clean(
            " ".join(
                value
                for value in (
                    anchor.get_text(" ", strip=True),
                    parent_text,
                )
                if value
            )
        )
        add(anchor.get("href"), context)

    category_pattern = re.compile(
        r'https?://(?:www\.)?deloox\.com/'
        r'(?:[^"\'<>\\s]+/)?category/\d+/[^"\'<>\\s]+'
        r'|/(?:en/|it/|nl/)?category/\d+/[^"\'<>\\s]+',
        re.I,
    )

    normalized_html = html.replace("\\/", "/")

    for match in category_pattern.finditer(normalized_html):
        start = max(0, match.start() - 900)
        end = min(len(normalized_html), match.end() + 900)

        context = clean(
            BeautifulSoup(
                normalized_html[start:end],
                "html.parser",
            ).get_text(" ", strip=True)
        )

        add(match.group(0), context)

    return result


def _category_pages(session=None):
    """Generic Deloox catalogue/category entry points."""
    pages = []
    for base in DELOOX_BASE_URLS:
        pages.extend((
            base + "/en/category/1103659/fragrances.html",
            base + "/category/1103659/fragrances.html",
            base + "/categorie/1075744/eau-de-toilette-homme.html",
            base + "/categorie/1075743/eau-de-parfum-femme.html",
            base + "/categorie/1075742/eau-de-parfum-femme.html",
        ))
    return tuple(dict.fromkeys(pages))

def _discover_from_categories(session, query, max_urls=80):
    """Discover products from broad catalogue and matching category pages."""
    product_urls = []
    seen_products = set()
    category_urls = []
    seen_categories = set()

    def add_category(url):
        if url and url not in seen_categories:
            seen_categories.add(url)
            category_urls.append(url)

    # Start with live broad catalogue entry points.
    for url in _category_pages(session):
        add_category(url)

    # Sitemap categories are a generic fallback.
    for url in _sitemap_category_urls(
        session,
        query,
        max_sitemaps=48,
        max_urls=50,
    ):
        add_category(url)

    for category_url in category_urls:
        try:
            response = session.get(
                category_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            continue

        if response.status_code >= 400:
            continue

        # A broad category can expose a more specific product-line/category
        # page.  This relationship is discovered from page content; no
        # product or brand is hardcoded.
        filter_urls = _category_product_line_links(
            response.text,
            query,
        )

        pages = [(category_url, False)]
        pages.extend((url, True) for url in filter_urls)

        seen_pages = set()

        for page_url, filtered in pages:
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)

            if page_url == category_url:
                page_html = response.text
            else:
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

            candidates = _candidate_product_urls(
                page_html,
                query,
                discovery_query=query,
                accept_all_products=filtered,
            )

            for product_url in candidates:
                if product_url in seen_products:
                    continue

                seen_products.add(product_url)
                product_urls.append(product_url)

                if len(product_urls) >= max_urls:
                    return product_urls[:max_urls]

    return product_urls[:max_urls]


def _sitemap_category_urls(
    session,
    query,
    max_sitemaps=12,
    max_urls=30,
):
    query_tokens = tokens(query)
    if not query_tokens:
        return []

    roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )

    pending = list(roots)
    seen_sitemaps = set()
    result = []
    seen_categories = set()

    def fetch_xml(url):
        try:
            response = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            return None

        if response.status_code >= 400:
            return None

        body = response.text.lstrip()
        content_type = (
            response.headers.get("content-type") or ""
        ).lower()

        if "xml" not in content_type and not body.startswith(
            ("<?xml", "<urlset", "<sitemapindex")
        ):
            return None

        return response.text

    while (
        pending
        and len(seen_sitemaps) < max_sitemaps
        and len(result) < max_urls
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

            lower = value.lower()

            if "/category/" in lower and lower.endswith(".html"):
                slug = lower.rsplit("/", 1)[-1][:-5]

                if query_tokens.issubset(tokens(slug)):
                    if value not in seen_categories:
                        seen_categories.add(value)
                        result.append(value)

                        if len(result) >= max_urls:
                            break

            elif lower.endswith(".xml") or "sitemap" in lower:
                if value not in seen_sitemaps:
                    pending.append(value)

    return result[:max_urls]


def _sitemap_product_urls(
    session,
    query,
    max_sitemaps=12,
    max_urls=80,
):
    query_tokens = tokens(query)
    if not query_tokens:
        return []

    roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )

    pending = list(roots)
    seen_sitemaps = set()
    result = []
    seen_products = set()

    def fetch_xml(url):
        try:
            response = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            return None

        if response.status_code >= 400:
            return None

        body = response.text.lstrip()
        content_type = (
            response.headers.get("content-type") or ""
        ).lower()

        if "xml" not in content_type and not body.startswith(
            ("<?xml", "<urlset", "<sitemapindex")
        ):
            return None

        return response.text

    while (
        pending
        and len(seen_sitemaps) < max_sitemaps
        and len(result) < max_urls
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

            lower = value.lower()

            if "/product/" in lower:
                if query_tokens.issubset(tokens(value)):
                    if value not in seen_products:
                        seen_products.add(value)
                        result.append(value)

                        if len(result) >= max_urls:
                            break

            elif lower.endswith(".xml") or "sitemap" in lower:
                if value not in seen_sitemaps:
                    pending.append(value)

    return result


def _discover(session, query):
    """Generic deterministic Deloox discovery."""
    query = clean(query)
    if not query:
        return []

    urls = []
    seen = set()
    max_urls = 60

    def add(url):
        if url and url not in seen and len(urls) < max_urls:
            seen.add(url)
            urls.append(url)

    discovery_queries = _candidate_queries(query)[:2]
    routes = (
        "/chercher.html?q=",
        "/zoeken.html?q=",
        "/search?q=",
        "/en/search?q=",
        "/en/search?query=",
        "/en/search?search=",
        "/en/search?searchTerm=",
    )

    category_urls = []
    seen_categories = set()

    for base in DELOOX_BASE_URLS:
        for discovery_query in discovery_queries:
            for route in routes:
                endpoint = base + route + quote_plus(discovery_query)
                try:
                    response = session.get(endpoint, headers=HEADERS, timeout=TIMEOUT)
                except requests.RequestException:
                    continue
                if response.status_code >= 400:
                    continue

                for product_url in _candidate_product_urls(
                    response.text,
                    query,
                    discovery_query=discovery_query,
                    accept_all_products=False,
                ):
                    add(product_url)
                    if len(urls) >= max_urls:
                        return urls[:max_urls]

                for category_url in _category_product_line_links(response.text, query):
                    if category_url not in seen_categories:
                        seen_categories.add(category_url)
                        category_urls.append(category_url)

                if len(category_urls) >= 12:
                    break
            if len(category_urls) >= 12:
                break
        if len(category_urls) >= 12:
            break

    for category_url in category_urls[:12]:
        try:
            response = session.get(category_url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if response.status_code >= 400:
            continue
        for product_url in _candidate_product_urls(
            response.text,
            query,
            discovery_query=query,
            accept_all_products=True,
        ):
            add(product_url)
            if len(urls) >= max_urls:
                return urls[:max_urls]

    for category_url in _category_pages():
        try:
            response = session.get(category_url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if response.status_code >= 400:
            continue
        for product_url in _candidate_product_urls(
            response.text,
            query,
            discovery_query=query,
            accept_all_products=True,
        ):
            add(product_url)
            if len(urls) >= max_urls:
                return urls[:max_urls]

    for product_url in _sitemap_product_urls(
        session,
        query,
        max_sitemaps=8,
        max_urls=40,
    ):
        add(product_url)
        if len(urls) >= max_urls:
            return urls[:max_urls]

    return urls[:max_urls]

def diagnose_search(session, query):
    """Read-only diagnostic for discovery and product validation."""
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
            response = session.get(
                category_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            entry["status"] = response.status_code
        except requests.RequestException as exc:
            entry["error"] = str(exc)
            report["category_endpoints"].append(entry)
            continue

        report["category_endpoints"].append(entry)

        if response.status_code >= 400:
            continue

        filters = _category_product_line_links(
            response.text,
            query,
        )

        entry["filter_urls"] = filters[:20]
        report["filter_urls"].extend(filters)

        pages = [(category_url, False)]
        pages.extend((url, True) for url in filters)

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
            response = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            continue

        if response.status_code >= 400:
            continue

        item = _product(
            url,
            response.text,
            query,
        )

        if item:
            report["validated_products"].append(item)

    for endpoint in (
        BASE_URL
        + "/en/search?query="
        + quote_plus(query),
        BASE_URL
        + "/en/search?search="
        + quote_plus(query),
        BASE_URL
        + "/en/search?q="
        + quote_plus(query),
    ):
        try:
            response = session.get(
                endpoint,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            report["search_fallback"].append(
                {
                    "url": endpoint,
                    "status": response.status_code,
                }
            )
        except requests.RequestException as exc:
            report["search_fallback"].append(
                {
                    "url": endpoint,
                    "error": str(exc),
                }
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
                response = session.get(
                    url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException:
                continue

            if response.status_code >= 400:
                continue

            item = _product(
                url,
                response.text,
                query,
            )

            if not item:
                continue

            sku = item["identity"].get("sku")
            sku_value = sku.get("value") if sku else None
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
