"""Notino adapter for ScentHunter.

Discovery strategy:
- Prefer Notino's real search page through Playwright.
- Fall back to requests + BeautifulSoup when direct HTTP is available.
- Search/category/sitemap discovery is generic.
- Product pages are parsed through JSON-LD/page content.
- No Google/Bing.
- No hardcoded products, prices, brands, or product-specific exceptions.
"""
from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = Exception
    sync_playwright = None


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = f"{BASE_URL}/search.asp?exps={{query}}"
TIMEOUT = int(os.getenv("NOTINO_TIMEOUT_S", "15"))
DEFAULT_TIMEOUT_MS = int(os.getenv("NOTINO_TIMEOUT_MS", "30000"))
BROWSER_ENABLED = os.getenv("NOTINO_BROWSER", "1").lower() not in {
    "0",
    "false",
    "no",
}

LOGGER = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

PRICE_RE = re.compile(
    r"(?<![\d.,])"
    r"((?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.]\d{2})?)"
    r"\s*(?:€|EUR)"
    r"(?!\w)",
    re.IGNORECASE,
)

PRODUCT_PATH_EXCLUSIONS = {
    "search.asp",
    "parfums",
    "parfums-homme",
    "parfums-femme",
    "cosmetiques",
    "maquillage",
    "cheveux",
    "corps",
    "visage",
    "promotions",
    "nouveaux",
    "marques",
    "panier",
    "checkout",
    "login",
    "account",
    "magazine",
    "contact",
}

OUT_OF_STOCK_TERMS = (
    "rupture de stock",
    "en rupture",
    "indisponible",
    "épuisé",
    "epuise",
    "out of stock",
    "sold out",
    "unavailable",
    "not available",
)

IN_STOCK_TERMS = (
    "en stock",
    "disponible",
    "available",
    "in stock",
)


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
    query_tokens = tokens(query)
    return bool(query_tokens) and query_tokens.issubset(tokens(text))


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

    if re.search(r"\bparfum\b", text):
        return "Parfum"

    return None


def _source_value(value, source):
    if value in (None, ""):
        return None
    return {"value": value, "source": source}


def parse_price(value):
    text = clean(value)
    if not text:
        return None

    match = PRICE_RE.search(text)
    if not match:
        return None

    raw = match.group(1).replace(" ", "")

    if raw.count(".") > 1:
        raw = raw.replace(".", "")
    elif "." in raw and "," not in raw:
        raw = raw.replace(".", ",")

    try:
        return round(float(raw.replace(",", ".")), 2)
    except ValueError:
        return None


def availability_from_sources(data, soup):
    """Prefer structured availability; never classify from unrelated page text."""

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

            text = norm(raw)

            if any(term in text for term in (
                "instock",
                "in stock",
                "available",
                "disponible",
                "en stock",
            )):
                return "in_stock"

            if any(term in text for term in (
                "outofstock",
                "out of stock",
                "soldout",
                "sold out",
                "unavailable",
                "not available",
                "indisponible",
                "rupture",
                "epuise",
                "épuisé",
            )):
                return "out_of_stock"

    for tag in soup.select(
        '[itemprop="availability"], '
        'meta[property="product:availability"], '
        'meta[name="availability"]'
    ):
        raw = tag.get("content") or tag.get_text(" ", strip=True)
        text = norm(raw)

        if any(term in text for term in IN_STOCK_TERMS):
            return "in_stock"

        if any(term in text for term in OUT_OF_STOCK_TERMS):
            return "out_of_stock"

    return "unknown"


