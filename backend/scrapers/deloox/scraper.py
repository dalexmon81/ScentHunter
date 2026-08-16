"""Deloox adapter for ScentHunter.

Generic Deloox discovery adapter.

Important:
- Discovery is deliberately broad.
- Candidate product URLs are NOT rejected early because the URL slug
  does not exactly match the search query.
- The real product name is checked only after opening the product page.
- Matching supports cases such as:
      "Armaf De Nuit Sillage"
  ->  "Armaf Club De Nuit Sillage Eau de Parfum"
- No perfume-specific hard-coded fix is required.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


# =========================================================
# BASIC HELPERS
# =========================================================

def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", clean(v).lower()),
    ).strip()


def tokens(v):
    return {
        x
        for x in norm(v).split()
        if len(x) > 1
    }


def search_tokens(value):
    """
    Tokens used for product matching.

    Generic words that often describe the product type are ignored,
    while brand/name terms are preserved.
    """

    stop = {
        "for",
        "the",
        "and",
        "with",
        "him",
        "her",
        "men",
        "mens",
        "women",
        "womens",
        "perfume",
        "parfum",
        "fragrance",
        "eau",
        "ml",
        "edt",
        "edp",
        "spray",
    }

    return {
        x
        for x in norm(value).split()
        if len(x) > 1 and x not in stop
    }


def product_matches(name, query):
    """
    Generic product-name matching.

    Exact token matching is preferred.

    If the exact token set is not present, a tolerant match is used.
    This handles real-world Deloox naming differences, for example:

        query:
            Armaf De Nuit Sillage

        product:
            Armaf Club De Nuit Sillage Eau de Parfum

    The match is based on meaningful terms rather than requiring the
    complete product name or URL slug to be identical.
    """

    q = search_tokens(query)
    n = search_tokens(name)

    if not q or not n:
        return False

    # Exact meaningful-token match.
    if q.issubset(n):
        return True

    matched = 0

    for qt in q:
        if qt in n:
            matched += 1
            continue

        # Allow small naming differences / compound names.
        if any(
            qt in nt or nt in qt
            for nt in n
            if len(nt) >= 3
        ):
            matched += 1

    # Require all terms when there are only 1-2 meaningful tokens.
    # For longer names, tolerate one missing naming term because Deloox
    # often inserts words such as "Club", "de", "For Him", etc.
    if len(q) <= 2:
        return matched == len(q)

    return matched / len(q) >= 0.66


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


def availability(text):
    """Normalize Deloox availability values."""

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


# =========================================================
# JSON-LD
# =========================================================

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
                stack.extend(x["@graph"])

    return {}


# =========================================================
# PRODUCT PARSER
# =========================================================

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

    if not name:
        return None

    # IMPORTANT:
    # Do not use the old strict matches() check here.
    # Product names on Deloox frequently differ from the user's query.
    if not product_matches(
        name,
        query,
    ):
        return None

    # -----------------------------------------------------
    # Product line
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Brand
    # -----------------------------------------------------

    brand = data.get("brand")

    if isinstance(
        brand,
        dict,
    ):
        brand = brand.get("name")

    # -----------------------------------------------------
    # Offers
    # -----------------------------------------------------

    offers = data.get("offers")

    if isinstance(
        offers,
        list,
    ):
        offer = next(
            (
                x
                for x in offers
                if isinstance(x, dict)
            ),
            {},
        )

    elif isinstance(
        offers,
        dict,
    ):
        offer = offers

    else:
        offer = {}

    # -----------------------------------------------------
    # Price
    # -----------------------------------------------------

    price = parse_price(
        offer.get("price")
    )

    if price is None:
        price = parse_price(text)

    if price is None:
        return None

    # -----------------------------------------------------
    # GTIN
    # -----------------------------------------------------

    gtin = clean(
        data.get("gtin13")
        or data.get("gtin14")
        or data.get("gtin")
        or ""
    ) or None

    # -----------------------------------------------------
    # MPN
    # -----------------------------------------------------

    mpn = clean(
        data.get("mpn")
        or ""
    ) or None

    # -----------------------------------------------------
    # SKU
    # -----------------------------------------------------

    sku = clean(
        data.get("sku")
        or ""
    ) or None

    # -----------------------------------------------------
    # Image
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Availability
    # -----------------------------------------------------

    avail = availability(text)

    jsonld_availability = clean(
        offer.get("availability")
        or ""
    )

    if jsonld_availability:
        availability_norm = norm(
            jsonld_availability
        )

        if (
            "instock" in availability_norm
            or "in stock" in availability_norm
        ):
            avail = "in_stock"

        elif any(
            x in availability_norm
            for x in (
                "outofstock",
                "out of stock",
                "soldout",
                "sold out",
            )
        ):
            avail = "out_of_stock"

    # -----------------------------------------------------
    # Result
    # -----------------------------------------------------

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
            f"{price:.2f}".replace(".", ",")
            + " €"
        ),

        "url": url,

        "available": (
            avail == "in_stock"
        ),
    }


# =========================================================
# QUERY VARIANTS
# =========================================================

def _candidate_queries(query):
    """
    Generate progressively broader search queries.
    """

    normalized = norm(query)

    if not normalized:
        return []

    stop = {
        "for",
        "the",
        "and",
        "with",
        "de",
        "da",
        "del",
        "della",
        "du",
        "des",
        "di",
        "by",
        "e",
        "in",
        "of",
    }

    searches = [clean(query)]

    meaningful = [
        token
        for token in normalized.split()
        if token not in stop
        and len(token) > 1
    ]

    if normalized not in searches:
        searches.append(normalized)

    # Longer/more distinctive terms first.
    for token in sorted(
        meaningful,
        key=lambda x: (-len(x), x),
    ):
        if token not in searches:
            searches.append(token)

    return searches


# =========================================================
# PRODUCT URL DISCOVERY
# =========================================================

def _candidate_product_urls(
    html,
    query,
    discovery_query=None,
    accept_all_products=False,
):
    """
    Extract Deloox product URLs from HTML,
    JSON, JSON-LD, JS and data attributes.

    IMPORTANT:
    No early query filtering is performed.

    The old implementation discarded URLs when the URL/context
    did not contain all query tokens. That caused valid products
    such as "Armaf Club De Nuit Sillage" to disappear when the
    user searched "Armaf De Nuit Sillage".

    Candidate collection is now broad; _product() performs
    the actual product-name validation.
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    found = []
    seen = set()

    def add(raw_url):
        if not raw_url:
            return

        raw_url = (
            clean(raw_url)
            .replace("\\/", "/")
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

        if "/product/" not in parsed.path.lower():
            return

        if url in seen:
            return

        seen.add(url)
        found.append(url)

    # -----------------------------------------------------
    # 1. Normal anchors
    # -----------------------------------------------------

    for a in soup.find_all(
        "a",
        href=True,
    ):
        add(
            a.get("href")
        )

    # -----------------------------------------------------
    # 2. Literal product URLs
    # -----------------------------------------------------

    product_patterns = [
        r'https?://(?:www\.)?deloox\.com/[^"\'<>\s]+/product/[^"\'<>\s]+',

        r'["\']((?:/)?(?:en/|it/|nl/)?product/[^"\']+)["\']',

        r'["\']((?:https?:)?//(?:www\.)?deloox\.com/[^"\']*/product/[^"\']+)["\']',
    ]

    for pattern in product_patterns:
        for raw in re.findall(
            pattern,
            html,
            re.I,
        ):
            if isinstance(
                raw,
                tuple,
            ):
                raw = "".join(raw)

            add(raw)

    # -----------------------------------------------------
    # 3. JSON / JSON-LD / serialized state / JS
    # -----------------------------------------------------

    for script in soup.find_all("script"):

        body = script.get_text(
            " ",
            strip=False,
        )

        if (
            not body
            or "/product/" not in body.lower()
        ):
            continue

        for match in re.finditer(
            r'(?P<url>(?:https?:)?//(?:www\.)?deloox\.com/[^"\'<>\s]+/product/[^"\'<>\s]+|'
            r'/?(?:en/|it/|nl/)?product/[^"\'<>\s]+)',
            body,
            re.I,
        ):
            add(
                match.group("url")
            )

    # -----------------------------------------------------
    # 4. Product-card data attributes
    # -----------------------------------------------------

    for tag in soup.find_all(True):

        attrs = tag.attrs or {}

        for value in attrs.values():

            if not isinstance(
                value,
                str,
            ):
                continue

            if "/product/" not in value.lower():
                continue

            for match in re.finditer(
                r'(?:https?:)?//(?:www\.)?deloox\.com/[^"\'>\s]+/product/[^"\'>\s]+|'
                r'/?(?:en/|it/|nl/)?product/[^"\'>\s]+',
                value,
                re.I,
            ):
                add(
                    match.group(0)
                )

    return found


# =========================================================
# PRODUCT-LINE / CATEGORY FILTER LINKS
# =========================================================

def _category_product_line_links(
    html,
    query,
):
    """
    Find Deloox category/Product-line URLs that may be useful
    for discovery.

    Query matching is used only to prioritize category links,
    never to validate the final product.
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    links = []
    seen = set()

    q_tokens = search_tokens(query)

    if not q_tokens:
        return links

    def url_ok(raw_url):

        raw_url = (
            clean(raw_url)
            .replace("\\/", "/")
        )

        if not raw_url:
            return None

        if raw_url.startswith(
            (
                "javascript:",
                "mailto:",
                "#",
            )
        ):
            return None

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
            return None

        if parsed.netloc.lower() not in {
            "deloox.com",
            "www.deloox.com",
        }:
            return None

        path = parsed.path.lower()
        query_string = parsed.query.lower()

        if (
            "/category/" not in path
            and "filter" not in query_string
        ):
            return None

        return url

    def add(
        raw_url,
        label="",
        context="",
    ):

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

        # Fuzzy relevance for category discovery.
        matched = 0

        for qt in q_tokens:
            if qt in search_tokens(haystack):
                matched += 1
                continue

            if any(
                qt in nt or nt in qt
                for nt in search_tokens(haystack)
                if len(nt) >= 3
            ):
                matched += 1

        if not matched:
            return

        if url in seen:
            return

        seen.add(url)
        links.append(url)

    # Normal anchors.
    for a in soup.find_all(
        "a",
        href=True,
    ):

        label = a.get_text(
            " ",
            strip=True,
        )

        href = a.get("href")

        add(
            href,
            label,
            label,
        )

    # data-url / data-href / data-link / data-target.
    for tag in soup.find_all(True):

        attrs = tag.attrs or {}

        label = tag.get_text(
            " ",
            strip=True,
        )

        for key in (
            "data-url",
            "data-href",
            "data-link",
            "data-target",
        ):

            value = attrs.get(key)

            if isinstance(
                value,
                str,
            ):
                add(
                    value,
                    label,
                    label,
                )

    # Raw HTML / JS.
    raw = html.replace(
        "\\\\/",
        "/",
    )

    url_pattern = re.compile(
        r'(?:https?:)?//(?:www\.)?deloox\.com[^"\'<>\s]+|'
        r'/(?:en/|it/|nl/)?category/[^"\'<>\s]+',
        re.I,
    )

    for m in url_pattern.finditer(raw):

        raw_url = m.group(0)

        if (
            "filter" not in raw_url.lower()
            and "category/" not in raw_url.lower()
        ):
            continue

        context = raw[
            max(
                0,
                m.start() - 1800,
            ):
            min(
                len(raw),
                m.end() + 1800,
            )
        ]

        add(
            raw_url,
            context,
            context,
        )

    return links[:80]


# =========================================================
# CATEGORY ROOTS
# =========================================================

def _category_pages(session=None):
    """
    Current broad Deloox fragrance category roots.

    Extra category roots are intentionally included so that
    brand-specific products have more chances to appear.
    """

    return (
        BASE_URL + "/category/1000054/mens-fragrances.html",
        BASE_URL + "/category/1075639/womens-fragrances.html",
        BASE_URL + "/category/1075750/mens-perfume.html",
        BASE_URL + "/category/1000003/fragrances.html",

        BASE_URL + "/it/categoria/1000054/profumi-uomo.html",
        BASE_URL + "/it/categoria/1075639/profumi-donna.html",
        BASE_URL + "/it/categoria/1075750/profumi-uomo.html",
        BASE_URL + "/it/categoria/1000003/profumi.html",

        BASE_URL + "/category/1079036/armaf-fragrances.html",
    )


# =========================================================
# TARGETED SEEDS
# =========================================================

def _targeted_category_seed_urls(query):
    """
    Optional category seeds for known high-value query patterns.

    These are discovery accelerators only.
    They are NOT required for correctness.
    """

    q = norm(query)

    seeds = []

    # Liquid Brun.
    if "liquid brun" in q:
        seeds.append(
            BASE_URL
            + "/en/category/1132834/liquid-brun.html"
        )

    # French Avenue.
    if (
        "liquid brun" in q
        or "french avenue" in q
    ):
        seeds.extend(
            [
                BASE_URL
                + "/en/category/1121334/"
                + "french-avenue-mens-fragrances.html",

                BASE_URL
                + "/en/category/1121322/"
                + "french-avenue-fragrances.html",
            ]
        )

    # Armaf.
    if "armaf" in q:
        seeds.append(
            BASE_URL
            + "/category/1079036/armaf-fragrances.html"
        )

    seen = set()

    result = []

    for u in seeds:
        if u in seen:
            continue

        seen.add(u)
        result.append(u)

    return result


# =========================================================
# ROBOTS / SITEMAP DISCOVERY
# =========================================================

def _robots_sitemaps(session):
    """Read sitemap locations published by Deloox robots.txt."""

    roots = [
        BASE_URL + "/robots.txt",
        BASE_URL + "/en/robots.txt",
        BASE_URL + "/it/robots.txt",
    ]

    found = []
    seen = set()

    for robots_url in roots:
        try:
            r = session.get(
                robots_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            continue

        for line in r.text.splitlines():
            if not line.lower().startswith("sitemap:"):
                continue

            value = clean(
                line.split(":", 1)[1]
            )

            if not value:
                continue

            if value not in seen:
                seen.add(value)
                found.append(value)

    return found


def _common_sitemaps():
    return [
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/sitemap.xml.gz",
        BASE_URL + "/sitemap_index.xml.gz",
        BASE_URL + "/sitemap-index.xml.gz",
        BASE_URL + "/en/sitemap.xml",
        BASE_URL + "/en/sitemap.xml.gz",
    ]


def _xml_locs(xml_text):
    """Extract <loc> values without depending on XML namespaces."""

    if not xml_text:
        return []

    return [
        clean(x)
        for x in re.findall(
            r"<loc[^>]*>\s*(.*?)\s*</loc>",
            xml_text,
            re.I | re.S,
        )
        if clean(x)
    ]


def _fetch_xml(session, url):
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

    if not (
        "<loc" in body.lower()
        or body.startswith(
            (
                "<?xml",
                "<urlset",
                "<sitemapindex",
            )
        )
    ):
        return None

    return r.text


# =========================================================
# SITEMAP CATEGORY DISCOVERY
# =========================================================

def _sitemap_category_urls(
    session,
    query,
    max_sitemaps=50,
    max_urls=100,
):
    """
    Discover relevant Deloox category/Product-line pages.
    """

    query_tokens = search_tokens(query)

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
            r.headers.get("content-type")
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
        and len(seen_sitemaps) < max_sitemaps
        and len(category_urls) < max_urls
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

        for loc in soup.find_all("loc"):

            value = clean(
                loc.get_text()
            )

            if not value:
                continue

            low = value.lower()

            if (
                "/category/" in low
                and low.endswith(".html")
            ):

                slug = (
                    low.rsplit(
                        "/",
                        1,
                    )[-1][:-5]
                )

                slug_tokens = search_tokens(
                    slug
                )

                # Fuzzy category relevance.
                matched = 0

                for qt in query_tokens:

                    if qt in slug_tokens:
                        matched += 1
                        continue

                    if any(
                        qt in st or st in qt
                        for st in slug_tokens
                        if len(st) >= 3
                    ):
                        matched += 1

                if matched:

                    if value not in seen_categories:

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

                if value not in seen_sitemaps:
                    pending.append(value)

    return category_urls[:max_urls]


# =========================================================
# SITEMAP PRODUCT DISCOVERY
# =========================================================

def _sitemap_product_urls(
    session,
    query,
    max_sitemaps=120,
    max_urls=300,
):
    """
    Robust Deloox product discovery.

    The previous version assumed a small set of sitemap filenames.
    Deloox can publish the real sitemap locations through robots.txt
    and/or a sitemap index. This version discovers those locations,
    follows sitemap indexes recursively, and only then filters product
    URLs by meaningful query tokens.

    This is the main generic fallback and is not perfume-specific.
    """

    query_tokens = search_tokens(query)

    if not query_tokens:
        return []

    pending = []
    seen_sitemaps = set()
    product_urls = []
    seen_products = set()

    # robots.txt is the first source of truth.
    pending.extend(
        _robots_sitemaps(session)
    )

    # Keep known roots as fallback.
    pending.extend(
        _common_sitemaps()
    )

    def relevant_url(url):
        url_tokens = search_tokens(url)

        if not url_tokens:
            return False

        # Require at least one meaningful query token.
        # Product pages are validated later against the actual name.
        for qt in query_tokens:
            if qt in url_tokens:
                return True

            if any(
                qt in ut or ut in qt
                for ut in url_tokens
                if len(ut) >= 3
            ):
                return True

        return False

    while (
        pending
        and len(seen_sitemaps) < max_sitemaps
        and len(product_urls) < max_urls
    ):
        sitemap_url = pending.pop(0)

        if sitemap_url in seen_sitemaps:
            continue

        seen_sitemaps.add(sitemap_url)

        xml = _fetch_xml(
            session,
            sitemap_url,
        )

        if not xml:
            continue

        for loc in _xml_locs(xml):

            low = loc.lower()

            if "/product/" in low:
                if not relevant_url(loc):
                    continue

                if loc in seen_products:
                    continue

                seen_products.add(loc)
                product_urls.append(loc)

                if len(product_urls) >= max_urls:
                    break

                continue

            # Sitemap index / nested sitemap.
            if (
                low.endswith(".xml")
                or low.endswith(".xml.gz")
                or "sitemap" in low
            ):
                if loc not in seen_sitemaps:
                    pending.append(loc)

    return product_urls[:max_urls]


# =========================================================
# MAIN DISCOVERY
# =========================================================

def _discover_from_categories(
    session,
    query,
    max_urls=200,
):
    """
    Discover product URLs from category pages.

    Deloox does not reliably expose every product on page 1.
    We therefore walk a limited number of pagination pages and stop
    as soon as enough candidates are collected.
    """

    urls = []
    seen = set()

    def add_candidates(html):
        candidates = _candidate_product_urls(
            html,
            query,
            accept_all_products=True,
        )

        for product_url in candidates:
            if product_url in seen:
                continue

            seen.add(product_url)
            urls.append(product_url)

            if len(urls) >= max_urls:
                return True

        return False

    roots = _category_pages(session)

    for category_url in roots:

        page_urls = [category_url]

        # Deloox uses ?page=N on category pages.
        for n in range(2, 16):
            separator = "&" if "?" in category_url else "?"
            page_urls.append(
                category_url
                + separator
                + "page="
                + str(n)
            )

        for page_url in page_urls:

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

            if add_candidates(page.text):
                return urls[:max_urls]

            # Also inspect relevant category/filter links on each page.
            filter_urls = _category_product_line_links(
                page.text,
                query,
            )

            for filter_url in filter_urls[:20]:

                try:
                    filtered = session.get(
                        filter_url,
                        headers=HEADERS,
                        timeout=TIMEOUT,
                    )
                except requests.RequestException:
                    continue

                if filtered.status_code >= 400:
                    continue

                if add_candidates(filtered.text):
                    return urls[:max_urls]

    return urls[:max_urls]


def _discover(session, q):

    urls = []
    seen = set()

    def add_many(values):
        for url in values:
            if url in seen:
                continue

            seen.add(url)
            urls.append(url)

            if len(urls) >= 250:
                return True

        return False

    # =====================================================
    # 1. SITEMAP FIRST
    # =====================================================

    # This is the most reliable generic path because it does not
    # depend on Deloox's changing search UI or filter parameters.
    if add_many(
        _sitemap_product_urls(
            session,
            q,
            max_sitemaps=120,
            max_urls=250,
        )
    ):
        return urls[:250]

    # =====================================================
    # 2. CATEGORY + PAGINATION
    # =====================================================

    if add_many(
        _discover_from_categories(
            session,
            q,
            max_urls=250,
        )
    ):
        return urls[:250]

    # =====================================================
    # 3. TARGETED CATEGORY SEEDS
    # =====================================================

    for category_url in _targeted_category_seed_urls(q):

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

        if add_many(
            _candidate_product_urls(
                page.text,
                q,
                accept_all_products=True,
            )
        ):
            return urls[:250]

    # =====================================================
    # 4. SEARCH ENDPOINTS
    # =====================================================

    # Keep these only as a fallback. Some Deloox search URLs return
    # 404, so a failed search endpoint must never terminate discovery.
    for discovery_query in _candidate_queries(q):

        endpoints = [
            BASE_URL
            + "/en/search?query="
            + quote_plus(discovery_query),

            BASE_URL
            + "/en/search?search="
            + quote_plus(discovery_query),

            BASE_URL
            + "/en/search?q="
            + quote_plus(discovery_query),

            BASE_URL
            + "/it/cerca?query="
            + quote_plus(discovery_query),

            BASE_URL
            + "/search?q="
            + quote_plus(discovery_query),
        ]

        for endpoint in endpoints:

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

            if add_many(
                _candidate_product_urls(
                    r.text,
                    q,
                    discovery_query=discovery_query,
                    accept_all_products=True,
                )
            ):
                return urls[:250]

    return urls[:250]


# =========================================================
# DIAGNOSTICS
# =========================================================

def diagnose_search(
    session,
    query,
):
    """
    Return a compact discovery trace.
    """

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

    # -----------------------------------------------------
    # Category endpoints
    # -----------------------------------------------------

    for category_url in _category_pages(
        session
    ):

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

        entry[
            "filter_urls"
        ] = filter_urls[:30]

        report[
            "filter_urls"
        ].extend(
            filter_urls
        )

        pages = (
            [
                (
                    category_url,
                    False,
                )
            ]
            + [
                (
                    u,
                    True,
                )
                for u in filter_urls
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

            candidates = _candidate_product_urls(
                page.text,
                query,
                accept_all_products=filtered,
            )

            entry[
                "candidate_urls"
            ].extend(
                candidates[:80]
            )

            for u in candidates:

                if u in seen_candidates:
                    continue

                seen_candidates.add(
                    u
                )

                report[
                    "candidate_urls"
                ].append(u)

                if (
                    len(
                        report[
                            "candidate_urls"
                        ]
                    )
                    >= 150
                ):
                    break

            if (
                len(
                    report[
                        "candidate_urls"
                    ]
                )
                >= 150
            ):
                break

        if (
            len(
                report[
                    "candidate_urls"
                ]
            )
            >= 150
        ):
            break

    # -----------------------------------------------------
    # Validate candidates
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Search fallback diagnostics
    # -----------------------------------------------------

    for discovery_query in _candidate_queries(
        query
    ):

        endpoints = [
            BASE_URL
            + "/en/search?query="
            + quote_plus(
                discovery_query
            ),

            BASE_URL
            + "/en/search?search="
            + quote_plus(
                discovery_query
            ),

            BASE_URL
            + "/en/search?q="
            + quote_plus(
                discovery_query
            ),
        ]

        for endpoint in endpoints:

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


# =========================================================
# PUBLIC SEARCH API
# =========================================================

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

            sku = item[
                "identity"
            ].get("sku")

            if sku:
                sku_value = sku.get(
                    "value"
                )

            key = (
                url,
                sku_value,
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            results.append(
                item
            )

        return results

    finally:
        session.close()


def scrape(query):
    return search(query)


# =========================================================
# COMMAND LINE
# =========================================================

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
