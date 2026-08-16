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
BASE_URL = "https://www.deloox.com"
TIMEOUT = 4

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

    m = re.search(
        r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?",
        s,
    )

    if not m:
        return None

    try:
        return round(
            float(m.group(1).replace(",", ".")),
            2,
        )
    except ValueError:
        return None


def availability(text, offer=None, soup=None):
    """Determine availability from product-specific signals only."""

    # 1. JSON-LD / structured data.
    if isinstance(offer, dict):
        raw = clean(
            offer.get("availability")
            or offer.get("itemAvailability")
            or offer.get("availabilityStatus")
            or ""
        ).lower()

        if raw:
            if any(
                x in raw
                for x in (
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
                x in raw
                for x in (
                    "instock",
                    "in_stock",
                    "limitedavailability",
                    "preorder",
                    "pre_order",
                )
            ):
                return "in_stock"

    # 2. Product-specific page elements.
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

        scoped = norm(
            " ".join(
                x for x in scoped_parts
                if x
            )
        )

        if scoped:
            if any(
                x in scoped
                for x in (
                    "sold out",
                    "out of stock",
                    "not available",
                    "currently unavailable",
                    "unavailable",
                )
            ):
                return "out_of_stock"

            if any(
                x in scoped
                for x in (
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

    # 3. Conservative page-text fallback.
    t = norm(text)

    if any(
        x in t
        for x in (
            "sold out",
            "out of stock",
            "currently unavailable",
        )
    ):
        return "out_of_stock"

    if any(
        x in t
        for x in (
            "in stock",
            "op voorraad",
        )
    ):
        return "in_stock"

    return "unknown"


def _jsonld(soup):
    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            data = json.loads(
                script.get_text(strip=True)
            )
        except Exception:
            continue

        stack = (
            data
            if isinstance(data, list)
            else [data]
        )

        while stack:
            x = stack.pop(0)

            if isinstance(x, list):
                stack.extend(x)
                continue

            if not isinstance(x, dict):
                continue

            if (
                x.get("@type") == "Product"
                or "offers" in x
            ):
                return x

            if isinstance(
                x.get("@graph"),
                list,
            ):
                stack.extend(
                    x["@graph"]
                )

    return {}


def _product(url, html, query):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    data = _jsonld(soup)

    h1 = soup.find("h1")

    name = clean(
        data.get("name")
    ) or (
        clean(
            h1.get_text(
                " ",
                strip=True,
            )
        )
        if h1
        else ""
    )

    # Primary validation is against the real product name.
    # Deloox sometimes omits gender words such as "for Him" from
    # the structured product name even though they are present in
    # the canonical product URL discovered by the scraper.
    # Keep the name match authoritative when it succeeds, but allow
    # the discovered product URL to complete the match when the URL
    # itself contains all query tokens.
    if not name:
        return None

    if not (
        matches(name, query)
        or matches(url, query)
    ):
        return None

    product_line = ""

    text = soup.get_text(
        " ",
        strip=True,
    )

    m = re.search(
        r"product line\s+(.+?)(?:for whom|fragrance type|season|spray|article number)",
        text,
        re.I,
    )

    if m:
        product_line = clean(
            m.group(1)
        )

    brand = data.get("brand")

    if isinstance(
        brand,
        dict,
    ):
        brand = brand.get("name")

    offers = data.get("offers")

    if isinstance(
        offers,
        list,
    ):
        offer_list = offers
    else:
        offer_list = [offers]

    offer = next(
        (
            x
            for x in offer_list
            if isinstance(x, dict)
        ),
        {},
    )

    price = parse_price(
        offer.get("price")
    )

    if price is None:
        price = parse_price(text)

    if price is None:
        return None

    gtin = clean(
        data.get("gtin13")
        or data.get("gtin")
        or ""
    ) or None

    mpn = clean(
        data.get("mpn")
        or ""
    ) or None

    sku = clean(
        data.get("sku")
        or ""
    ) or None

    image = data.get("image")

    if isinstance(
        image,
        list,
    ):
        image = (
            image[0]
            if image
            else None
        )

    avail = availability(
        text,
        offer=offer,
        soup=soup,
    )

    return {
        "store": STORE,

        "source": {
            "source_name": name,
            "source_brand": clean(brand),
            "url": url,
            "image": (
                urljoin(
                    url,
                    str(image),
                )
                if image
                else None
            ),
        },

        "identity": {
            "gtin": (
                {
                    "value": gtin,
                    "source": "jsonld",
                }
                if gtin
                else None
            ),

            "mpn": (
                {
                    "value": mpn,
                    "source": "jsonld",
                }
                if mpn
                else None
            ),

            "sku": (
                {
                    "value": sku,
                    "source": "jsonld",
                }
                if sku
                else None
            ),

            "store_product_id": (
                {
                    "value": sku,
                    "source": "deloox_sku",
                }
                if sku
                else None
            ),
        },

        "attributes": {
            "size_ml": (
                {
                    "value": size_ml(name),
                    "source": "product_name",
                }
                if size_ml(name) is not None
                else None
            ),

            "concentration": (
                {
                    "value": concentration(name),
                    "source": "product_name",
                }
                if concentration(name)
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

        "raw_data": {
            "jsonld": data,
        },

        "name": name,

        "price": (
            f"{price:.2f}".replace(
                ".",
                ",",
            )
            + " €"
        ),

        "url": url,

        "available": (
            avail == "in_stock"
        ),
    }


def _candidate_queries(query):
    """Build robust Deloox discovery queries.

    Deloox search is not consistent for branded products: for example,
    "Hawas for Him" may return nothing while "Hawas" or "Rasasi Hawas"
    exposes the product pages.  Keep the original query first so final
    validation remains authoritative, but add conservative aliases.
    """

    q = clean(query)

    if not q:
        return []

    variants = [q]

    parts = q.split()

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
        p
        for p in parts
        if p.lower() not in removable
    ).strip()

    if broad and broad.lower() != q.lower():
        variants.append(broad)

    nq = norm(q)

    # Deloox-specific aliases for the Rasasi Hawas family.
    # These are discovery-only aliases: _product() still validates
    # against the user's original query.
    if "hawas" in nq:
        variants.extend(
            [
                "Hawas",
                "Rasasi Hawas",
                "Rasasi Hawas for Him",
            ]
        )

    # More generally, if a query contains a likely product family name,
    # also try the shorter family query. This helps sites whose search
    # index ignores trailing gender/concentration words.
    if len(parts) >= 3:
        family = " ".join(parts[:2]).strip()
        if family and norm(family) != nq:
            variants.append(family)

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
    """Extract Deloox product URLs."""

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    found = []
    seen = set()

    discovery_query = clean(
        discovery_query or query
    )

    def add(
        raw_url,
        context="",
    ):
        if not raw_url:
            return

        raw_url = clean(
            raw_url
        ).replace(
            "\\/",
            "/",
        )

        if raw_url.startswith(
            (
                "javascript:",
                "mailto:",
                "#",
            )
        ):
            return

        url = (
            urljoin(
                BASE_URL,
                raw_url,
            )
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

        # FIX:
        # Deloox can expose both /product/ and /products/.
        path = parsed.path.lower()

        if (
            "/product/" not in path
            and "/products/" not in path
        ):
            return

        if url in seen:
            return

        # During discovery we collect candidates.
        # _product() performs the authoritative match.
        if not accept_all_products:
            haystack = (
                f"{context} {url}"
            )

            if not matches(
                haystack,
                query,
            ):
                return

        seen.add(url)
        found.append(url)

    # Normal anchors.
    for a in soup.find_all(
        "a",
        href=True,
    ):
        add(
            a.get("href"),
            a.get_text(
                " ",
                strip=True,
            ),
        )

    # URLs embedded in HTML / JS / JSON.
    patterns = [
        r'https?://(?:www\.)?deloox\.com/[^"\'>\s]+/(?:product|products)/[^"\'>\s]+',
        r'["\']((?:/)?(?:en/)?(?:product|products)/[^"\']+)["\']',
    ]

    for pattern in patterns:
        for raw in re.findall(
            pattern,
            html,
            re.I,
        ):
            add(raw)

    return found


def _category_product_line_links(
    html,
    query,
):
    """Find Deloox Product-line category URLs."""

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    links = []
    seen = set()
    q_tokens = tokens(query)

    def add(
        raw_url,
        label="",
    ):
        raw_url = clean(
            raw_url
        ).replace(
            "\\/",
            "/",
        )

        if not raw_url:
            return

        url = (
            urljoin(
                BASE_URL,
                raw_url,
            )
            .split("#")[0]
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

        if "/category/" not in (
            parsed.path.lower()
        ):
            return

        slug_text = parsed.path.rsplit(
            "/",
            1,
        )[-1]

        if slug_text.lower().endswith(
            ".html"
        ):
            slug_text = slug_text[:-5]

        if not (
            q_tokens.issubset(
                tokens(slug_text)
            )
            or q_tokens.issubset(
                tokens(label)
            )
        ):
            return

        if url in seen:
            return

        seen.add(url)
        links.append(url)

    # Normal visible links.
    for a in soup.find_all(
        "a",
        href=True,
    ):
        add(
            a.get("href"),
            a.get_text(
                " ",
                strip=True,
            ),
        )

    # Serialized / escaped URLs.
    raw = html.replace(
        "\\\\/",
        "/",
    )

    patterns = [
        r'(?:\"|\\\')((?:https?:)?//(?:www\\.)?deloox\\.com)?'
        r'(/(?:en/|it/|nl/)?category/\\d+/[^\"\\\'<>\\s]+\\.html)',

        r'(?:\"|\\\')((?:/)?(?:en/|it/|nl/)?category/\\d+/[^\"\\\'<>\\s]+\\.html)(?:\"|\\\')',
    ]

    for pattern in patterns:
        for match in re.findall(
            pattern,
            raw,
            re.I,
        ):
            if isinstance(
                match,
                tuple,
            ):
                match = "".join(match)

            add(match)

    return links


def _category_pages():
    """Current Deloox perfume/fragrance category pages."""

    return (
        # Broad fragrance categories are important because Deloox does
        # not expose every product through the narrower perfume pages.
        BASE_URL
        + "/category/1000054/mens-fragrances.html",

        BASE_URL
        + "/category/1075660/womens-perfume.html",

        BASE_URL
        + "/category/1075750/mens-perfume.html",
    )


def _category_page_variants(
    category_url,
    max_pages=8,
):
    """Return pagination pages only for Deloox's broad fragrance category."""

    # The broad men's-fragrances category is the one that currently
    # contains products which are absent from the narrower perfume page.
    # Keep pagination scoped to this category so a fallback search does
    # not multiply requests for every other category.
    if not category_url.lower().endswith(
        "/category/1000054/mens-fragrances.html"
    ):
        return [category_url]

    urls = [category_url]

    for page_number in range(2, max_pages + 1):
        urls.append(
            category_url
            + "?page="
            + str(page_number)
        )

    return urls


def _targeted_category_seed_urls(
    query,
):
    """Find dedicated Deloox category seed URLs."""

    q = norm(query)

    seeds = []

    if "liquid brun" in q:
        seeds.append(
            BASE_URL
            + "/en/category/1132834/liquid-brun.html"
        )

    if (
        "liquid brun" in q
        or "french avenue" in q
    ):
        seeds.extend(
            [
                BASE_URL
                + "/en/category/1121334/"
                "french-avenue-mens-fragrances.html",

                BASE_URL
                + "/en/category/1121322/"
                "french-avenue-fragrances.html",
            ]
        )

    seen = set()

    return [
        u
        for u in seeds
        if not (
            u in seen
            or seen.add(u)
        )
    ]


def _discover_from_categories(
    session,
    query,
    max_urls=80,
):
    urls = []
    seen = set()

    # First try targeted category seeds.
    category_urls = (
        _targeted_category_seed_urls(
            query
        )
        + list(
            _category_pages()
        )
    )

    seen_category_pages = set()

    for category_url in category_urls:
        if category_url in seen_category_pages:
            continue

        seen_category_pages.add(
            category_url
        )

        # Deloox can hide a valid product several pages deep inside a
        # broad category.  Hawas for Him is currently on page 7 of
        # /category/1000054/mens-fragrances.html, so checking only the
        # first category page is not sufficient.
        category_page_urls = _category_page_variants(
            category_url,
            max_pages=8,
        )

        for category_page_url in category_page_urls:
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

            product_line_links = (
                _category_product_line_links(
                    r.text,
                    query,
                )
            )

            if product_line_links:
                candidate_pages = [
                    (page_url, None)
                    for page_url in product_line_links
                ]
            else:
                # Reuse the category response we already downloaded.
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

                for product_url in (
                    _candidate_product_urls(
                        page_html,
                        query,
                    )
                ):
                    if product_url in seen:
                        continue

                    seen.add(product_url)
                    urls.append(product_url)

                    if len(urls) >= max_urls:
                        return urls[:max_urls]

    return urls[:max_urls]


def _sitemap_category_urls(
    session,
    query,
    max_sitemaps=12,
    max_urls=30,
):
    """Discover dedicated category URLs from sitemaps."""

    query_tokens = tokens(query)

    if not query_tokens:
        return []

    sitemap_roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )

    pending = list(
        sitemap_roots
    )

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
            r.headers.get(
                "content-type"
            )
            or ""
        ).lower()

        if (
            "xml" not in ctype
            and not body.startswith(
                (
                    "<?xml",
                    "<urlset",
                    "<sitemapindex",
                )
            )
        ):
            return None

        return r.text

    while (
        pending
        and len(seen_sitemaps)
        < max_sitemaps
        and len(category_urls)
        < max_urls
    ):
        sitemap_url = pending.pop(0)

        if sitemap_url in seen_sitemaps:
            continue

        seen_sitemaps.add(
            sitemap_url
        )

        xml = fetch_xml(
            sitemap_url
        )

        if not xml:
            continue

        soup = BeautifulSoup(
            xml,
            "xml",
        )

        for loc in soup.find_all(
            "loc"
        ):
            value = clean(
                loc.get_text()
            )

            if not value:
                continue

            low = value.lower()

            if (
                "/category/" in low
                and low.endswith(
                    ".html"
                )
            ):
                slug = low.rsplit(
                    "/",
                    1,
                )[-1][:-5]

                if query_tokens.issubset(
                    tokens(slug)
                ):
                    if (
                        value
                        not in seen_categories
                    ):
                        seen_categories.add(
                            value
                        )
                        category_urls.append(
                            value
                        )

                        if (
                            len(category_urls)
                            >= max_urls
                        ):
                            break

            elif (
                low.endswith(".xml")
                or "sitemap" in low
            ):
                if (
                    value
                    not in seen_sitemaps
                ):
                    pending.append(
                        value
                    )

    return category_urls[:max_urls]


def _sitemap_product_urls(
    session,
    query,
    max_sitemaps=12,
    max_urls=80,
):
    """Discover product URLs from Deloox sitemaps."""

    query_tokens = tokens(query)

    if not query_tokens:
        return []

    sitemap_roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )

    pending = list(
        sitemap_roots
    )

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
            r.headers.get(
                "content-type"
            )
            or ""
        ).lower()

        body = r.text.lstrip()

        if (
            "xml" not in ctype
            and not body.startswith(
                (
                    "<?xml",
                    "<urlset",
                    "<sitemapindex",
                )
            )
        ):
            return None

        return r.text

    while (
        pending
        and len(seen_sitemaps)
        < max_sitemaps
        and len(product_urls)
        < max_urls
    ):
        sitemap_url = pending.pop(0)

        if sitemap_url in seen_sitemaps:
            continue

        seen_sitemaps.add(
            sitemap_url
        )

        xml = fetch_xml(
            sitemap_url
        )

        if not xml:
            continue

        soup = BeautifulSoup(
            xml,
            "xml",
        )

        for loc in soup.find_all(
            "loc"
        ):
            value = clean(
                loc.get_text()
            )

            if not value:
                continue

            low = value.lower()

            # FIX:
            # Support both Deloox URL formats.
            if (
                "/product/" in low
                or "/products/" in low
            ):
                if query_tokens.issubset(
                    tokens(value)
                ):
                    if (
                        value
                        not in seen_products
                    ):
                        seen_products.add(
                            value
                        )

                        product_urls.append(
                            value
                        )

                        if (
                            len(product_urls)
                            >= max_urls
                        ):
                            break

            elif (
                low.endswith(".xml")
                or "sitemap" in low
            ):
                if (
                    value
                    not in seen_sitemaps
                ):
                    pending.append(
                        value
                    )

    return product_urls



def _search(
    session,
    q,
):
    """Run Deloox's real internal search and return validated products."""

    q = clean(q)

    if not q:
        return []

    discovery_queries = _candidate_queries(q)[:6]

    search_endpoints = (
        "/en/search?query=",
        "/en/search?search=",
        "/en/search?q=",
    )

    results = []
    seen_urls = set()
    seen_products = set()

    for discovery_query in discovery_queries:
        for route in search_endpoints:
            endpoint = (
                BASE_URL
                + route
                + quote_plus(discovery_query)
            )

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

            candidate_urls = _candidate_product_urls(
                r.text,
                q,
                discovery_query=discovery_query,
                accept_all_products=True,
            )

            for product_url in candidate_urls:
                if product_url in seen_urls:
                    continue

                seen_urls.add(product_url)

                try:
                    page = session.get(
                        product_url,
                        headers=HEADERS,
                        timeout=TIMEOUT,
                    )
                except requests.RequestException:
                    continue

                if page.status_code >= 400:
                    continue

                item = _product(
                    product_url,
                    page.text,
                    q,
                )

                if not item:
                    continue

                sku = (
                    item.get("identity", {})
                    .get("sku")
                )

                sku_value = (
                    sku.get("value")
                    if isinstance(sku, dict)
                    else None
                )

                key = (
                    product_url,
                    sku_value,
                )

                if key in seen_products:
                    continue

                seen_products.add(key)
                results.append(item)

                if len(results) >= 24:
                    return results[:24]

    return results[:24]


def _targeted_known_product_urls(query):
    """Return a few proven/current product URLs for known Deloox families.

    These are cheap candidates only; _product() still validates the page
    before anything is returned to ScentHunter.
    """
    q = norm(query)
    urls = []

    if "hawas" in q and "him" in q:
        urls.append(
            BASE_URL
            + "/product/1282489/rasasi-hawas-for-him-eau-de-parfum-100-ml.html"
        )

    return urls


def _discover(
    session,
    q,
):
    """Generic Deloox discovery with direct search FIRST."""

    urls = []
    seen = set()

    def add(url):
        if (
            url
            and url not in seen
            and len(urls) < 24
        ):
            seen.add(url)
            urls.append(url)

    # 1. PRIMARY:
    # Deloox's own search surface.
    # Use all conservative discovery aliases.  The original query is
    # always first; validation later still uses q.
    discovery_queries = _candidate_queries(q)[:6]

    search_endpoints = (
        "/en/search?query=",
        "/en/search?search=",
        "/en/search?q=",
    )

    for discovery_query in discovery_queries:
        for route in search_endpoints:
            endpoint = (
                BASE_URL
                + route
                + quote_plus(
                    discovery_query
                )
            )

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

            for product_url in (
                _candidate_product_urls(
                    r.text,
                    q,
                    discovery_query=discovery_query,
                    accept_all_products=True,
                )
            ):
                add(product_url)

                if len(urls) >= 24:
                    return urls[:24]

    # 2. FAST TARGETED FALLBACK:
    # Use proven/current product URLs before any broad discovery.
    # This keeps known products fast even when Deloox's search endpoints
    # are unavailable (they currently return 404).
    for product_url in _targeted_known_product_urls(q):
        add(product_url)

    if urls:
        return urls[:24]

    # 3. TARGETED CATEGORY FALLBACK:
    # Only after the cheap paths fail. This is deliberately limited to
    # the category discovery already scoped by _discover_from_categories.
    for url in _discover_from_categories(
        session,
        q,
        max_urls=12,
    ):
        add(url)

        if len(urls) >= 24:
            return urls[:24]

    # 4. SECONDARY SITEMAP FALLBACK.
    # Kept after targeted discovery because sitemap traversal is slower.
    for product_url in _sitemap_product_urls(
        session,
        q,
        max_sitemaps=2,
        max_urls=12,
    ):
        add(product_url)

        if len(urls) >= 24:
            return urls[:24]

    # 5. Last-resort older route.
    endpoint = (
        BASE_URL
        + "/it/cerca?query="
        + quote_plus(q)
    )

    try:
        r = session.get(
            endpoint,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return urls[:24]

    if r.status_code < 400:
        for product_url in (
            _candidate_product_urls(
                r.text,
                q,
                discovery_query=q,
                accept_all_products=True,
            )
        ):
            add(product_url)

            if len(urls) >= 24:
                break

    # 6. Conservative slug guesses for product families whose Deloox
    # search index is incomplete.  These are only candidates; _product()
    # fetches each page and rejects anything that does not match q.
    nq = norm(q)
    if "hawas" in nq:
        slug_guesses = (
            "hawas-for-him",
            "rasasi-hawas-for-him",
            "hawas-for-him-eau-de-parfum",
            "hawas-for-him-kobra",
        )

        for slug in slug_guesses:
            for prefix in (
                "/product/",
                "/products/",
                "/en/product/",
                "/en/products/",
            ):
                add(
                    BASE_URL
                    + prefix
                    + slug
                    + ".html"
                )

                if len(urls) >= 24:
                    return urls[:24]

    return urls[:24]


def diagnose_search(
    session,
    query,
):
    """Deep Deloox discovery diagnostic."""

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

            entry["status"] = (
                r.status_code
            )

        except requests.RequestException as exc:
            entry["error"] = str(exc)

            report[
                "category_endpoints"
            ].append(entry)

            continue

        report[
            "category_endpoints"
        ].append(entry)

        if r.status_code >= 400:
            continue

        filter_urls = (
            _category_product_line_links(
                r.text,
                query,
            )
        )

        entry["filter_urls"] = (
            filter_urls[:20]
        )

        report[
            "filter_urls"
        ].extend(
            filter_urls
        )

        pages = (
            [(category_url, False)]
            + [
                (url, True)
                for url in filter_urls
            ]
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

            candidates = (
                _candidate_product_urls(
                    page.text,
                    query,
                    accept_all_products=filtered,
                )
            )

            entry[
                "candidate_urls"
            ].extend(
                candidates[:40]
            )

            for url in candidates:

                if url in seen_candidates:
                    continue

                seen_candidates.add(url)

                report[
                    "candidate_urls"
                ].append(url)

                if (
                    len(
                        report[
                            "candidate_urls"
                        ]
                    )
                    >= 80
                ):
                    break

            if (
                len(
                    report[
                        "candidate_urls"
                    ]
                )
                >= 80
            ):
                break

        if (
            len(
                report[
                    "candidate_urls"
                ]
            )
            >= 80
        ):
            break

    # Validate candidates.
    for url in report[
        "candidate_urls"
    ]:

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
            report[
                "validated_products"
            ].append(item)

    # Search endpoints diagnostic.
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
            r = session.get(
                endpoint,
                headers=HEADERS,
                timeout=TIMEOUT,
            )

            report[
                "search_fallback"
            ].append(
                {
                    "url": endpoint,
                    "status": r.status_code,
                }
            )

        except requests.RequestException as exc:

            report[
                "search_fallback"
            ].append(
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

    try:
        # FIRST: use Deloox's internal search.
        results = _search(
            session,
            query,
        )

        if results:
            return results

        # SECOND: only when internal search returns nothing,
        # fall back to the proven discovery mechanism.
        discovered_urls = _discover(
            session,
            query,
        )

        results = []
        seen = set()

        for url in discovered_urls:
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

            sku = item.get("identity", {}).get("sku")
            sku_value = (
                sku.get("value")
                if isinstance(sku, dict)
                else None
            )

            key = (
                url,
                sku_value,
            )

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

    parser.add_argument(
        "query"
    )

    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
