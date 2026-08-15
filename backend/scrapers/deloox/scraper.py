"""Deloox adapter for ScentHunter.

Discovery strategy:
- Prefer direct known product URLs for products whose Deloox product page
  is known and stable.
- Then use Deloox category pages and Product-line filters.
- Then targeted category pages.
- Then sitemap discovery.
- Search endpoints are kept only as a final fallback because Deloox
  currently returns 404 for the old /en/search endpoints.
- Product pages are parsed through JSON-LD/page content.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURAZIONE
# ============================================================

STORE = "Deloox"

BASE_URL = "https://www.deloox.com"

TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


# ============================================================
# DIRECT PRODUCT URLS
# ============================================================
#
# Queste URL vengono usate PRIMA della discovery generica.
#
# Motivo:
# Deloox può avere il prodotto perfettamente online ma le sue
# categorie generiche possono restituire risultati non pertinenti.
#
# Hawas For Him è stato verificato direttamente su Deloox:
#
# /product/1282489/rasasi-hawas-for-him-eau-de-parfum-100-ml.html
#
# ============================================================

DIRECT_PRODUCT_URLS = {
    "hawas for him": (
        BASE_URL
        + "/product/1282489/"
        + "rasasi-hawas-for-him-eau-de-parfum-100-ml.html"
    ),
}


# ============================================================
# FUNZIONI BASE
# ============================================================

def clean(v):
    return re.sub(
        r"\s+",
        " ",
        str(v or ""),
    ).strip()


def norm(v):
    return re.sub(
        r"\s+",
        " ",
        re.sub(
            r"[^a-z0-9]+",
            " ",
            clean(v).lower(),
        ),
    ).strip()


def tokens(v):
    return {
        x
        for x in norm(v).split()
        if len(x) > 1
    }


def matches(text, q):
    q_tokens = tokens(q)

    return (
        bool(q_tokens)
        and q_tokens.issubset(tokens(text))
    )


# ============================================================
# SIZE / CONCENTRATION
# ============================================================

def size_ml(*values):
    m = re.search(
        r"(?<!\d)"
        r"(\d+(?:[.,]\d+)?)"
        r"\s*(ml|cl)\b",
        " ".join(
            clean(x)
            for x in values
        ),
        re.I,
    )

    if not m:
        return None

    n = float(
        m.group(1).replace(",", ".")
    )

    if m.group(2).lower() == "cl":
        n *= 10

    return (
        int(n)
        if n.is_integer()
        else n
    )


def concentration(*values):
    t = norm(
        " ".join(
            clean(x)
            for x in values
        )
    )

    if re.search(
        r"\beau de toilette\b|\bedt\b",
        t,
    ):
        return "Eau de Toilette"

    if re.search(
        r"\beau de parfum\b|\bedp\b",
        t,
    ):
        return "Eau de Parfum"

    if re.search(
        r"\bextrait(?: de parfum)?\b",
        t,
    ):
        return "Extrait de Parfum"

    return None


# ============================================================
# PRICE
# ============================================================

def parse_price(v):
    s = clean(v)

    if not s:
        return None

    # Prima proviamo un prezzo chiaramente associato al simbolo €.
    euro_patterns = [
        r"€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"(\d{1,4}(?:[.,]\d{2})?)\s*€",
    ]

    for pattern in euro_patterns:
        m = re.search(
            pattern,
            s,
            re.I,
        )

        if m:
            try:
                return round(
                    float(
                        m.group(1).replace(
                            ",",
                            ".",
                        )
                    ),
                    2,
                )
            except ValueError:
                pass

    # Fallback.
    m = re.search(
        r"(\d{1,4}(?:[.,]\d{2})?)",
        s,
    )

    if not m:
        return None

    try:
        return round(
            float(
                m.group(1).replace(
                    ",",
                    ".",
                )
            ),
            2,
        )
    except ValueError:
        return None


# ============================================================
# AVAILABILITY
# ============================================================

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
            "available",
            "op voorraad",
        )
    ):
        return "in_stock"

    return "unknown"


# ============================================================
# JSON-LD
# ============================================================

def _jsonld(soup):
    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            data = json.loads(
                script.get_text(
                    strip=True
                )
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

            x_type = x.get("@type")

            if (
                x_type == "Product"
                or (
                    isinstance(
                        x_type,
                        list,
                    )
                    and "Product" in x_type
                )
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


# ============================================================
# PRODUCT PARSER
# ============================================================

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

    # --------------------------------------------------------
    # STRICT MATCH
    # --------------------------------------------------------

    if not name:
        return None

    if not matches(
        name,
        query,
    ):
        return None

    # --------------------------------------------------------
    # PAGE TEXT
    # --------------------------------------------------------

    text = soup.get_text(
        " ",
        strip=True,
    )

    # --------------------------------------------------------
    # PRODUCT LINE
    # --------------------------------------------------------

    product_line = ""

    m = re.search(
        r"product line\s+(.+?)"
        r"(?:for whom|fragrance type|season|spray|article number)",
        text,
        re.I,
    )

    if m:
        product_line = clean(
            m.group(1)
        )

    # --------------------------------------------------------
    # BRAND
    # --------------------------------------------------------

    brand = data.get("brand")

    if isinstance(
        brand,
        dict,
    ):
        brand = brand.get("name")

    brand = clean(
        brand
    )

    # --------------------------------------------------------
    # OFFERS
    # --------------------------------------------------------

    offers = data.get(
        "offers"
    )

    if isinstance(
        offers,
        list,
    ):
        offer_list = offers
    elif isinstance(
        offers,
        dict,
    ):
        offer_list = [offers]
    else:
        offer_list = []

    offer = next(
        (
            x
            for x in offer_list
            if isinstance(
                x,
                dict,
            )
        ),
        {},
    )

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    price = parse_price(
        offer.get("price")
    )

    if price is None:
        price = parse_price(
            offer.get(
                "lowPrice"
            )
        )

    if price is None:
        # Cerchiamo una cifra associata a € nel testo.
        euro_matches = re.findall(
            r"€\s*(\d{1,4}(?:[.,]\d{2})?)",
            text,
            re.I,
        )

        if euro_matches:
            price = parse_price(
                euro_matches[0]
            )

    if price is None:
        return None

    # --------------------------------------------------------
    # IDENTIFIERS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    image = data.get(
        "image"
    )

    if isinstance(
        image,
        list,
    ):
        image = (
            image[0]
            if image
            else None
        )

    if image:
        image = urljoin(
            url,
            str(image),
        )

    # --------------------------------------------------------
    # AVAILABILITY
    # --------------------------------------------------------

    avail = availability(
        text
    )

    # --------------------------------------------------------
    # SIZE / CONCENTRATION
    # --------------------------------------------------------

    parsed_size = size_ml(
        name
    )

    parsed_concentration = concentration(
        name
    )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    return {
        "store": STORE,

        "source": {
            "source_name": name,
            "source_brand": brand,
            "url": url,
            "image": image,
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
                    "value": parsed_size,
                    "source": "product_name",
                }
                if parsed_size is not None
                else None
            ),

            "concentration": (
                {
                    "value": parsed_concentration,
                    "source": "product_name",
                }
                if parsed_concentration
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
            f"{price:.2f}"
            .replace(
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


# ============================================================
# DIRECT PRODUCT DISCOVERY
# ============================================================

def _targeted_product_urls(query):
    """
    Restituisce URL prodotto conosciute e verificate.

    Questa fase viene eseguita PRIMA delle categorie generiche.

    È importante perché Deloox può avere il prodotto online ma
    la categoria generica può restituire una pagina non pertinente.
    """

    q_tokens = tokens(
        query
    )

    if not q_tokens:
        return []

    found = []

    for product_name, url in DIRECT_PRODUCT_URLS.items():

        product_tokens = tokens(
            product_name
        )

        if product_tokens.issubset(
            q_tokens
        ):
            found.append(url)
            continue

        # Caso:
        # query = "Rasasi Hawas For Him"
        # direct key = "Hawas For Him"
        if product_tokens.issubset(
            q_tokens
        ):
            found.append(url)

    # Deduplica
    return list(
        dict.fromkeys(found)
    )


# ============================================================
# CANDIDATE QUERIES
# ============================================================

def _candidate_queries(query):
    """Generate progressively broader Deloox discovery queries."""

    normalized = norm(
        query
    )

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

    searches = [
        clean(query)
    ]

    meaningful = [
        token
        for token in normalized.split()
        if token not in stop
        and len(token) > 1
    ]

    if normalized not in searches:
        searches.append(
            normalized
        )

    for token in sorted(
        meaningful,
        key=lambda x: (
            -len(x),
            x,
        ),
    ):
        if token not in searches:
            searches.append(
                token
            )

    return searches


# ============================================================
# PRODUCT URL DISCOVERY
# ============================================================

def _candidate_product_urls(
    html,
    query,
    discovery_query=None,
    accept_all_products=False,
):
    """
    Extract Deloox product URLs from HTML,
    JSON, JSON-LD and JS.
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    found = []
    seen = set()

    discovery = (
        discovery_query
        or query
    )

    q_tokens = tokens(
        discovery
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

        url = urljoin(
            BASE_URL,
            raw_url,
        )

        url = (
            url
            .split("#")[0]
            .split("?")[0]
        )

        try:
            parsed = urlparse(
                url
            )
        except Exception:
            return

        if parsed.netloc.lower() not in {
            "deloox.com",
            "www.deloox.com",
        }:
            return

        if "/product/" not in (
            parsed.path.lower()
        ):
            return

        if url in seen:
            return

        haystack = (
            f"{context} {url}"
        )

        if (
            not accept_all_products
            and q_tokens
            and not matches(
                haystack,
                discovery,
            )
        ):
            if not any(
                token in tokens(
                    haystack
                )
                for token in q_tokens
            ):
                return

        seen.add(url)
        found.append(url)

    # --------------------------------------------------------
    # 1. NORMAL ANCHORS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 2. RAW PRODUCT URLS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 3. SCRIPT / SERIALIZED DATA
    # --------------------------------------------------------

    for script in soup.find_all(
        "script"
    ):

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
            r'(?P<url>'
            r'(?:https?:)?//(?:www\.)?deloox\.com/[^"\'<>\s]+/product/[^"\'<>\s]+'
            r'|'
            r'/?(?:en/|it/|nl/)?product/[^"\'<>\s]+'
            r')',
            body,
            re.I,
        ):

            pos = match.start()

            context = body[
                max(
                    0,
                    pos - 1200,
                ):
                min(
                    len(body),
                    match.end() + 1200,
                )
            ]

            add(
                match.group("url"),
                context,
            )

    # --------------------------------------------------------
    # 4. DATA ATTRIBUTES
    # --------------------------------------------------------

    for tag in soup.find_all(
        True
    ):

        attrs = tag.attrs or {}

        attr_text = " ".join(
            clean(v)
            for v in attrs.values()
            if isinstance(
                v,
                (
                    str,
                    int,
                    float,
                ),
            )
        )

        if "/product/" not in (
            attr_text.lower()
        ):
            continue

        for m in re.finditer(
            r'(?:https?:)?//(?:www\.)?deloox\.com/[^"\'>\s]+/product/[^"\'>\s]+'
            r'|'
            r'/?(?:en/|it/|nl/)?product/[^"\'>\s]+',
            attr_text,
            re.I,
        ):

            add(
                m.group(0),
                (
                    f"{tag.get_text(' ', strip=True)} "
                    f"{attr_text}"
                ),
            )

    return found