def _normalise_url(href):
    if not href:
        return None

    href = clean(href)

    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(BASE_URL, href)

    parsed = urlparse(href)

    if parsed.scheme not in {"http", "https"}:
        return None

    if parsed.netloc.lower() not in {
        "notino.fr",
        "www.notino.fr",
    }:
        return None

    path = parsed.path.rstrip("/")

    if not path or path == "/":
        return None

    if path.lower().endswith(
        (".jpg", ".jpeg", ".png", ".webp", ".svg")
    ):
        return None

    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _looks_like_product_url(url):
    parsed = urlparse(url)
    path = parsed.path.strip("/").lower()

    if not path:
        return False

    if "search.asp" in path:
        return False

    first_segment = path.split("/", 1)[0]

    if first_segment in PRODUCT_PATH_EXCLUSIONS:
        return False

    # Product pages commonly expose a /p-<id>/ suffix. Notino also uses
    # canonical product URLs without that suffix, so those are accepted when
    # the path is multi-segment and the final slug is not a known collection
    # endpoint. The product page itself remains the final validator.
    if re.search(r"(?:^|/)p-\d+(?:/|$)", path):
        return True

    segments = [segment for segment in path.split("/") if segment]

    if len(segments) < 2:
        return False

    return segments[-1] not in PRODUCT_PATH_EXCLUSIONS


def _extract_prices(text):
    prices = []

    for match in PRICE_RE.finditer(clean(text)):
        raw = match.group(1).replace(" ", "")

        if raw.count(".") > 1:
            raw = raw.replace(".", "")
        elif "." in raw and "," not in raw:
            raw = raw.replace(".", ",")

        value = f"{raw} €"

        if value not in prices:
            prices.append(value)

    return prices


def _candidate_container(anchor):
    node = anchor

    for _ in range(7):
        if not node:
            break

        text = clean(node.get_text(" ", strip=True))

        if len(text) >= 20 and (
            _extract_prices(text)
            or _has_stock_marker(text)
        ):
            return node

        node = getattr(node, "parent", None)

    return anchor.parent


def _has_stock_marker(text):
    low = clean(text).lower()

    return any(
        marker in low
        for marker in (
            "en stock",
            "disponible",
            "en rupture",
            "rupture de stock",
            "indisponible",
            "épuisé",
            "epuise",
        )
    )


def _name_from_container(container, fallback):
    if container is None:
        return fallback

    for selector in ("h1", "h2", "h3", "h4"):
        element = container.select_one(selector)

        if element:
            text = clean(element.get_text(" ", strip=True))

            if 2 <= len(text) <= 300:
                return text

    anchor = container.find("a", href=True)

    if anchor:
        text = clean(anchor.get_text(" ", strip=True))

        if 2 <= len(text) <= 300:
            return text

    return fallback


def _walk_json_ld(value):
    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from _walk_json_ld(child)

    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_ld(child)


def _parse_json_ld(soup):
    products = []

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        for obj in _walk_json_ld(data):
            obj_type = obj.get("@type")

            if isinstance(obj_type, list):
                is_product = "Product" in obj_type
            else:
                is_product = obj_type == "Product"

            if is_product:
                products.append(obj)

    return products


def _image_from_product(data):
    image = data.get("image") if isinstance(data, dict) else None

    if isinstance(image, list):
        image = image[0] if image else None

    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")

    if not image:
        return None

    return str(image)


def _selected_size(soup, data, h1_name):
    """Extract the actually selected bottle size."""

    visible_sources = [
        h1_name,
        clean(data.get("name")) if isinstance(data, dict) else "",
    ]

    for value in visible_sources:
        match = re.search(
            r"(?<!\d)(\d{1,4})\s*ml\b",
            value,
            re.I,
        )
        if match:
            return int(match.group(1))

    selectors = [
        'input[type="radio"][checked]',
        'input[type="radio"][aria-checked="true"]',
        'input[checked][name*="size" i]',
        'option[selected]',
        '[aria-selected="true"]',
    ]

    for selector in selectors:
        for node in soup.select(selector):
            chunks = [
                node.get("value", ""),
                node.get("aria-label", ""),
                node.get("data-value", ""),
                node.get("data-size", ""),
                node.get_text(" ", strip=True),
            ]

            parent = node.parent
            if parent:
                chunks.append(parent.get_text(" ", strip=True))

            grand = parent.parent if parent else None
            if grand:
                chunks.append(grand.get_text(" ", strip=True))

            blob = " ".join(chunks)

            match = re.search(
                r"(?<!\d)(\d{1,4})\s*ml\b",
                blob,
                re.I,
            )

            if match:
                return int(match.group(1))

    return size_ml(h1_name, data.get("name") if isinstance(data, dict) else "")


