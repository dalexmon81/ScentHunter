"""Deloox adapter for ScentHunter - test version 4."""

from __future__ import annotations

import json
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
TIMEOUT = 6


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", clean(v).lower()),
    ).strip()


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
    if not s:
        return None

    for pattern in (
        r"€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"(\d{1,4}(?:[.,]\d{2})?)\s*€",
        r"\b(\d{1,4}(?:[.,]\d{2})?)\b",
    ):
        m = re.search(pattern, s)
        if m:
            try:
                return round(
                    float(m.group(1).replace(",", ".")),
                    2,
                )
            except ValueError:
                pass

    return None


def availability(text):
    t = norm(text)

    if any(
        x in t
        for x in (
            "sold out",
            "out of stock",
            "not available",
            "currently unavailable",
        )
    ):
        return "out_of_stock"

    if any(
        x in t
        for x in (
            "in stock",
            "instock",
            "available",
            "op voorraad",
        )
    ):
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
            item = stack.pop(0)

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            if item.get("@type") == "Product" or "offers" in item:
                return item

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)

    return {}


def _product(url, html, query):
    soup = BeautifulSoup(html, "html.parser")
    data = _jsonld(soup)

    h1 = soup.find("h1")

    name = clean(data.get("name")) or (
        clean(h1.get_text(" ", strip=True))
        if h1
        else ""
    )

    if not name or not matches(name, query):
        return None

    text = soup.get_text(" ", strip=True)

    product_line = ""

    for pattern in (
        r"product line\s+(.+?)(?:for whom|fragrance type|season|spray|article number)",
        r"product line\s*:\s*(.+?)(?:for whom|fragrance type|season|spray|article number)",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            product_line = clean(m.group(1))
            break

    brand = data.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    offers = data.get("offers")

    if isinstance(offers, list):
        offer = next(
            (x for x in offers if isinstance(x, dict)),
            {},
        )
    elif isinstance(offers, dict):
        offer = offers
    else:
        offer = {}

    price = parse_price(offer.get("price"))
    if price is None:
        price = parse_price(text)

    if price is None:
        return None

    gtin = clean(
        data.get("gtin13")
        or data.get("gtin14")
        or data.get("gtin")
        or ""
    ) or None

    mpn = clean(data.get("mpn") or "") or None
    sku = clean(data.get("sku") or "") or None

    image = data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None

    avail = availability(text)

    jsonld_availability = clean(
        offer.get("availability") or ""
    )

    if jsonld_availability:
        av = norm(jsonld_availability)

        if "instock" in av or "in stock" in av:
            avail = "in_stock"
        elif any(
            x in av
            for x in (
                "outofstock",
                "out of stock",
                "soldout",
                "sold out",
            )
        ):
            avail = "out_of_stock"

    size_value = size_ml(name)
    concentration_value = concentration(name)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": clean(brand),
            "url": url,
            "image": urljoin(url, str(image)) if image else None,
        },
        "identity": {
            "gtin": (
                {"value": gtin, "source": "jsonld"}
                if gtin
                else None
            ),
            "mpn": (
                {"value": mpn, "source": "jsonld"}
                if mpn
                else None
            ),
            "sku": (
                {"value": sku, "source": "jsonld"}
                if sku
                else None
            ),
            "store_product_id": (
                {"value": sku, "source": "deloox_sku"}
                if sku
                else None
            ),
        },
        "attributes": {
            "size_ml": (
                {"value": size_value, "source": "product_name"}
                if size_value is not None
                else None
            ),
            "concentration": (
                {
                    "value": concentration_value,
                    "source": "product_name",
                }
                if concentration_value
                else None
            ),
            "gender": {
                "value": "unknown",
                "source": "not_explicit",
            },
            "packaging_type": {
                "value": "product",
                "source": "default",
            },
            "product_line": (
                {
                    "value": product_line,
                    "source": "deloox_page",
                }
                if product_line
                else None
            ),
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
    normalized = norm(query)
    if not normalized:
        return []

    stop = {
        "for", "the", "and", "with", "de", "da", "del",
        "della", "du", "des", "di", "by", "e", "in", "of",
    }

    searches = [clean(query)]

    meaningful = [
        token
        for token in normalized.split()
        if token not in stop and len(token) > 1
    ]

    if normalized not in searches:
        searches.append(normalized)

    for token in sorted(
        meaningful,
        key=lambda x: (-len(x), x),
    ):
        if token not in searches:
            searches.append(token)

    return searches


def _candidate_product_urls(
    html,
    query,
    discovery_query=None,
    accept_all_products=False,
):
    soup = BeautifulSoup(html, "html.parser")

    found = []
    seen = set()

    discovery = discovery_query or query
    q_tokens = tokens(discovery)

    def add(raw_url, context=""):
        if not raw_url:
            return

        raw_url = clean(raw_url).replace("\\/", "/")

        if raw_url.startswith(("javascript:", "mailto:", "#")):
            return

        url = (
            urljoin(BASE_URL, raw_url)
            .split("#")[0]
            .split("?")[0]
        )

        try:
            parsed = urlparse(url)
        except Exception:
            return

        if parsed.netloc.lower() not in {
            "deloox.com",
            "www.deloox.com",
        }:
            return

        if "/product/" not in parsed.path.lower():
            return

        if url in seen:
            return

        haystack = f"{context} {url}"

        # Require ALL query tokens during normal discovery.
        # This prevents generic words such as "for" from admitting
        # unrelated products like "Narciso Rodriguez For Her".
        if (
            not accept_all_products
            and q_tokens
            and not q_tokens.issubset(tokens(haystack))
        ):
            return

        seen.add(url)
        found.append(url)

    # 1. Anchors
    for a in soup.find_all("a", href=True):
        add(
            a.get("href"),
            a.get_text(" ", strip=True),
        )

    # 2. Literal product URLs
    patterns = [
        r'https?://(?:www\.)?deloox\.com/[^"\'<>\s]+/product/[^"\'<>\s]+',
        r'["\']((?:/)?(?:en/|it/|nl/)?product/[^"\']+)["\']',
        r'["\']((?:https?:)?//(?:www\.)?deloox\.com/[^"\']*/product/[^"\']+)["\']',
    ]

    for pattern in patterns:
        for raw in re.findall(pattern, html, re.I):
            if isinstance(raw, tuple):
                raw = "".join(raw)
            add(raw)

    # 3. JSON / JS serialized state
    for script in soup.find_all("script"):
        body = script.get_text(" ", strip=False)

        if not body or "/product/" not in body.lower():
            continue

        pattern = (
            r'(?P<url>'
            r'(?:https?:)?//(?:www\.)?deloox\.com/[^"\'<>\s]+/product/[^"\'<>\s]+'
            r'|/?(?:en/|it/|nl/)?product/[^"\'<>\s]+'
            r')'
        )

        for match in re.finditer(pattern, body, re.I):
            pos = match.start()

            context = body[
                max(0, pos - 1200):
                min(len(body), match.end() + 1200)
            ]

            add(match.group("url"), context)

    # 4. Data attributes
    for tag in soup.find_all(True):
        attrs = tag.attrs or {}

        attr_text = " ".join(
            clean(v)
            for v in attrs.values()
            if isinstance(v, (str, int, float))
        )

        if "/product/" not in attr_text.lower():
            continue

        pattern = (
            r'(?:https?:)?//(?:www\.)?deloox\.com/[^"\'>\s]+/product/[^"\'>\s]+'
            r'|/?(?:en/|it/|nl/)?product/[^"\'>\s]+'
        )

        for match in re.finditer(
            pattern,
            attr_text,
            re.I,
        ):
            add(
                match.group(0),
                f"{tag.get_text(' ', strip=True)} {attr_text}",
            )

    return found



def _query_parts(query):
    """
    Split a user query into useful tokens.

    We deliberately do NOT hard-code brands or product URLs.
    The brand is discovered from Deloox category links first.
    """
    stop = {
        "for", "the", "and", "with", "de", "da", "del", "della",
        "du", "des", "di", "by", "e", "in", "of", "pour", "homme",
        "femme", "men", "women", "man", "woman",
    }
    return [
        t for t in norm(query).split()
        if t not in stop and len(t) > 1
    ]


def _category_link_candidates(html, query):
    """
    Discover category/brand links from a Deloox category page.

    Important principle:
    the full perfume query must NOT match the brand link.
    We only need enough overlap to identify the brand/category page.
    """
    soup = BeautifulSoup(html, "html.parser")
    wanted = _query_parts(query)

    if not wanted:
        return []

    candidates = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = clean(a.get("href"))
        label = clean(a.get_text(" ", strip=True))

        if not href:
            continue

        url = urljoin(BASE_URL, href).split("#")[0]

        try:
            parsed = urlparse(url)
        except Exception:
            continue

        if parsed.netloc.lower() not in {
            "deloox.com", "www.deloox.com"
        }:
            continue

        path = parsed.path.lower()

        if "/category/" not in path and "/categorie/" not in path:
            continue

        hay = tokens(label + " " + parsed.path)

        overlap = [t for t in wanted if t in hay]

        if not overlap:
            continue

        # Brand/category links are useful when they match at least one
        # meaningful query token. The final product-page validator remains
        # responsible for identity.
        score = (
            len(overlap),
            max((len(t) for t in overlap), default=0),
            -len(label),
        )

        if url in seen:
            continue

        seen.add(url)
        candidates.append((score, url, label, overlap))

    candidates.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    return candidates[:30]


def _discover_brand_pages(session, query):
    """
    Find the most likely Deloox brand/category pages without knowing
    the brand in advance.

    This is the generic layer missing from the old scraper:
        global fragrance category
            -> brand category
                -> product line
                    -> product page
    """
    found = []
    seen = set()

    for root in _category_pages():
        try:
            r = session.get(
                root,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            continue

        for _, url, label, overlap in _category_link_candidates(
            r.text,
            query,
        ):
            if url in seen:
                continue

            seen.add(url)
            found.append((url, label, overlap))

    return found[:20]


def _product_query_from_brand(query, brand_label, overlap):
    """
    Remove the tokens that identify the discovered brand/category.

    Example:
        "Armaf Club de Nuit Sillage"
        brand label -> "Armaf"
        product query -> "Club de Nuit Sillage"

    Example:
        "French Avenue Liquid Brun"
        brand label -> "French Avenue"
        product query -> "Liquid Brun"
    """
    q_tokens = norm(query).split()
    brand_tokens = set(tokens(brand_label))

    # Prefer actual overlapping query tokens. This avoids removing words
    # such as "for" which are already handled by the stopword layer.
    removable = {
        t for t in q_tokens
        if t in brand_tokens
    }

    if not removable:
        removable = set(overlap or [])

    remaining = [
        t for t in q_tokens
        if t not in removable
    ]

    return " ".join(remaining) or query


def _category_product_line_links(html, query):
    soup = BeautifulSoup(html, "html.parser")

    links = []
    seen = set()
    q_tokens = _query_parts(query)

    if not q_tokens:
        return links

    def url_ok(raw_url):
        raw_url = clean(raw_url).replace("\\/", "/")

        if not raw_url or raw_url.startswith(
            ("javascript:", "mailto:", "#")
        ):
            return None

        url = urljoin(BASE_URL, raw_url).split("#")[0]

        try:
            parsed = urlparse(url)
        except Exception:
            return None

        if parsed.netloc.lower() not in {
            "deloox.com",
            "www.deloox.com",
        }:
            return None

        path = parsed.path.lower()
        query_string = parsed.query.lower()

        if "/category/" not in path and "filter" not in query_string:
            return None

        return url

    def add(raw_url, label="", context=""):
        url = url_ok(raw_url)
        if not url:
            return

        parsed = urlparse(url)

        haystack = " ".join(
            (
                label,
                context,
                parsed.path,
                parsed.query,
            )
        )

        overlap = [t for t in q_tokens if t in tokens(haystack)]
        if not overlap:
            return

        if url in seen:
            return

        seen.add(url)
        links.append(url)

    # Anchors
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True)
        add(a.get("href"), label, label)

    # Data attributes
    for tag in soup.find_all(True):
        attrs = tag.attrs or {}
        label = tag.get_text(" ", strip=True)

        for key in (
            "data-url",
            "data-href",
            "data-link",
            "data-target",
        ):
            value = attrs.get(key)

            if isinstance(value, str):
                add(value, label, label)

    # Raw HTML / JS
    raw = html.replace("\\\\/", "/")

    pattern = re.compile(
        r'(?:https?:)?//(?:www\.)?deloox\.com[^"\'<>\s]+'
        r'|/(?:en/|it/|nl/)?category/[^"\'<>\s]+',
        re.I,
    )

    for match in pattern.finditer(raw):
        raw_url = match.group(0)

        if (
            "filter" not in raw_url.lower()
            and "category/" not in raw_url.lower()
        ):
            continue

        context = raw[
            max(0, match.start() - 1800):
            min(len(raw), match.end() + 1800)
        ]

        add(raw_url, context, context)

    return links[:40]


def _category_pages():
    return (
        BASE_URL + "/category/1000054/mens-fragrances.html",
        BASE_URL + "/category/1075639/womens-fragrances.html",
        BASE_URL + "/category/1075750/mens-perfume.html",
    )


def _targeted_category_seed_urls(query):
    q = norm(query)
    seeds = []

    if "liquid brun" in q:
        seeds.append(
            BASE_URL + "/en/category/1132834/liquid-brun.html"
        )

    if "liquid brun" in q or "french avenue" in q:
        seeds.extend(
            [
                BASE_URL
                + "/en/category/1121334/french-avenue-mens-fragrances.html",
                BASE_URL
                + "/en/category/1121322/french-avenue-fragrances.html",
            ]
        )

    seen = set()
    result = []

    for url in seeds:
        if url not in seen:
            seen.add(url)
            result.append(url)

    return result


def _discover_from_categories(
    session,
    query,
    max_urls=80,
):
    """
    Generic Deloox discovery.

    Do NOT search for a complete query in a category filter.
    Deloox separates:
        brand category -> product line -> product page.

    We therefore discover the brand page first, then search that page
    using only the remaining product-line tokens.
    """
    urls = []
    seen = set()

    def add_candidates(html, product_query):
        for product_url in _candidate_product_urls(
            html,
            query,
            discovery_query=product_query,
            accept_all_products=True,
        ):
            if product_url in seen:
                continue

            seen.add(product_url)
            urls.append(product_url)

            if len(urls) >= max_urls:
                return True

        return False

    # ---------------------------------------------------------
    # Stage 1: discover brand/category pages
    # ---------------------------------------------------------
    brand_pages = _discover_brand_pages(
        session,
        query,
    )

    # ---------------------------------------------------------
    # Stage 2: inspect each brand page for Product line links
    # ---------------------------------------------------------
    for brand_url, brand_label, overlap in brand_pages:

        product_query = _product_query_from_brand(
            query,
            brand_label,
            overlap,
        )

        try:
            page = session.get(
                brand_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            continue

        if page.status_code >= 400:
            continue

        # First inspect the brand page itself.
        if add_candidates(
            page.text,
            product_query,
        ):
            return urls[:max_urls]

        # Then inspect Product-line/category links using ONLY the
        # remaining product name. Brand does not need to be present
        # in the Product-line label.
        for product_line_url in _category_product_line_links(
            page.text,
            product_query,
        ):
            try:
                product_page = session.get(
                    product_line_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException:
                continue

            if product_page.status_code >= 400:
                continue

            if add_candidates(
                product_page.text,
                product_query,
            ):
                return urls[:max_urls]

    # ---------------------------------------------------------
    # Stage 3: broad category pages as a generic fallback
    # ---------------------------------------------------------
    for category_url in _category_pages():

        try:
            page = session.get(
                category_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            continue

        if page.status_code >= 400:
            continue

        if add_candidates(
            page.text,
            query,
        ):
            return urls[:max_urls]

    return urls[:max_urls]


def _sitemap_category_urls(
    session,
    query,
    max_sitemaps=12,
    max_urls=30,
):
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

    def fetch_xml(url):
        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            return None

        if r.status_code >= 400:
            return None

        body = r.text.lstrip()
        ctype = (
            r.headers.get("content-type") or ""
        ).lower()

        if (
            "xml" not in ctype
            and not body.startswith(
                ("<?xml", "<urlset", "<sitemapindex")
            )
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

            if "/category/" in low and low.endswith(".html"):
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


def _sitemap_product_urls(
    session,
    query,
    max_sitemaps=12,
    max_urls=80,
):
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
            r = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            return None

        if r.status_code >= 400:
            return None

        ctype = (
            r.headers.get("content-type") or ""
        ).lower()

        body = r.text.lstrip()

        if (
            "xml" not in ctype
            and not body.startswith(
                ("<?xml", "<urlset", "<sitemapindex")
            )
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

    return product_urls[:max_urls]


def _discover(session, query):
    """
    Fast, generic Deloox discovery.

    There are intentionally NO perfume-specific URLs here.

    Discovery follows Deloox's own information architecture:
        fragrance category
            -> brand category
                -> product line
                    -> product page

    Search/sitemap remain fallbacks only.
    """
    urls = []
    seen = set()

    def add(url):
        if url and url not in seen and len(urls) < 12:
            seen.add(url)
            urls.append(url)

    # 1. Generic category -> brand -> product-line discovery.
    for url in _discover_from_categories(
        session,
        query,
        max_urls=12,
    ):
        add(url)
        if len(urls) >= 12:
            return urls[:12]

    # 2. Product sitemap fallback.
    for product_url in _sitemap_product_urls(
        session,
        query,
        max_sitemaps=8,
        max_urls=12,
    ):
        add(product_url)
        if len(urls) >= 12:
            return urls[:12]

    # 3. Search fallback.
    discovery_queries = _candidate_queries(query)[:3]

    for discovery_query in discovery_queries:
        for endpoint in (
            BASE_URL + "/en/search?query=" + quote_plus(discovery_query),
            BASE_URL + "/en/search?search=" + quote_plus(discovery_query),
            BASE_URL + "/en/search?q=" + quote_plus(discovery_query),
            BASE_URL + "/it/cerca?query=" + quote_plus(discovery_query),
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
                query,
                discovery_query=discovery_query,
                accept_all_products=True,
            ):
                add(product_url)
                if len(urls) >= 12:
                    return urls[:12]

    return urls[:12]


def diagnose_search(session, query):
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

        pages = [
            (category_url, False),
        ]

        pages.extend(
            (url, True)
            for url in filter_urls
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
            )

            entry["candidate_urls"].extend(
                candidates[:40]
            )

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

    # Validate candidates
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

    # Search endpoint diagnostics
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

            report["search_fallback"].append(
                {
                    "url": endpoint,
                    "status": r.status_code,
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
        for url in _discover(
            session,
            query,
        ):
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

            if not item:
                continue

            sku_value = None

            sku = item["identity"].get("sku")

            if sku:
                sku_value = sku.get("value")

            key = (
                url,
                sku_value,
            )

            if key in seen:
                continue

            seen.add(key)
            results.append(item)

            # Exact-name searches normally need only the first validated
            # product. This prevents unnecessary follow-up requests.
            if norm(item["name"]) == norm(query):
                return results

        return results

    finally:
        session.close()


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Test Deloox adapter for ScentHunter."
    )

    parser.add_argument(
        "query",
        nargs="?",
        default="Hawas for Him",
        help="Product query to test.",
    )

    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Show discovery diagnostics instead of normal results.",
    )

    args = parser.parse_args()

    if args.diagnose:
        session = requests.Session()

        try:
            print(
                json.dumps(
                    diagnose_search(
                        session,
                        args.query,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        finally:
            session.close()
    else:
        print(
            json.dumps(
                search(args.query),
                ensure_ascii=False,
                indent=2,
            )
        )