# ============================================================
# PRODUCT LINE FILTER LINKS
# ============================================================

def _category_product_line_links(
    html,
    query,
):
    """
    Find Deloox Product-line filter/category URLs matching query.
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    links = []
    seen = set()

    q_tokens = tokens(
        query
    )

    if not q_tokens:
        return links

    def url_ok(raw_url):

        raw_url = clean(
            raw_url
        ).replace(
            "\\/",
            "/",
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

        url = urljoin(
            BASE_URL,
            raw_url,
        ).split("#")[0]

        try:
            parsed = urlparse(
                url
            )
        except Exception:
            return None

        if parsed.netloc.lower() not in {
            "deloox.com",
            "www.deloox.com",
        }:
            return None

        path = parsed.path.lower()

        query_string = (
            parsed.query.lower()
        )

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

        url = url_ok(
            raw_url
        )

        if not url:
            return

        parsed = urlparse(
            url
        )

        haystack = " ".join(
            (
                label,
                context,
                parsed.path,
                parsed.query,
            )
        )

        if not q_tokens.issubset(
            tokens(haystack)
        ):
            return

        if url in seen:
            return

        seen.add(url)
        links.append(url)

    # Normal anchors
    for a in soup.find_all(
        "a",
        href=True,
    ):

        label = a.get_text(
            " ",
            strip=True,
        )

        add(
            a.get("href"),
            label,
            label,
        )

    # Data attributes
    for tag in soup.find_all(
        True
    ):

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

            value = attrs.get(
                key
            )

            if isinstance(
                value,
                str,
            ):
                add(
                    value,
                    label,
                    label,
                )

    # Raw HTML / JS
    raw = html.replace(
        "\\\\/",
        "/",
    )

    url_pattern = re.compile(
        r'(?:https?:)?//(?:www\.)?deloox\.com[^"\'<>\s]+'
        r'|'
        r'/(?:en/|it/|nl/)?category/[^"\'<>\s]+',
        re.I,
    )

    for m in url_pattern.finditer(
        raw
    ):

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

    return links[:40]


# ============================================================
# CATEGORY ROOTS
# ============================================================

def _category_pages(session):

    return (
        BASE_URL
        + "/category/1000054/mens-fragrances.html",

        BASE_URL
        + "/category/1075639/womens-fragrances.html",

        BASE_URL
        + "/category/1075750/mens-perfume.html",
    )


# ============================================================
# TARGETED CATEGORY SEEDS
# ============================================================

def _targeted_category_seed_urls(
    query,
):
    q = norm(
        query
    )

    seeds = []

    # --------------------------------------------------------
    # Liquid Brun
    # --------------------------------------------------------

    if "liquid brun" in q:

        seeds.append(
            BASE_URL
            + "/en/category/1132834/liquid-brun.html"
        )

    # --------------------------------------------------------
    # French Avenue
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Dedup
    # --------------------------------------------------------

    seen = set()
    output = []

    for url in seeds:

        if url in seen:
            continue

        seen.add(url)
        output.append(url)

    return output


# ============================================================
# DISCOVER FROM CATEGORIES
# ============================================================

def _discover_from_categories(
    session,
    query,
    max_urls=80,
):

    urls = []
    seen = set()

    for category_url in _category_pages(
        session
    ):

        try:
            r = session.get(
                category_url,
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

        candidate_pages = (
            product_line_links
            or [category_url]
        )

        for page_url in candidate_pages:

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

            for product_url in _candidate_product_urls(
                page.text,
                query,
                accept_all_products=(
                    page_url != category_url
                ),
            ):

                if product_url in seen:
                    continue

                seen.add(
                    product_url
                )

                urls.append(
                    product_url
                )

                if len(urls) >= max_urls:
                    return urls[:max_urls]

    return urls[:max_urls]


# ============================================================
# SITEMAP CATEGORY DISCOVERY
# ============================================================

def _sitemap_category_urls(
    session,
    query,
    max_sitemaps=12,
    max_urls=30,
):

    query_tokens = tokens(
        query
    )

    if not query_tokens:
        return []

    sitemap_roots = (
        BASE_URL
        + "/sitemap.xml",

        BASE_URL
        + "/sitemap_index.xml",

        BASE_URL
        + "/sitemap-index.xml",

        BASE_URL
        + "/en/sitemap.xml",
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

        sitemap_url = pending.pop(
            0
        )

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

                    if value in seen_categories:
                        continue

                    seen_categories.add(
                        value
                    )

                    category_urls.append(
                        value
                    )

                    if len(category_urls) >= max_urls:
                        break

            elif (
                low.endswith(".xml")
                or "sitemap" in low
            ):

                if value not in seen_sitemaps:
                    pending.append(
                        value
                    )

    return category_urls[:max_urls]


# ============================================================
# SITEMAP PRODUCT DISCOVERY
# ============================================================

def _sitemap_product_urls(
    session,
    query,
    max_sitemaps=12,
    max_urls=80,
):

    query_tokens = tokens(
        query
    )

    if not query_tokens:
        return []

    sitemap_roots = (
        BASE_URL
        + "/sitemap.xml",

        BASE_URL
        + "/sitemap_index.xml",

        BASE_URL
        + "/sitemap-index.xml",

        BASE_URL
        + "/en/sitemap.xml",
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

        sitemap_url = pending.pop(
            0
        )

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

            if "/product/" in low:

                if query_tokens.issubset(
                    tokens(value)
                ):

                    if value in seen_products:
                        continue

                    seen_products.add(
                        value
                    )

                    product_urls.append(
                        value
                    )

                    if len(product_urls) >= max_urls:
                        break

            elif (
                low.endswith(".xml")
                or "sitemap" in low
            ):

                if value not in seen_sitemaps:
                    pending.append(
                        value
                    )

    return product_urls


# ============================================================
# MAIN DISCOVERY
# ============================================================

def _discover(
    session,
    q,
):

    urls = []
    seen = set()

    # ========================================================
    # 1. DIRECT PRODUCT URL
    # ========================================================
    #
    # QUESTO È IL CAMBIAMENTO PRINCIPALE.
    #
    # Hawas For Him viene trovato immediatamente senza passare
    # dalle categorie generiche.
    #
    # ========================================================

    for url in _targeted_product_urls(
        q
    ):

        if url in seen:
            continue

        seen.add(url)
        urls.append(url)

    if urls:
        return urls[:80]

    # ========================================================
    # 2. CURRENT CATEGORY / PRODUCT LINE
    # ========================================================

    for url in _discover_from_categories(
        session,
        q,
        max_urls=80,
    ):

        if url in seen:
            continue

        seen.add(url)
        urls.append(url)

        if len(urls) >= 80:
            return urls[:80]

    # ========================================================
    # 3. TARGETED CATEGORY SEEDS
    # ========================================================

    for category_url in _targeted_category_seed_urls(
        q
    ):

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

        for product_url in _candidate_product_urls(
            page.text,
            q,
        ):

            if product_url in seen:
                continue

            seen.add(
                product_url
            )

            urls.append(
                product_url
            )

            if len(urls) >= 80:
                return urls[:80]

    # ========================================================
    # 4. CATEGORY PAGES FROM SITEMAP
    # ========================================================

    for category_url in _sitemap_category_urls(
        session,
        q,
        max_sitemaps=12,
        max_urls=30,
    ):

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

        for product_url in _candidate_product_urls(
            page.text,
            q,
        ):

            if product_url in seen:
                continue

            seen.add(
                product_url
            )

            urls.append(
                product_url
            )

            if len(urls) >= 80:
                return urls[:80]

    # ========================================================
    # 5. PROGRESSIVE SEARCH FALLBACK
    # ========================================================

    for discovery_query in _candidate_queries(
        q
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
            except requests.RequestException:
                continue

            if r.status_code >= 400:
                continue

            for url in _candidate_product_urls(
                r.text,
                q,
                discovery_query=discovery_query,
            ):

                if url in seen:
                    continue

                seen.add(
                    url
                )

                urls.append(
                    url
                )

                if len(urls) >= 80:
                    return urls[:80]

    # ========================================================
    # 6. LEGACY SEARCH
    # ========================================================

    endpoints = [
        BASE_URL
        + "/en/search?query="
        + quote_plus(q),

        BASE_URL
        + "/en/search?search="
        + quote_plus(q),

        BASE_URL
        + "/en?search="
        + quote_plus(q),

        BASE_URL
        + "/en/search?q="
        + quote_plus(q),
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

        for url in _candidate_product_urls(
            r.text,
            q,
        ):

            if url in seen:
                continue

            seen.add(
                url
            )

            urls.append(
                url
            )

        if len(urls) >= 80:
            return urls[:80]

    # ========================================================
    # 7. LAST RESORT - PRODUCT SITEMAP
    # ========================================================

    if not urls:

        for url in _sitemap_product_urls(
            session,
            q,
            max_sitemaps=12,
            max_urls=80,
        ):

            if url in seen:
                continue

            seen.add(
                url
            )

            urls.append(
                url
            )

            if len(urls) >= 80:
                break

    return urls[:80]


# ============================================================
# DIAGNOSTIC
# ============================================================

def diagnose_search(
    session,
    query,
):
    """
    Discovery trace diagnostica.

    Mostra:
    - URL prodotto diretto
    - categorie
    - filter URLs
    - candidate URLs
    - prodotti validati
    - vecchi endpoint search
    """

    query = clean(
        query
    )

    report = {
        "query": query,

        "direct_product_urls": (
            _targeted_product_urls(
                query
            )
        ),

        "category_endpoints": [],

        "filter_urls": [],

        "candidate_urls": [],

        "validated_products": [],

        "search_fallback": [],
    }

    if not query:
        return report

    # ========================================================
    # DIRECT PRODUCT
    # ========================================================

    seen_candidates = set()

    for direct_url in report[
        "direct_product_urls"
    ]:

        try:
            r = session.get(
                direct_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:

            report[
                "direct_product_error"
            ] = str(exc)

            continue

        report[
            "direct_product_status"
        ] = r.status_code

        if r.status_code < 400:

            item = _product(
                direct_url,
                r.text,
                query,
            )

            if item:
                report[
                    "validated_products"
                ].append(
                    item
                )

    # ========================================================
    # CATEGORIES
    # ========================================================

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

            entry[
                "status"
            ] = r.status_code

        except requests.RequestException as exc:

            entry[
                "error"
            ] = str(exc)

            report[
                "category_endpoints"
            ].append(
                entry
            )

            continue

        report[
            "category_endpoints"
        ].append(
            entry
        )

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
        ] = filter_urls[:20]

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
                candidates[:40]
            )

            for u in candidates:

                if u in seen_candidates:
                    continue

                seen_candidates.add(
                    u
                )

                report[
                    "candidate_urls"
                ].append(
                    u
                )

                if len(
                    report[
                        "candidate_urls"
                    ]
                ) >= 80:
                    break

            if len(
                report[
                    "candidate_urls"
                ]
            ) >= 80:
                break

        if len(
            report[
                "candidate_urls"
            ]
        ) >= 80:
            break

    # ========================================================
    # VALIDATE CANDIDATES
    # ========================================================

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
            ].append(
                item
            )

    # ========================================================
    # OLD SEARCH ENDPOINTS
    # ========================================================

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


# ============================================================
# SEARCH
# ============================================================

def search(query):

    query = clean(
        query
    )

    if not query:
        return []

    session = requests.Session()

    results = []

    seen = set()

    try:

        # ----------------------------------------------------
        # DISCOVERY
        # ----------------------------------------------------

        discovered_urls = _discover(
            session,
            query,
        )

        # ----------------------------------------------------
        # FETCH + PARSE
        # ----------------------------------------------------

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

            sku_value = None

            sku = item[
                "identity"
            ].get(
                "sku"
            )

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


# ============================================================
# SCRAPE ALIAS
# ============================================================

def scrape(query):
    return search(
        query
    )


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "query"
    )

    args = parser.parse_args()

    print(
        json.dumps(
            search(
                args.query
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
