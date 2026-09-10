"""
ScentHunter - Sabina adapter
Fast, bounded, query-driven discovery with parallel product extraction.

Sabina is a PrestaShop-style storefront. The adapter deliberately keeps
discovery generic and moves product identity decisions out of the scraper.

Live-search strategy:
1. Warm up the Sabina storefront session.
2. Try first-party search/AJAX routes.
3. If first-party discovery is empty, use a bounded public-index fallback.
4. Fetch product pages in parallel.
5. Extract product/variant data from JSON-LD and page HTML.
6. Keep explicit out-of-stock products; never turn unknown into false.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import (
    parse_qs,
    quote_plus,
    unquote,
    urljoin,
    urlparse,
)

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:
    sync_playwright = None
    PlaywrightTimeoutError = Exception


STORE = "Sabina"
BASE = "https://www.sabina.com"

CONNECT_TIMEOUT = 1.5
READ_TIMEOUT = 3.5
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

MAX_CANDIDATES = 6
PRODUCT_WORKERS = 6
MAX_EXTERNAL_RESULTS = 0
MAX_VARIANT_ROWS = 80
BROWSER_TIMEOUT_MS = 9000
BROWSER_WAIT_MS = 1200

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/json;"
        "q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": BASE + "/es/",
}

PRICE_RE = re.compile(
    r"(?:€|\$|£)\s*"
    r"(\d{1,5}(?:[.,]\d{2})?)"
    r"|(?<!\d)"
    r"(\d{1,5}(?:[.,]\d{2})?)\s*"
    r"(?:€|\$|£)",
    re.I,
)

SIZE_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*"
    r"(ml|cl|dl|l)\b",
    re.I,
)

PRODUCT_URL_RE = re.compile(
    r"^https?://(?:www\.)?sabina\.com/"
    r"(?:it|fr|en|es|de|pt)/"
    r"(?!content|ricerca|ricerca_old|"
    r"buscar|buscar_old|search|marchi|"
    r"negozi|contatto|faq|carrello|"
    r"ordine|stato-ordine|il-mio-conto|"
    r"module|modules)",
    re.I,
)

NON_PRODUCT_TERMS = {
    "gift set",
    "giftset",
    "geschenkset",
    "set",
    "coffret",
    "duo",
    "trio",
    "tester",
    "sample",
    "muestra",
    "miniature",
    "mini",
    "travel size",
    "travel-size",
    "after shave",
    "aftershave",
    "deodorant",
    "shampoo",
    "body lotion",
    "body cream",
    "cream",
    "crema",
    "serum",
    "makeup",
    "make up",
}

OUT_MARKERS = (
    "out of stock",
    "sold out",
    "unavailable",
    "not available",
    "not available in this combination",
    "producto no disponible",
    "producto agotado",
    "sin stock",
    "agotado",
    "no disponible",
    "nicht verfügbar",
    "ausverkauft",
)

IN_MARKERS = (
    "in stock",
    "available",
    "available now",
    "add to cart",
    "añadir al carrito",
    "en stock",
    "disponible",
    "disponibilidad inmediata",
    "auf lager",
)

CURRENCY_MAP = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
}


def _clean(value):
    return re.sub(
        r"\s+",
        " ",
        html_lib.unescape(
            str(value or "")
        ),
    ).strip()


def _norm(value):
    text = _clean(value).casefold()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(
        r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)",
        " ",
        text,
    )
    text = re.sub(
        r"[^a-z0-9à-ÿäöüß]+",
        " ",
        text,
    )
    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def _tokens(value):
    return [
        token
        for token in re.findall(
            r"[a-z0-9à-ÿäöüß]+",
            _norm(value),
        )
        if len(token) > 1
    ]


def _price_number(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        return (
            round(number, 2)
            if 0 < number < 100000
            else None
        )

    raw = _clean(value)
    raw = raw.replace("\xa0", " ")

    # European and plain decimal formats:
    # 1.234,56 -> 1234.56
    # 24,95 -> 24.95
    # 1234.56 -> 1234.56
    match = re.search(
        r"(?<!\d)"
        r"(\d{1,3}(?:\.\d{3})*,\d{2}"
        r"|\d+(?:,\d{2})"
        r"|\d+(?:\.\d{2}))"
        r"(?!\d)",
        raw,
    )

    if not match:
        return None

    number = match.group(1)

    if "," in number:
        if "." in number:
            number = number.replace(".", "")
        number = number.replace(",", ".")

    try:
        result = float(number)
    except ValueError:
        return None

    return (
        round(result, 2)
        if 0 < result < 100000
        else None
    )


def _price(value):
    number = _price_number(value)

    if number is None:
        return None

    return (
        f"{number:.2f}".replace(
            ".",
            ",",
        )
        + " €"
    )


def _size_ml(value):
    match = SIZE_RE.search(
        _clean(value)
    )

    if not match:
        return None

    try:
        number = float(
            match.group(1).replace(
                ",",
                ".",
            )
        )
    except ValueError:
        return None

    unit = match.group(2).lower()

    if unit == "cl":
        number *= 10
    elif unit == "dl":
        number *= 100
    elif unit == "l":
        number *= 1000

    return (
        int(number)
        if number.is_integer()
        else number
    )


def _concentration(value):
    text = _norm(value)

    if (
        "eau de toilette" in text
        or re.search(r"\bedt\b", text)
    ):
        return "Eau de Toilette"

    if (
        "eau de parfum" in text
        or re.search(r"\bedp\b", text)
    ):
        return "Eau de Parfum"

    if (
        "extrait de parfum" in text
        or re.search(r"\bextrait\b", text)
    ):
        return "Extrait de Parfum"

    if re.search(
        r"\bparfum\b",
        text,
    ):
        return "Parfum"

    return ""


def _availability_from_value(value):
    text = _norm(value)

    if not text:
        return None

    if any(
        marker in text
        for marker in OUT_MARKERS
    ):
        return "out_of_stock"

    if any(
        marker in text
        for marker in IN_MARKERS
    ):
        return "in_stock"

    compact = text.replace(
        " ",
        "",
    )

    if (
        "outofstock" in compact
        or "soldout" in compact
    ):
        return "out_of_stock"

    if (
        "instock" in compact
        or "limitedavailability"
        in compact
    ):
        return "in_stock"

    return None


def _looks_like_product_url(url):
    return bool(
        url
        and PRODUCT_URL_RE.match(
            url
        )
    )


def _clean_product_url(url):
    if not url:
        return ""

    value = html_lib.unescape(
        str(url)
    ).strip()

    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = urljoin(
            BASE,
            value,
        )
    elif not re.match(
        r"^https?://",
        value,
        re.I,
    ):
        value = urljoin(
            BASE + "/",
            value,
        )

    parsed = urlparse(value)

    host = parsed.netloc.lower().split(
        ":",
        1,
    )[0]

    if host not in {
        "sabina.com",
        "www.sabina.com",
    }:
        return ""

    clean = parsed._replace(
        netloc="www.sabina.com",
        query="",
        fragment="",
    ).geturl()

    return (
        clean
        if _looks_like_product_url(clean)
        else ""
    )


def _query_matches(
    name,
    url,
    query,
):
    """
    Match against both visible product name and URL.

    Sabina product slugs can contain the brand while the visible card
    title is abbreviated, so both signals are considered.
    """
    q_words = [
        word
        for word in _tokens(query)
        if len(word) > 1
    ]

    if not q_words:
        return False

    haystack = _norm(
        f"{name} {url.replace('-', ' ')}"
    )

    return all(
        word in haystack
        for word in q_words
    )


def _contains_non_product_term(
    name,
    url="",
):
    haystack = _norm(
        f"{name} {url.replace('-', ' ')}"
    )

    for term in NON_PRODUCT_TERMS:
        if _norm(term) in haystack:
            return True

    return False


def _jsonld_objects(soup):
    objects = []

    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        raw = (
            script.string
            or script.get_text()
        )

        if not raw:
            continue

        try:
            data = json.loads(
                raw
            )
        except Exception:
            continue

        queue = [data]

        while queue:
            item = queue.pop(0)

            if isinstance(
                item,
                list,
            ):
                queue.extend(item)
                continue

            if not isinstance(
                item,
                dict,
            ):
                continue

            objects.append(item)

            graph = item.get(
                "@graph"
            )

            if isinstance(
                graph,
                list,
            ):
                queue.extend(graph)

    return objects


def _jsonld_product(soup):
    for item in _jsonld_objects(
        soup
    ):
        typ = item.get(
            "@type"
        )

        types = (
            typ
            if isinstance(
                typ,
                list,
            )
            else [typ]
        )

        if (
            "Product" in types
            or "ProductGroup" in types
        ):
            return item

    return {}


def _jsonld_products(soup):
    products = []

    for item in _jsonld_objects(
        soup
    ):
        typ = item.get(
            "@type"
        )

        types = (
            typ
            if isinstance(
                typ,
                list,
            )
            else [typ]
        )

        if (
            "Product" in types
            or "ProductGroup" in types
        ):
            products.append(item)

    return products


def _jsonld_value(
    data,
    *keys,
):
    if not isinstance(
        data,
        dict,
    ):
        return None

    for key in keys:
        value = data.get(
            key
        )

        if isinstance(
            value,
            dict,
        ):
            value = (
                value.get("name")
                or value.get("value")
                or value.get("content")
            )

        if isinstance(
            value,
            list,
        ):
            if value:
                first = value[0]

                if isinstance(
                    first,
                    dict,
                ):
                    value = (
                        first.get("name")
                        or first.get("value")
                    )
                else:
                    value = first

        if (
            value is not None
            and str(value).strip()
        ):
            return _clean(value)

    return None


def _offer_objects(
    product,
):
    offers = (
        product.get("offers")
        if isinstance(
            product,
            dict,
        )
        else None
    )

    if isinstance(
        offers,
        dict,
    ):
        return [offers]

    if isinstance(
        offers,
        list,
    ):
        return [
            offer
            for offer in offers
            if isinstance(
                offer,
                dict,
            )
        ]

    return []


def _offer_price(
    offer,
):
    if not isinstance(
        offer,
        dict,
    ):
        return None

    for key in (
        "price",
        "lowPrice",
        "salePrice",
        "finalPrice",
    ):
        number = _price_number(
            offer.get(key)
        )

        if number is not None:
            return number

    specification = offer.get(
        "priceSpecification"
    )

    if isinstance(
        specification,
        dict,
    ):
        return _price_number(
            specification.get(
                "price"
            )
        )

    if isinstance(
        specification,
        list,
    ):
        for item in specification:
            if not isinstance(
                item,
                dict,
            ):
                continue

            number = _price_number(
                item.get("price")
            )

            if number is not None:
                return number

    return None


def _offer_availability(
    offer,
):
    if not isinstance(
        offer,
        dict,
    ):
        return None

    return _availability_from_value(
        offer.get(
            "availability"
        )
        or offer.get(
            "itemAvailability"
        )
        or offer.get(
            "availabilityStatus"
        )
    )


def _extract_brand(
    product,
    soup,
):
    brand = _jsonld_value(
        product,
        "brand",
        "manufacturer",
    )

    if brand:
        return brand

    meta = soup.select_one(
        'meta[property="product:brand"], '
        'meta[name="brand"]'
    )

    if meta:
        return _clean(
            meta.get("content")
        )

    return None


def _extract_image(
    product,
    soup,
):
    image = product.get(
        "image"
    ) if isinstance(
        product,
        dict,
    ) else None

    if isinstance(
        image,
        dict,
    ):
        image = (
            image.get("url")
            or image.get("contentUrl")
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
        return urljoin(
            BASE,
            str(image),
        )

    meta = soup.select_one(
        'meta[property="og:image"], '
        'meta[name="twitter:image"]'
    )

    if meta and meta.get(
        "content"
    ):
        return urljoin(
            BASE,
            meta.get("content"),
        )

    return None


def _extract_gtin(
    product,
):
    return _jsonld_value(
        product,
        "gtin13",
        "gtin12",
        "gtin14",
        "gtin",
        "ean",
    )


def _extract_size_from_product(
    product,
    title="",
):
    # Do not invent a size. Use explicit product structured data or title.
    for key in (
        "size",
        "volume",
        "netContent",
        "capacity",
        "contentVolume",
    ):
        value = _jsonld_value(
            product,
            key,
        )

        size = _size_ml(
            value
        )

        if size is not None:
            return size, (
                f"jsonld_{key}"
            )

    size = _size_ml(
        title
    )

    if size is not None:
        return size, "product_title"

    return None, None


def _extract_product_name(
    product,
    soup,
):
    name = _jsonld_value(
        product,
        "name",
        "productName",
        "title",
    )

    if name:
        return name

    h1 = soup.find(
        "h1"
    )

    if h1:
        return _clean(
            h1.get_text(
                " ",
                strip=True,
            )
        )

    title = soup.find(
        "title"
    )

    if title:
        return _clean(
            title.get_text(
                " ",
                strip=True,
            )
        )

    return ""


def _availability_from_product(
    product,
    soup,
):
    values = []

    for offer in _offer_objects(
        product
    ):
        value = _offer_availability(
            offer
        )

        if value:
            values.append(
                value
            )

    if "in_stock" in values:
        return (
            "in_stock",
            "jsonld",
        )

    if "out_of_stock" in values:
        return (
            "out_of_stock",
            "jsonld",
        )

    page_text = _norm(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    page_state = (
        _availability_from_value(
            page_text
        )
    )

    if page_state:
        return (
            page_state,
            "page_text",
        )

    return (
        "unknown",
        "not_explicit",
    )


def _extract_price_and_currency(
    product,
    soup,
):
    for offer in _offer_objects(
        product
    ):
        price = _offer_price(
            offer
        )

        if price is None:
            continue

        currency = (
            offer.get(
                "priceCurrency"
            )
            or "EUR"
        )

        return (
            price,
            str(currency).upper(),
            "jsonld_offer",
        )

    for selector in (
        'meta[property="product:price:amount"]',
        'meta[itemprop="price"]',
        'meta[name="price"]',
    ):
        node = soup.select_one(
            selector
        )

        if not node:
            continue

        price = _price_number(
            node.get("content")
            or node.get_text(
                " ",
                strip=True,
            )
        )

        if price is not None:
            currency = (
                soup.select_one(
                    'meta[property="product:price:currency"], '
                    'meta[itemprop="priceCurrency"]'
                )
            )

            return (
                price,
                (
                    currency.get("content")
                    if currency
                    else "EUR"
                ),
                "meta",
            )

    selectors = (
        '[itemprop="price"]',
        '[data-price]',
        '[data-product-price]',
        ".product-price",
        ".current-price",
        ".current_price",
        ".sale-price",
        ".final-price",
    )

    candidates = []

    for selector in selectors:
        for node in soup.select(
            selector
        ):
            marker = (
                " ".join(
                    node.get(
                        "class",
                        [],
                    )
                ).lower()
                + " "
                + str(
                    node.get(
                        "id",
                        "",
                    )
                ).lower()
            )

            parent_text = (
                node.parent.get_text(
                    " ",
                    strip=True,
                ).lower()
                if node.parent
                else ""
            )

            if any(
                bad in marker
                for bad in (
                    "old-price",
                    "regular-price",
                    "compare",
                    "cross",
                    "coupon",
                    "discount",
                )
            ):
                continue

            if any(
                bad in parent_text
                for bad in (
                    "old price",
                    "was ",
                    "before ",
                    "per liter",
                    "€/l",
                )
            ):
                continue

            price = _price_number(
                node.get("content")
                or node.get("data-price")
                or node.get(
                    "data-product-price"
                )
                or node.get_text(
                    " ",
                    strip=True,
                )
            )

            if price is None:
                continue

            score = 0

            if (
                "current" in marker
                or "final" in marker
                or "sale" in marker
            ):
                score += 20

            if (
                "product" in marker
            ):
                score += 10

            candidates.append(
                (
                    score,
                    len(candidates),
                    price,
                )
            )

    if candidates:
        # Keep DOM order for equal-confidence price nodes. Sorting by the
        # numeric price was wrong on Sabina because related-product cards can
        # contain cheaper prices and were therefore selected over the main
        # product price.
        candidates.sort(
            key=lambda row: (
                -row[0],
                row[1],
            )
        )

        return (
            candidates[0][2],
            "EUR",
            "semantic_html",
        )

    return (
        None,
        "EUR",
        None,
    )


def _extract_variant_rows(
    soup,
    product,
    base_name,
    base_url,
):
    """
    Extract explicit size/price combinations.

    The critical rule is that size and price must come from the same
    variant/option block whenever the page exposes variants. We never
    pair every size on a page with the first price on that page.
    """
    rows = []

    # JSON-LD ProductGroup / hasVariant.
    variants = product.get(
        "hasVariant"
    ) if isinstance(
        product,
        dict,
    ) else None

    if isinstance(
        variants,
        dict,
    ):
        variants = [variants]

    if isinstance(
        variants,
        list,
    ):
        for variant in variants:
            if not isinstance(
                variant,
                dict,
            ):
                continue

            name = (
                _jsonld_value(
                    variant,
                    "name",
                )
                or base_name
            )

            size, size_source = (
                _extract_size_from_product(
                    variant,
                    name,
                )
            )

            price = None
            currency = "EUR"

            for offer in _offer_objects(
                variant
            ):
                price = _offer_price(
                    offer
                )

                if price is not None:
                    currency = str(
                        offer.get(
                            "priceCurrency"
                        )
                        or "EUR"
                    ).upper()
                    break

            availability = None

            for offer in _offer_objects(
                variant
            ):
                availability = (
                    _offer_availability(
                        offer
                    )
                    or availability
                )

            if (
                size is not None
                or price is not None
                or availability
            ):
                rows.append(
                    {
                        "name": name,
                        "size_ml": size,
                        "size_source": size_source,
                        "price": price,
                        "currency": currency,
                        "availability": (
                            availability
                            or "unknown"
                        ),
                        "url": (
                            _jsonld_value(
                                variant,
                                "url",
                            )
                            or base_url
                        ),
                        "sku": _jsonld_value(
                            variant,
                            "sku",
                        ),
                    }
                )

    # Generic DOM variant blocks.
    variant_selectors = (
        "[data-product-attribute]",
        "[data-product-variant]",
        "[data-variant]",
        ".product-variants-item",
        ".product-variants",
        ".product-variant",
        ".variant-item",
        ".variant",
        ".attribute",
    )

    seen_blocks = set()

    for selector in variant_selectors:
        for block in soup.select(
            selector
        ):
            marker = str(
                block
            )[:1000]

            if marker in seen_blocks:
                continue

            seen_blocks.add(
                marker
            )

            text = _clean(
                block.get_text(
                    " ",
                    strip=True,
                )
            )

            size = _size_ml(
                text
            )

            if size is None:
                continue

            price = None

            # Price is read only inside this same block.
            for node in block.select(
                '[itemprop="price"],'
                '[data-price],'
                '[data-product-price],'
                ".price,"
                ".product-price,"
                ".current-price,"
                ".sale-price"
            ):
                price = _price_number(
                    node.get(
                        "content"
                    )
                    or node.get(
                        "data-price"
                    )
                    or node.get_text(
                        " ",
                        strip=True,
                    )
                )

                if price is not None:
                    break

            availability = (
                _availability_from_value(
                    text
                )
                or "unknown"
            )

            if (
                price is not None
                or availability
                != "unknown"
            ):
                rows.append(
                    {
                        "name": base_name,
                        "size_ml": size,
                        "size_source": "variant_block",
                        "price": price,
                        "currency": "EUR",
                        "availability": availability,
                        "url": base_url,
                        "sku": None,
                    }
                )

    # De-duplicate variant rows.
    output = []
    seen = set()

    for row in rows:
        key = (
            row.get("size_ml"),
            row.get("price"),
            row.get("availability"),
            row.get("url"),
            row.get("sku"),
        )

        if key in seen:
            continue

        seen.add(key)
        output.append(row)

        if len(output) >= MAX_VARIANT_ROWS:
            break

    return output


def _extract_product_page(
    url,
    query,
):
    session = requests.Session()
    session.headers.update(
        HEADERS
    )

    try:
        try:
            response = session.get(
                url,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            return []

        try:
            if response.status_code in (
                403,
                429,
            ):
                return []

            if response.status_code != 200:
                return []

            html_text = response.text
            final_url = _clean_product_url(
                response.url
            ) or url
        finally:
            response.close()

        soup = BeautifulSoup(
            html_text,
            "html.parser",
        )

        product = _jsonld_product(
            soup
        )

        title = _extract_product_name(
            product,
            soup,
        )

        if not title:
            return []

        if not _query_matches(
            title,
            final_url,
            query,
        ):
            return []

        if _contains_non_product_term(
            title,
            final_url,
        ):
            return []

        brand = _extract_brand(
            product,
            soup,
        )

        price, currency, price_source = (
            _extract_price_and_currency(
                product,
                soup,
            )
        )

        availability, availability_source = (
            _availability_from_product(
                product,
                soup,
            )
        )

        size, size_source = (
            _extract_size_from_product(
                product,
                title,
            )
        )

        concentration = _concentration(
            title
        )

        image = _extract_image(
            product,
            soup,
        )

        gtin = _extract_gtin(
            product
        )

        mpn = _jsonld_value(
            product,
            "mpn",
        )

        sku = _jsonld_value(
            product,
            "sku",
        )

        product_id = (
            _jsonld_value(
                product,
                "productID",
                "productId",
            )
            or sku
        )

        variant_rows = (
            _extract_variant_rows(
                soup,
                product,
                title,
                final_url,
            )
        )

        output = []

        # If explicit variant data exists, emit the real size/price
        # combinations rather than mixing page-level values.
        if variant_rows:
            for variant in variant_rows:
                variant_size = variant.get(
                    "size_ml"
                )

                variant_price = variant.get(
                    "price"
                )

                variant_availability = (
                    variant.get(
                        "availability"
                    )
                    or availability
                )

                if (
                    variant_size is None
                    and size is not None
                ):
                    variant_size = size

                if (
                    variant_price is None
                    and not variant_rows
                ):
                    variant_price = price

                if (
                    variant_price is None
                    and variant_availability
                    == "unknown"
                ):
                    continue

                variant_url = (
                    _clean_product_url(
                        variant.get(
                            "url"
                        )
                    )
                    or final_url
                )

                variant_sku = (
                    variant.get("sku")
                    or sku
                )

                output.append(
                    _build_result(
                        title=(
                            variant.get(
                                "name"
                            )
                            or title
                        ),
                        brand=brand,
                        price=variant_price,
                        currency=(
                            variant.get(
                                "currency"
                            )
                            or currency
                        ),
                        availability=(
                            variant_availability
                        ),
                        availability_source=(
                            availability_source
                            if variant_availability
                            == availability
                            else "variant"
                        ),
                        size_ml=variant_size,
                        size_source=(
                            variant.get(
                                "size_source"
                            )
                            or size_source
                        ),
                        concentration=concentration,
                        image=image,
                        gtin=gtin,
                        mpn=mpn,
                        sku=variant_sku,
                        product_id=product_id,
                        url=variant_url,
                        price_source=(
                            price_source
                            if variant_price
                            == price
                            else "variant"
                        ),
                    )
                )

            # If variants were found but none survived, do not fabricate
            # a page-level offer.
            return [
                item
                for item in output
                if item
            ]

        # Normal single-offer product page.
        if (
            price is None
            and availability
            == "unknown"
        ):
            return []

        return [
            _build_result(
                title=title,
                brand=brand,
                price=price,
                currency=currency,
                availability=availability,
                availability_source=availability_source,
                size_ml=size,
                size_source=size_source,
                concentration=concentration,
                image=image,
                gtin=gtin,
                mpn=mpn,
                sku=sku,
                product_id=product_id,
                url=final_url,
                price_source=price_source,
            )
        ]

    finally:
        session.close()


def _build_result(
    *,
    title,
    brand,
    price,
    currency,
    availability,
    availability_source,
    size_ml,
    size_source,
    concentration,
    image,
    gtin,
    mpn,
    sku,
    product_id,
    url,
    price_source,
):
    price_text = (
        _price(price)
        if price is not None
        else None
    )

    return {
        "store": STORE,

        "source": {
            "source_name": title,
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
                    "value": product_id,
                    "source": "product_url_or_jsonld",
                }
                if product_id
                else None
            ),
            "store_variant_id": None,
        },

        "attributes": {
            "size_ml": (
                {
                    "value": size_ml,
                    "source": size_source,
                }
                if size_ml is not None
                else None
            ),
            "concentration": (
                {
                    "value": concentration,
                    "source": "product_title",
                }
                if concentration
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
        },

        "offer": {
            "price": price,
            "currency": (
                str(
                    currency
                    or "EUR"
                ).upper()
            ),
            "availability": availability,
        },

        "provenance": {
            "name": "sabina_jsonld_or_h1",
            "brand": (
                "sabina_jsonld"
                if brand
                else None
            ),
            "price": price_source,
            "availability": availability_source,
            "image": (
                "sabina_jsonld"
                if image
                else None
            ),
            "store_product_id": (
                "product_url_or_jsonld"
                if product_id
                else None
            ),
            "sku": (
                "sabina_jsonld"
                if sku
                else None
            ),
            "gtin": (
                "sabina_jsonld"
                if gtin
                else None
            ),
            "mpn": (
                "sabina_jsonld"
                if mpn
                else None
            ),
            "size_ml": size_source,
            "concentration": (
                "product_title"
                if concentration
                else None
            ),
            "gender": "not_explicit",
            "packaging_type": "default",
        },

        "raw_data": {
            "product_url": url,
            "jsonld_product": {},
        },

        # Compatibility with current main.py.
        "name": title,
        "brand": brand,
        "price": price_text,
        "price_num": price,
        "url": url,
        "available": (
            True
            if availability == "in_stock"
            else False
            if availability
            == "out_of_stock"
            else None
        ),
        "availability": availability,
        "size_ml": size_ml,
        "size": (
            f"{int(size_ml)} ml"
            if size_ml is not None
            and float(size_ml).is_integer()
            else (
                f"{size_ml} ml"
                if size_ml is not None
                else None
            )
        ),
        "concentration": concentration,
        "image": image,
        "gtin": gtin,
        "mpn": mpn,
        "sku": sku,
        "store_product_id": product_id,
    }


def _extract_product_links_from_html(
    text,
    query,
):
    """
    Generic first-party discovery.

    A candidate is accepted when the query tokens are present either in
    the product slug or in the small product-card context. Large parent
    containers are deliberately ignored.
    """
    soup = BeautifulSoup(
        text or "",
        "html.parser",
    )

    found = []
    seen = set()

    tokens = [
        token
        for token in _tokens(query)
        if len(token) > 1
    ]

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        url = _clean_product_url(
            anchor.get(
                "href"
            )
        )

        if not url:
            continue

        url_hay = _norm(
            url.replace(
                "-",
                " ",
            )
        )

        url_match = (
            bool(tokens)
            and all(
                token in url_hay
                for token in tokens
            )
        )

        text_candidates = [
            _clean(
                anchor.get("title")
            ),
            _clean(
                anchor.get("aria-label")
            ),
            _clean(
                anchor.get_text(
                    " ",
                    strip=True,
                )
            ),
        ]

        container = anchor

        for _ in range(4):
            container = getattr(
                container,
                "parent",
                None,
            )

            if not container:
                break

            classes = " ".join(
                container.get(
                    "class",
                    [],
                )
            )
            marker = (
                classes
                + " "
                + str(
                    container.get(
                        "id",
                        "",
                    )
                )
            ).lower()

            container_text = _clean(
                container.get_text(
                    " ",
                    strip=True,
                )
            )

            if (
                len(container_text)
                <= 700
                and any(
                    term in marker
                    for term in (
                        "product",
                        "item",
                        "card",
                        "result",
                        "ajax_block",
                    )
                )
            ):
                text_candidates.append(
                    container_text
                )
                break

        text_match = any(
            candidate
            and len(candidate) <= 700
            and all(
                token
                in _norm(candidate)
                for token in tokens
            )
            for candidate in text_candidates
        )

        if not tokens or not (
            url_match
            or text_match
        ):
            continue

        if url in seen:
            continue

        seen.add(url)
        found.append(url)

        if len(found) >= MAX_CANDIDATES:
            break

    return found


def _get(
    session,
    url,
    *,
    params=None,
    data=None,
    ajax=False,
):
    headers = dict(
        HEADERS
    )

    if ajax:
        headers[
            "X-Requested-With"
        ] = "XMLHttpRequest"

    try:
        response = session.request(
            "POST"
            if data is not None
            else "GET",
            url,
            params=params,
            data=data,
            headers=headers,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None

    if response.status_code in (
        403,
        429,
    ):
        response.close()
        return None

    if response.status_code >= 400:
        response.close()
        return None

    return response


def _discover_from_first_party(
    session,
    query,
):
    """
    Fast first-party discovery.

    Sabina's normal search response is the authoritative discovery source.
    We try the known first-party routes in order and stop as soon as a route
    returns query-relevant product URLs. Historical/AJAX routes are fallback
    only; they are not needlessly executed after a successful discovery.
    """
    urls = []
    seen = set()
    q = quote_plus(query)

    # One current first-party HTTP route only. Older routes/AJAX endpoints
    # are deliberately not chained here: on Sabina they add long waits without
    # improving discovery when the search is client-rendered.
    search_urls = [
        BASE + "/es/buscar_old?s=" + q,
    ]

    for url in search_urls:
        response = _get(session, url)
        if response is None:
            continue

        try:
            links = _extract_product_links_from_html(
                response.text,
                query,
            )
        finally:
            response.close()

        if not links:
            continue

        for link in links:
            if link in seen:
                continue
            seen.add(link)
            urls.append(link)
            if len(urls) >= MAX_CANDIDATES:
                return urls[:MAX_CANDIDATES]

        # A successful first-party search is enough. Do not spend several
        # additional network round-trips against equivalent legacy routes.
        if urls:
            return urls[:MAX_CANDIDATES]

    # No external search engines and no legacy AJAX cascade: if the
    # first-party HTTP search is client-rendered, the caller immediately
    # switches to the bounded browser discovery path.

    return urls[:MAX_CANDIDATES]

def _extract_search_engine_urls(
    text,
    query,
):
    soup = BeautifulSoup(
        text,
        "html.parser",
    )

    found = []
    seen = set()

    tokens = [
        token
        for token in _tokens(query)
        if len(token) > 1
    ]

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        href = html_lib.unescape(
            str(
                anchor.get(
                    "href"
                )
                or ""
            )
        )

        candidate = href

        parsed = urlparse(
            href
        )

        params = parse_qs(
            parsed.query
        )

        for key in (
            "url",
            "q",
            "uddg",
        ):
            if params.get(key):
                candidate = unquote(
                    params[key][0]
                )
                break

        clean_url = (
            _clean_product_url(
                candidate
            )
        )

        if not clean_url:
            continue

        url_hay = _norm(
            clean_url.replace(
                "-",
                " ",
            )
        )

        anchor_text = _clean(
            anchor.get_text(
                " ",
                strip=True,
            )
        )

        text_hay = _norm(
            anchor_text.replace(
                "-",
                " ",
            )
        )

        if not tokens:
            continue

        if not (
            all(
                token in url_hay
                for token in tokens
            )
            or (
                len(text_hay) <= 500
                and all(
                    token in text_hay
                    for token in tokens
                )
            )
        ):
            continue

        if clean_url in seen:
            continue

        seen.add(clean_url)
        found.append(clean_url)

        if (
            len(found)
            >= MAX_EXTERNAL_RESULTS
        ):
            break

    return found


def _dedupe_results(
    rows,
):
    output = []
    seen = set()

    for row in rows:
        if not row:
            continue

        key = (
            row.get(
                "store_product_id"
            )
            or row.get(
                "url"
            )
        )

        key = (
            key,
            row.get(
                "size_ml"
            ),
            row.get(
                "price_num"
            ),
            row.get(
                "availability"
            ),
        )

        if key in seen:
            continue

        seen.add(key)
        output.append(row)

    return output


def _is_product_url(url):
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc.lower() != "www.sabina.com":
        return False
    path = parsed.path.lower()
    return bool(re.search(r"/\d{4,8}-[^/]+\.html$", path))


def _query_tokens_in_text(query, text):
    tokens = re.findall(r"[a-z0-9]+", _clean(query).lower())
    haystack = _clean(text).lower()
    return bool(tokens) and all(token in haystack for token in tokens if len(token) >= 3)


def _discover_from_browser(query):
    """Discover structural Sabina product URLs from rendered search."""
    if sync_playwright is None:
        return []

    search_url = BASE + "/es/buscar_old?s=" + quote_plus(query)
    found, seen = [], set()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="es-ES",
                extra_http_headers={
                    "Accept-Language": HEADERS["Accept-Language"],
                },
            )
            page = context.new_page()
            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=BROWSER_TIMEOUT_MS,
            )
            try:
                page.wait_for_load_state("networkidle", timeout=3500)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(BROWSER_WAIT_MS)

            hrefs = page.locator("a[href]").evaluate_all(
                """
                anchors => anchors.map(a => ({
                    href: a.href || "",
                    text: a.innerText || a.textContent || ""
                }))
                """
            )
            rendered_html = page.content()
            current_url = page.url

            def add_url(raw):
                if not raw:
                    return
                absolute = urljoin(current_url, raw).split("#", 1)[0]
                if not _is_product_url(absolute) or absolute in seen:
                    return
                seen.add(absolute)
                found.append(absolute)

            for item in hrefs:
                add_url(_clean(item.get("href")))
                if len(found) >= MAX_CANDIDATES:
                    break

            if len(found) < MAX_CANDIDATES:
                for match in re.finditer(r"(?:href=[\"'])([^\"']+)", rendered_html, re.I):
                    add_url(match.group(1))
                    if len(found) >= MAX_CANDIDATES:
                        break

            context.close()
            browser.close()
    except Exception:
        return []

    return found[:MAX_CANDIDATES]


def search(query):
    query = _clean(
        query
    )

    if not query:
        return []

    session = requests.Session()
    session.headers.update(
        HEADERS
    )

    try:
        # Warm-up: establishes cookies/locale before discovery.
        response = _get(
            session,
            BASE + "/es/",
        )

        if response is not None:
            response.close()

        candidate_urls = (
            _discover_from_first_party(
                session,
                query,
            )
        )

        # Sabina's current search can be client-rendered. If HTTP discovery
        # is empty, use the rendered first-party search page. Never depend on
        # Google/Bing/DuckDuckGo for retailer discovery.
        if not candidate_urls:
            candidate_urls = _discover_from_browser(query)

        candidate_urls = list(
            dict.fromkeys(
                candidate_urls
            )
        )[:MAX_CANDIDATES]

    finally:
        session.close()

    if not candidate_urls:
        return []

    results = []

    # Product requests are independent: one slow/broken page cannot
    # block every other candidate.
    with ThreadPoolExecutor(
        max_workers=min(
            PRODUCT_WORKERS,
            len(candidate_urls),
        )
    ) as pool:
        futures = {
            pool.submit(
                _extract_product_page,
                url,
                query,
            ): url
            for url in candidate_urls
        }

        for future in as_completed(
            futures
        ):
            try:
                results.extend(
                    future.result()
                )
            except Exception:
                continue

    results = _dedupe_results(
        results
    )

    def sort_key(item):
        availability = item.get(
            "availability"
        )

        if (
            availability
            == "out_of_stock"
        ):
            state = 2
        elif item.get(
            "price_num"
        ) is not None:
            state = 0
        else:
            state = 1

        price = item.get(
            "price_num"
        )

        try:
            numeric_price = float(
                price
            )
        except (
            TypeError,
            ValueError,
        ):
            numeric_price = float(
                "inf"
            )

        size = item.get(
            "size_ml"
        )

        try:
            numeric_size = float(
                size
            )
        except (
            TypeError,
            ValueError,
        ):
            numeric_size = float(
                "inf"
            )

        return (
            state,
            numeric_price,
            numeric_size,
            str(
                item.get(
                    "name"
                )
                or ""
            ).lower(),
        )

    results.sort(
        key=sort_key
    )

    return results[:80]


def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generic Sabina scraper"
    )
    parser.add_argument(
        "query",
        help="Runtime search query",
    )

    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