def _product(url, html, query):
    soup = BeautifulSoup(html, "html.parser")

    jsonld_products = _parse_json_ld(soup)
    data = jsonld_products[0] if jsonld_products else {}

    h1 = soup.find("h1")
    h1_name = clean(h1.get_text(" ", strip=True)) if h1 else ""

    # The visible H1 is authoritative when present. Do not replace a
    # mismatching product title with another JSON-LD object from the same
    # page: category/family pages can contain several Product objects.
    name = h1_name or clean(data.get("name"))

    if not name or not matches(name, query):
        return None

    text = soup.get_text(" ", strip=True)

    brand = data.get("brand")

    if isinstance(brand, dict):
        brand = brand.get("name")

    offers = data.get("offers")

    if isinstance(offers, list):
        offer_list = [
            x for x in offers
            if isinstance(x, dict)
        ]
    elif isinstance(offers, dict):
        offer_list = [offers]
    else:
        offer_list = []

    offer = next(
        (
            x for x in offer_list
            if x.get("price") is not None
        ),
        {},
    )

    price = parse_price(offer.get("price"))

    if price is None:
        prices = _extract_prices(text)

        if prices:
            price = parse_price(prices[0])

    if price is None:
        return None

    gtin = clean(
        data.get("gtin13")
        or data.get("gtin")
        or ""
    ) or None

    mpn = clean(data.get("mpn") or "") or None
    sku = clean(data.get("sku") or "") or None

    image = _image_from_product(data)

    if image:
        image = urljoin(url, image)

    availability = availability_from_sources(data, soup)
    selected_size = _selected_size(soup, data, h1_name)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": clean(brand),
            "url": url,
            "image": image,
        },
        "identity": {
            "gtin": (
                {"value": gtin, "source": "jsonld"}
                if gtin else None
            ),
            "mpn": (
                {"value": mpn, "source": "jsonld"}
                if mpn else None
            ),
            "sku": (
                {"value": sku, "source": "jsonld"}
                if sku else None
            ),
            "store_product_id": (
                {"value": sku, "source": "notino_sku"}
                if sku else None
            ),
        },
        "attributes": {
            "size_ml": (
                {
                    "value": selected_size,
                    "source": "selected_variant_or_product_name",
                }
                if selected_size is not None else None
            ),
            "concentration": (
                {
                    "value": concentration(name),
                    "source": "product_name",
                }
                if concentration(name) else None
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
            "currency": "EUR",
            "availability": availability,
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
        "available": availability == "in_stock",
    }


def _candidate_product_urls(html, query):
    """Discover generic Notino product URLs from a search/landing page.

    Discovery must not require the query text to be present in the exact
    anchor node. Notino frequently separates the product URL, product name
    and price into different DOM/JSON nodes. The real product page is the
    authoritative validation stage, just like the Deloox flow.
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    def add(raw_url, context="", force=False):
        if not raw_url:
            return

        raw_url = clean(str(raw_url)).replace("\\/", "/")

        if raw_url.startswith(("javascript:", "mailto:", "#")):
            return

        url = _normalise_url(raw_url)

        if not url or not _looks_like_product_url(url):
            return

        if url in seen:
            return

        path = urlparse(url).path.lower()
        has_product_id = bool(re.search(r"(?:^|/)p-\d+(?:/|$)", path))

        # A real Notino product URL carrying its product id is safe to
        # discover without requiring the query to appear in the same DOM
        # node. The product page will perform the final generic validation.
        if not force and not has_product_id:
            container = _candidate_container_from_context_node(context)
            container_text = clean(
                container.get_text(" ", strip=True)
                if container is not None
                else context
            )

            if not matches(
                f"{context} {url} {container_text}",
                query,
            ):
                return

            # Product cards normally expose a price or stock marker. This
            # avoids turning ordinary category/navigation links into product
            # candidates while keeping the rule completely generic.
            if not (
                _extract_prices(container_text)
                or _has_stock_marker(container_text)
            ):
                return

        seen.add(url)
        found.append(url)

    # HTML anchors. For every anchor keep the parent card available so the
    # discovery decision can use the complete product-card context.
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not href:
            continue

        context_node = _candidate_container(anchor)
        add(
            href,
            context_node,
            force=False,
        )

    # Product JSON-LD and embedded JSON can contain URLs that are not attached
    # to the visible anchor containing the product name.
    for script in soup.select('script[type="application/ld+json"]'):
        raw_json = script.string or script.get_text()
        if not raw_json:
            continue

        try:
            data = json.loads(raw_json.strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        for obj in _walk_json_ld(data):
            if not isinstance(obj, dict):
                continue

            name = clean(obj.get("name", ""))
            for key in ("url", "@id"):
                value = obj.get(key)
                if isinstance(value, str):
                    add(value, name, force=False)

            item = obj.get("item")
            if isinstance(item, dict):
                item_name = clean(item.get("name", ""))
                for key in ("url", "@id"):
                    value = item.get(key)
                    if isinstance(value, str):
                        add(value, item_name, force=False)

    # Last generic fallback: collect explicit /p-<id>/ product URLs from the
    # raw page source. These are intentionally accepted without query matching
    # because Notino can render the title and URL in separate structures.
    decoded = html.replace("\\/", "/").replace("\\u002F", "/")
    patterns = (
        r"(?:https?:)?//(?:www\\.)?notino\\.fr/[^\"'<>\\s\\\\]+?/p-\\d+/?",
        r"(?:/[^\"'<>\\s\\\\]+?/p-\\d+/?)",
    )

    for pattern in patterns:
        for raw_url in re.findall(pattern, decoded, re.I):
            add(raw_url, force=True)

    return found


def _candidate_container_from_context_node(node):
    """Return a product-card container when the caller supplied one."""
    if hasattr(node, "get_text"):
        return node
    return None

def _search_pages(query):
    return (
        SEARCH_URL.format(query=quote_plus(query)),
        BASE_URL + "/search?query=" + quote_plus(query),
        BASE_URL + "/search?q=" + quote_plus(query),
    )


def _category_pages():
    # Generic entry points only. They are not tied to any product.
    return (
        BASE_URL + "/parfums.html",
        BASE_URL + "/parfums-homme.html",
        BASE_URL + "/parfums-femme.html",
    )


def _pagination_urls(page_url, max_pages=6):
    base = page_url.split("?")[0]

    for page in range(1, max_pages + 1):
        yield f"{base}?page={page}"


def _discover_from_search_requests(session, query, max_urls=80):
    urls = []
    seen = set()

    for search_url in _search_pages(query):
        try:
            response = session.get(
                search_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if response.status_code >= 400:
            continue

        for product_url in _candidate_product_urls(
            response.text,
            query,
        ):
            if product_url in seen:
                continue

            seen.add(product_url)
            urls.append(product_url)

            if len(urls) >= max_urls:
                return urls[:max_urls]

    return urls[:max_urls]


def _discover_with_playwright(query, max_urls=80):
    if sync_playwright is None:
        return []

    urls = []
    seen = set()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )

            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="fr-FR",
                extra_http_headers={
                    "Accept-Language": HEADERS["Accept-Language"],
                },
                viewport={
                    "width": 1365,
                    "height": 900,
                },
            )

            page = context.new_page()

            for url in _search_pages(query):
                try:
                    response = page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=DEFAULT_TIMEOUT_MS,
                    )
                except Exception:
                    continue

                if (
                    response is not None
                    and response.status >= 400
                ):
                    continue

                try:
                    page.wait_for_load_state(
                        "networkidle",
                        timeout=min(
                            DEFAULT_TIMEOUT_MS,
                            15000,
                        ),
                    )
                except PlaywrightTimeoutError:
                    pass

                page.wait_for_timeout(1200)

                html = page.content()

                for product_url in _candidate_product_urls(
                    html,
                    query,
                ):
                    if product_url in seen:
                        continue

                    seen.add(product_url)
                    urls.append(product_url)

                    if len(urls) >= max_urls:
                        browser.close()
                        return urls[:max_urls]

            browser.close()

    except Exception as exc:
        LOGGER.warning(
            "Notino Playwright discovery error: %s",
            exc,
        )

    return urls[:max_urls]


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
        BASE_URL + "/robots.txt",
    )

    pending = list(sitemap_roots)
    seen_sitemaps = set()
    product_urls = []
    seen_products = set()

    def fetch_text(url):
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

        return response.text

    while (
        pending
        and len(seen_sitemaps) < max_sitemaps
        and len(product_urls) < max_urls
    ):
        sitemap_url = pending.pop(0)

        if sitemap_url in seen_sitemaps:
            continue

        seen_sitemaps.add(sitemap_url)

        body = fetch_text(sitemap_url)

        if not body:
            continue

        if sitemap_url.endswith("robots.txt"):
            for line in body.splitlines():
                if line.lower().startswith("sitemap:"):
                    value = clean(
                        line.split(":", 1)[1]
                    )
                    if value:
                        pending.append(value)
            continue

        soup = BeautifulSoup(body, "xml")

        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())

            if not value:
                continue

            low = value.lower()

            if (
                "notino.fr" in low
                and (
                    "/p/" in low
                    or "/product/" in low
                )
                and query_tokens.issubset(tokens(value))
            ):
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
    urls = []
    seen = set()

    def add_many(values, limit=80):
        for url in values:
            if url in seen:
                continue

            seen.add(url)
            urls.append(url)

            if len(urls) >= limit:
                return True

        return False

    # PRIMARY: real Notino search through the browser.
    if BROWSER_ENABLED:
        if add_many(
            _discover_with_playwright(
                query,
                max_urls=80,
            )
        ):
            return urls[:80]

    # SECONDARY: direct HTTP search when Notino allows it.
    if add_many(
        _discover_from_search_requests(
            session,
            query,
            max_urls=80,
        )
    ):
        return urls[:80]

    # TERTIARY: generic category pages and pagination.
    for root in _category_pages():
        for page_url in _pagination_urls(
            root,
            max_pages=6,
        ):
            try:
                response = session.get(
                    page_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException:
                continue

            if response.status_code >= 400:
                break

            if add_many(
                _candidate_product_urls(
                    response.text,
                    query,
                )
            ):
                return urls[:80]

    # LAST RESORT: sitemap discovery.
    if add_many(
        _sitemap_product_urls(
            session,
            query,
            max_sitemaps=12,
            max_urls=80,
        )
    ):
        return urls[:80]

    return urls[:80]


def diagnose_search(query):
    """Diagnostic-only path. Does not alter search()."""

    import time

    query = clean(query)

    report = {
        "query": query,
        "total_seconds": 0.0,
        "stages": [],
        "search_pages": [],
        "category_pages": [],
        "sitemaps": [],
        "candidates": [],
        "products": [],
    }

    started_all = time.perf_counter()
    session = requests.Session()

    def timed_request(url, timeout=TIMEOUT):
        started = time.perf_counter()

        try:
            response = session.get(
                url,
                headers=HEADERS,
                timeout=timeout,
                allow_redirects=True,
            )
            return (
                response,
                round(time.perf_counter() - started, 3),
                None,
            )
        except Exception as exc:
            return (
                None,
                round(time.perf_counter() - started, 3),
                f"{type(exc).__name__}: {exc}",
            )

    try:
        # Stage 1: search endpoints.
        started = time.perf_counter()

        for url in _search_pages(query):
            response, seconds, error = timed_request(url)

            item = {
                "url": url,
                "seconds": seconds,
                "status": (
                    None
                    if response is None
                    else response.status_code
                ),
            }

            if error:
                item["error"] = error

            elif response is not None and response.status_code < 400:
                candidates = _candidate_product_urls(
                    response.text,
                    query,
                )
                item["candidate_count"] = len(candidates)

                for candidate in candidates:
                    if candidate not in report["candidates"]:
                        report["candidates"].append(candidate)

            report["search_pages"].append(item)

        report["stages"].append({
            "name": "search_endpoints",
            "seconds": round(
                time.perf_counter() - started,
                3,
            ),
        })

        # Stage 2: generic category roots.
        started = time.perf_counter()

        for url in _category_pages():
            response, seconds, error = timed_request(url)

            item = {
                "url": url,
                "seconds": seconds,
                "status": (
                    None
                    if response is None
                    else response.status_code
                ),
            }

            if error:
                item["error"] = error

            elif response is not None and response.status_code < 400:
                candidates = _candidate_product_urls(
                    response.text,
                    query,
                )
                item["candidate_count"] = len(candidates)

                for candidate in candidates:
                    if candidate not in report["candidates"]:
                        report["candidates"].append(candidate)

            report["category_pages"].append(item)

        report["stages"].append({
            "name": "category_roots",
            "seconds": round(
                time.perf_counter() - started,
                3,
            ),
        })

        # Stage 3: sitemap roots.
        started = time.perf_counter()

        for url in (
            BASE_URL + "/sitemap.xml",
            BASE_URL + "/sitemap_index.xml",
            BASE_URL + "/sitemap-index.xml",
            BASE_URL + "/robots.txt",
        ):
            response, seconds, error = timed_request(url)

            item = {
                "url": url,
                "seconds": seconds,
                "status": (
                    None
                    if response is None
                    else response.status_code
                ),
            }

            if error:
                item["error"] = error

            elif response is not None and response.status_code < 400:
                item["bytes"] = len(response.text)

            report["sitemaps"].append(item)

        report["stages"].append({
            "name": "sitemap_roots",
            "seconds": round(
                time.perf_counter() - started,
                3,
            ),
        })

        # Stage 4: validate candidates.
        started = time.perf_counter()

        for index, url in enumerate(
            report["candidates"][:20],
            1,
        ):
            response, seconds, error = timed_request(
                url,
                timeout=TIMEOUT,
            )

            item = {
                "index": index,
                "url": url,
                "seconds": seconds,
                "status": (
                    None
                    if response is None
                    else response.status_code
                ),
            }

            if error:
                item["result"] = "request_error"
                item["error"] = error

            elif response is None or response.status_code >= 400:
                item["result"] = "http_error"

            else:
                try:
                    product = _product(
                        url,
                        response.text,
                        query,
                    )

                    if product:
                        item["result"] = "MATCH"
                        item["name"] = product.get("name")
                        item["price"] = product.get("price")
                        item["image"] = (
                            product.get("source", {})
                            .get("image")
                        )
                    else:
                        item["result"] = "PARSER_REJECTED"

                except Exception as exc:
                    item["result"] = "PARSER_ERROR"
                    item["error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )

            report["products"].append(item)

        report["stages"].append({
            "name": "product_validation",
            "seconds": round(
                time.perf_counter() - started,
                3,
            ),
            "validated": min(
                20,
                len(report["candidates"]),
            ),
        })

    finally:
        session.close()

    report["total_seconds"] = round(
        time.perf_counter() - started_all,
        3,
    )

    return report


def _fetch_product_with_playwright(url):
    if sync_playwright is None or not BROWSER_ENABLED:
        return None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )

            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="fr-FR",
                extra_http_headers={
                    "Accept-Language": HEADERS["Accept-Language"],
                },
                viewport={
                    "width": 1365,
                    "height": 900,
                },
            )

            page = context.new_page()

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )

            if (
                response is not None
                and response.status >= 400
            ):
                browser.close()
                return None

            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=min(
                        DEFAULT_TIMEOUT_MS,
                        15000,
                    ),
                )
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(1200)

            html = page.content()
            browser.close()

            return html

    except Exception as exc:
        LOGGER.warning(
            "Notino Playwright product error: %s",
            exc,
        )
        return None


def search(query):
    query = clean(query)

    if not query:
        return []

    session = requests.Session()
    results = []
    seen = set()

    try:
        for url in _discover(session, query):
            html = None

            # Primary product-page retrieval: normal HTTP.
            try:
                response = session.get(
                    url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )

                if response.status_code < 400:
                    html = response.text

            except requests.RequestException:
                html = None

            # Notino can protect direct datacenter requests.
            # If that happens, use the same browser path used for discovery.
            if not html and BROWSER_ENABLED:
                html = _fetch_product_with_playwright(url)

            if not html:
                continue

            item = _product(
                url,
                html,
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

        return results

    finally:
        session.close()


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument(
        "--diagnostic",
        action="store_true",
    )
    args = parser.parse_args()

    if args.diagnostic:
        output = diagnose_search(args.query)
    else:
        output = search(args.query)

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )
