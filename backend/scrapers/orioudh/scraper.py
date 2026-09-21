"""ScentHunter - Orioudh scraper.

Generic Shopify/Orioudh store adapter.

The scraper is responsible only for:
- discovering real Shopify product URLs;
- fetching real product/variant data;
- normalizing retailer offer fields;
- propagating technical failures.

It contains no perfume-specific URL, SKU, price, family or variant map.
Canonical identity remains the responsibility of ProductMatcher.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Orioudh"
BASE_URL = "https://orioudh.com"

CONNECT_TIMEOUT = 3.5
READ_TIMEOUT = 8.0
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

MAX_CANDIDATES = 80
MAX_RESULTS = 80
PRODUCT_WORKERS = 6
MAX_SITEMAPS = 8
MAX_PRODUCTS_PER_PAGE = 250
MAX_CATALOG_PAGES = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/json;q=0.9,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}

SIZE_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
    re.I,
)


class StoreRequestError(RuntimeError):
    def __init__(
        self,
        status,
        message,
        url=None,
        http_status=None,
    ):
        super().__init__(message)
        self.status = status
        self.url = url
        self.http_status = http_status


def clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def norm(value):
    return re.sub(
        r"\s+",
        " ",
        re.sub(
            r"[^a-z0-9]+",
            " ",
            clean(value).lower(),
        ),
    ).strip()


def query_tokens(query):
    stopwords = {
        "eau",
        "de",
        "parfum",
        "perfume",
        "edp",
        "edt",
        "extrait",
        "spray",
        "for",
        "by",
        "pour",
        "ml",
        "cl",
        "men",
        "man",
        "women",
        "woman",
        "male",
        "female",
        "homme",
        "femme",
        "herren",
        "damen",
    }

    return [
        token
        for token in norm(query).split()
        if token not in stopwords
        and not re.fullmatch(
            r"\d+(?:[.,]\d+)?",
            token,
        )
    ]


def query_matches(text, query):
    wanted = query_tokens(query)
    if not wanted:
        return False

    hay = set(norm(text).split())
    return all(token in hay for token in wanted)


def size_ml(*values):
    match = SIZE_RE.search(
        " ".join(
            clean(value)
            for value in values
            if value
        )
    )

    if not match:
        return None

    number = float(
        match.group(1).replace(",", ".")
    )

    if match.group(2).lower() == "cl":
        number *= 10

    return (
        int(number)
        if number.is_integer()
        else number
    )


def concentration(*values):
    text = norm(
        " ".join(
            clean(value)
            for value in values
            if value
        )
    )

    if re.search(
        r"\beau de toilette\b|\bedt\b",
        text,
    ):
        return "Eau de Toilette"

    if re.search(
        r"\bextrait(?: de parfum)?\b",
        text,
    ):
        return "Extrait de Parfum"

    if re.search(
        r"\beau de parfum\b|\bedp\b",
        text,
    ):
        return "Eau de Parfum"

    return None


def price_num(value):
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)) and not isinstance(
        value,
        bool,
    ):
        number = float(value)
        if number.is_integer() and abs(number) >= 100:
            number /= 100
        return round(number, 2)

    text = clean(value).replace("€", "")
    match = re.search(
        r"\d+(?:[.,]\d{1,2})?",
        text,
    )

    if not match:
        return None

    raw = match.group(0)

    try:
        number = float(
            raw.replace(",", ".")
        )
    except ValueError:
        return None

    if (
        re.fullmatch(r"\d+", raw)
        and number >= 100
    ):
        number /= 100

    return round(number, 2)


def price_text(value):
    number = price_num(value)
    if number is None:
        return None

    return f"{number:.2f}".replace(
        ".",
        ",",
    ) + " €"


def availability(value):
    text = norm(value)

    if any(
        marker in text
        for marker in (
            "out of stock",
            "outofstock",
            "sold out",
            "soldout",
            "unavailable",
            "not available",
        )
    ):
        return "out_of_stock"

    if any(
        marker in text
        for marker in (
            "in stock",
            "instock",
            "available",
            "add to cart",
            "in winkelwagen",
        )
    ):
        return "in_stock"

    return "unknown"


def _request(
    session,
    url,
    params=None,
):
    for attempt in range(2):
        try:
            response = session.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.Timeout as exc:
            if attempt == 0:
                time.sleep(0.25)
                continue

            raise StoreRequestError(
                "timeout",
                "Orioudh request timed out",
                url=url,
            ) from exc
        except requests.ConnectionError as exc:
            if attempt == 0:
                time.sleep(0.25)
                continue

            raise StoreRequestError(
                "unavailable",
                "Orioudh connection failed",
                url=url,
            ) from exc
        except requests.RequestException as exc:
            if attempt == 0:
                time.sleep(0.25)
                continue

            raise StoreRequestError(
                "error",
                f"Orioudh request failed: {type(exc).__name__}",
                url=url,
            ) from exc

        status = response.status_code

        if 200 <= status < 300:
            return response

        if status in (401, 403):
            raise StoreRequestError(
                "blocked",
                f"Orioudh returned HTTP {status}",
                url=url,
                http_status=status,
            )

        if status == 429:
            if attempt == 0:
                time.sleep(0.6)
                continue

            raise StoreRequestError(
                "blocked",
                "Orioudh rate-limited the request",
                url=url,
                http_status=status,
            )

        if status >= 500:
            if attempt == 0:
                time.sleep(0.35)
                continue

            raise StoreRequestError(
                "unavailable",
                f"Orioudh returned HTTP {status}",
                url=url,
                http_status=status,
            )

        if 400 <= status < 500:
            raise StoreRequestError(
                "error",
                f"Orioudh returned HTTP {status}",
                url=url,
                http_status=status,
            )

        raise StoreRequestError(
            "error",
            f"Unexpected Orioudh HTTP status {status}",
            url=url,
            http_status=status,
        )

    raise StoreRequestError(
        "error",
        "Orioudh request exhausted retries",
        url=url,
    )


def _canonical_url(raw_url):
    if not raw_url:
        return ""

    url = urljoin(
        BASE_URL + "/",
        clean(raw_url),
    )

    parsed = urlparse(url)

    host = parsed.netloc.lower().split(
        ":",
        1,
    )[0]

    if host in {
        "www.orioudh.com",
        "orioudh.com",
    }:
        url = (
            "https://orioudh.com"
            + parsed.path
        )

    return url.split("?", 1)[0].split(
        "#",
        1,
    )[0].rstrip("/")


def _is_product_url(url):
    parsed = urlparse(url)

    host = parsed.netloc.lower().split(
        ":",
        1,
    )[0]

    return (
        host in {
            "orioudh.com",
            "www.orioudh.com",
        }
        and "/products/" in parsed.path
    )


def _add_product_url(
    urls,
    seen,
    raw_url,
    query,
    context="",
):
    url = _canonical_url(raw_url)

    if not url or not _is_product_url(url):
        return False

    if url in seen:
        return False

    if not query_matches(
        f"{context} {url}",
        query,
    ):
        return False

    seen.add(url)
    urls.append(url)
    return True


def _discover_search_suggest(
    session,
    query,
):
    urls = []
    seen = set()

    response = _request(
        session,
        BASE_URL + "/search/suggest.json",
        params={
            "q": query,
            "resources[type]": "product",
            "resources[limit]": 20,
            "resources[options][unavailable_products]": "show",
        },
    )

    try:
        data = response.json()
    except (ValueError, TypeError) as exc:
        raise StoreRequestError(
            "error",
            "Orioudh returned invalid search JSON",
            url=response.url,
        ) from exc

    products = (
        (data.get("resources") or {})
        .get("results", {})
        .get("products", [])
    )

    if not isinstance(products, list):
        return urls

    for product in products:
        if not isinstance(product, dict):
            continue

        raw_url = (
            product.get("url")
            or product.get("product_url")
        )

        context = " ".join(
            [
                clean(product.get("title")),
                clean(product.get("vendor")),
                clean(raw_url),
            ]
        )

        _add_product_url(
            urls,
            seen,
            raw_url,
            query,
            context,
        )

        if len(urls) >= MAX_CANDIDATES:
            break

    return urls


def _discover_search_html(
    session,
    query,
):
    urls = []
    seen = set()

    response = _request(
        session,
        BASE_URL + "/search",
        params={
            "q": query,
            "type": "product",
        },
    )

    soup = BeautifulSoup(
        response.text or "",
        "html.parser",
    )

    for anchor in soup.select(
        'a[href*="/products/"]'
    ):
        raw_url = anchor.get("href")
        context = " ".join(
            [
                clean(anchor.get("title")),
                anchor.get_text(
                    " ",
                    strip=True,
                ),
                clean(raw_url),
            ]
        )

        _add_product_url(
            urls,
            seen,
            raw_url,
            query,
            context,
        )

        if len(urls) >= MAX_CANDIDATES:
            break

    return urls


def _discover_catalog_json(
    session,
    query,
):
    """
    Shopify catalog discovery.

    Uses the store's actual catalog API rather than a perfume-specific map.
    """

    urls = []
    seen = set()

    endpoint = (
        BASE_URL
        + "/products.json"
    )

    for page in range(
        1,
        MAX_CATALOG_PAGES + 1,
    ):
        response = _request(
            session,
            endpoint,
            params={
                "limit": MAX_PRODUCTS_PER_PAGE,
                "page": page,
            },
        )

        try:
            data = response.json()
        except (ValueError, TypeError) as exc:
            raise StoreRequestError(
                "error",
                "Orioudh catalog returned invalid JSON",
                url=response.url,
            ) from exc

        products = (
            data.get("products")
            if isinstance(data, dict)
            else None
        )

        if not isinstance(
            products,
            list,
        ):
            break

        if not products:
            break

        for product in products:
            if not isinstance(product, dict):
                continue

            title = clean(
                product.get("title")
            )
            vendor = clean(
                product.get("vendor")
            )
            handle = clean(
                product.get("handle")
            )

            context = " ".join(
                [
                    title,
                    vendor,
                    handle,
                ]
            )

            if not query_matches(
                context,
                query,
            ):
                continue

            if not handle:
                continue

            url = (
                BASE_URL
                + "/products/"
                + handle
            )

            _add_product_url(
                urls,
                seen,
                url,
                query,
                context,
            )

            if len(urls) >= MAX_CANDIDATES:
                return urls

        if len(products) < MAX_PRODUCTS_PER_PAGE:
            break

    return urls


def _discover_sitemap(
    session,
    query,
):
    """
    Generic sitemap discovery.

    Follows sitemap indexes exposed by robots.txt.
    """

    urls = []
    seen = set()
    sitemap_seen = set()
    queue = []

    robots = _request(
        session,
        BASE_URL + "/robots.txt",
    )

    for sitemap in re.findall(
        r"(?im)^\s*sitemap:\s*(\S+)",
        robots.text or "",
    ):
        sitemap = clean(sitemap)
        if sitemap and sitemap not in sitemap_seen:
            sitemap_seen.add(sitemap)
            queue.append(sitemap)

    processed = 0

    while (
        queue
        and processed < MAX_SITEMAPS
        and len(urls) < MAX_CANDIDATES
    ):
        sitemap_url = queue.pop(0)
        processed += 1

        try:
            response = _request(
                session,
                sitemap_url,
            )
        except StoreRequestError:
            continue

        soup = BeautifulSoup(
            response.text or "",
            "xml",
        )

        locations = [
            clean(node.get_text(" ", strip=True))
            for node in soup.find_all("loc")
        ]

        if not locations:
            locations = re.findall(
                r"<loc>\s*([^<]+)\s*</loc>",
                response.text or "",
                re.I,
            )

        for location in locations:
            if not location:
                continue

            if (
                location.endswith(".xml")
                or "sitemap" in location.lower()
            ):
                if (
                    location not in sitemap_seen
                    and len(sitemap_seen) < MAX_SITEMAPS
                ):
                    sitemap_seen.add(location)
                    queue.append(location)
                continue

            if "/products/" not in location:
                continue

            _add_product_url(
                urls,
                seen,
                location,
                query,
                location,
            )

            if len(urls) >= MAX_CANDIDATES:
                break

    return urls


def discover(
    session,
    query,
):
    """
    Discover product URLs.

    All mechanisms are generic store mechanisms:
    search suggestion -> search HTML -> catalog -> sitemap.

    No product-specific branch exists here.
    """

    query = clean(query)

    if not query:
        return [], {
            "status": "success",
            "verified": True,
            "discovery": "empty_query",
        }

    candidates = []
    seen = set()
    failures = []

    # Search suggestion is the fastest current Shopify discovery path.
    try:
        for url in _discover_search_suggest(
            session,
            query,
        ):
            if url not in seen:
                seen.add(url)
                candidates.append(url)
    except StoreRequestError as exc:
        failures.append(
            {
                "status": exc.status,
                "url": exc.url,
                "http_status": exc.http_status,
                "message": str(exc),
            }
        )

    # Search HTML is a generic fallback.
    if len(candidates) < MAX_CANDIDATES:
        try:
            for url in _discover_search_html(
                session,
                query,
            ):
                if url not in seen:
                    seen.add(url)
                    candidates.append(url)
        except StoreRequestError as exc:
            failures.append(
                {
                    "status": exc.status,
                    "url": exc.url,
                    "http_status": exc.http_status,
                    "message": str(exc),
                }
            )

    # Full Shopify catalog is the authoritative broad discovery fallback.
    if len(candidates) < MAX_CANDIDATES:
        try:
            for url in _discover_catalog_json(
                session,
                query,
            ):
                if url not in seen:
                    seen.add(url)
                    candidates.append(url)
        except StoreRequestError as exc:
            failures.append(
                {
                    "status": exc.status,
                    "url": exc.url,
                    "http_status": exc.http_status,
                    "message": str(exc),
                }
            )

    # Sitemap is a second broad catalog fallback.
    if len(candidates) < MAX_CANDIDATES:
        try:
            for url in _discover_sitemap(
                session,
                query,
            ):
                if url not in seen:
                    seen.add(url)
                    candidates.append(url)
        except StoreRequestError as exc:
            failures.append(
                {
                    "status": exc.status,
                    "url": exc.url,
                    "http_status": exc.http_status,
                    "message": str(exc),
                }
            )

    candidates = candidates[:MAX_CANDIDATES]

    if candidates:
        return candidates, {
            "status": (
                "success"
                if not failures
                else "partial"
            ),
            "verified": True,
            "discovery": "catalog_candidates",
            "candidate_count": len(candidates),
            "failures": failures,
        }

    if failures:
        return [], {
            "status": failures[0]["status"],
            "verified": False,
            "discovery": "no_verified_catalog",
            "candidate_count": 0,
            "failures": failures,
        }

    return [], {
        "status": "success",
        "verified": True,
        "discovery": "verified_empty",
        "candidate_count": 0,
        "failures": [],
    }


def _product_json(
    session,
    url,
):
    response = _request(
        session,
        url.rstrip("/") + ".js",
    )

    try:
        data = response.json()
    except (ValueError, TypeError) as exc:
        raise StoreRequestError(
            "error",
            "Orioudh product endpoint returned invalid JSON",
            url=response.url,
        ) from exc

    if not isinstance(data, dict):
        raise StoreRequestError(
            "error",
            "Orioudh product endpoint returned unexpected JSON",
            url=response.url,
        )

    return data


def _product_image(product):
    image = product.get(
        "featured_image"
    )

    if isinstance(image, dict):
        image = (
            image.get("src")
            or image.get("url")
        )

    if not image:
        images = (
            product.get("images")
            or []
        )

        if images:
            image = images[0]

    return (
        urljoin(
            BASE_URL,
            str(image),
        )
        if image
        else None
    )


def _variant_identity(
    product,
    variant,
):
    sku = clean(
        variant.get("sku")
    )

    product_id = product.get("id")
    variant_id = variant.get("id")

    return {
        "gtin": None,
        "mpn": None,
        "sku": (
            {
                "value": sku,
                "source": "shopify_variant",
            }
            if sku
            else None
        ),
        "store_product_id": (
            {
                "value": product_id,
                "source": "shopify_product",
            }
            if product_id is not None
            else None
        ),
        "store_variant_id": (
            {
                "value": variant_id,
                "source": "shopify_variant",
            }
            if variant_id is not None
            else None
        ),
    }


def _variant_row(
    product,
    variant,
    url,
    query,
):
    title = clean(
        product.get("title")
    )
    variant_title = clean(
        variant.get("title")
    )

    product_type = clean(
        product.get("product_type")
    )

    context = " ".join(
        [
            title,
            variant_title,
            product_type,
            clean(product.get("vendor")),
        ]
    )

    if not query_matches(
        context,
        query,
    ):
        return None

    haystack = norm(
        f"{title} "
        f"{variant_title} "
        f"{product_type}"
    )

    # Generic non-product packaging exclusion.
    if re.search(
        r"\bmystery box\b|\bgift set\b|\bcoffret\b|\bset cadeau\b",
        haystack,
    ):
        return None

    number = price_num(
        variant.get("price")
    )

    if number is None:
        return None

    variant_size = size_ml(
        variant_title,
        title,
    )

    state = (
        "in_stock"
        if variant.get("available") is True
        else (
            "out_of_stock"
            if variant.get("available") is False
            else "unknown"
        )
    )

    image = _product_image(product)

    source_name = title
    if (
        variant_title
        and variant_title.lower()
        != "default title"
    ):
        source_name = (
            f"{title} {variant_title}"
        )

    # Keep retailer wording intact. Do not manufacture a canonical
    # perfume identity here.
    identity_name = title

    return {
        "store": STORE,
        "source": {
            "source_name": source_name,
            "source_brand": (
                clean(product.get("vendor"))
                or None
            ),
            "url": url,
            "image": image,
        },
        "image": image,
        "identity": _variant_identity(
            product,
            variant,
        ),
        "attributes": {
            "size_ml": (
                {
                    "value": variant_size,
                    "source": "product_variant",
                }
                if variant_size is not None
                else None
            ),
            "concentration": (
                {
                    "value": concentration(
                        variant_title,
                        title,
                    ),
                    "source": "product_title",
                }
                if concentration(
                    variant_title,
                    title,
                )
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
            "price": number,
            "currency": "EUR",
            "availability": state,
        },
        "provenance": {
            "source_page": url,
            "product_source": "shopify_product_json",
            "variant_source": "shopify_product_json",
        },
        "raw_data": {
            "product": product,
            "variant": variant,
        },
        "name": identity_name,
        "price": price_text(number),
        "url": url,
        "available": (
            True
            if state == "in_stock"
            else (
                False
                if state == "out_of_stock"
                else None
            )
        ),
    }


def _fetch_product(
    url,
    query,
):
    session = requests.Session()

    try:
        product = _product_json(
            session,
            url,
        )

        variants = (
            product.get("variants")
            or []
        )

        if not isinstance(
            variants,
            list,
        ):
            return [], {
                "status": "partial",
                "url": url,
                "reason": "invalid_variants",
            }

        rows = []

        for variant in variants:
            if not isinstance(
                variant,
                dict,
            ):
                continue

            row = _variant_row(
                product,
                variant,
                url,
                query,
            )

            if row:
                rows.append(row)

        if rows:
            return rows, {
                "status": "success",
                "url": url,
            }

        return [], {
            "status": "partial",
            "url": url,
            "reason": "product_did_not_match_query",
        }

    except StoreRequestError as exc:
        return [], {
            "status": exc.status,
            "url": exc.url,
            "http_status": exc.http_status,
            "error": str(exc),
        }
    except Exception as exc:
        return [], {
            "status": "error",
            "url": url,
            "error": (
                f"{type(exc).__name__}: {exc}"
            ),
        }
    finally:
        session.close()


def parse_product(
    url,
    query,
):
    rows, _meta = _fetch_product(
        _canonical_url(url),
        clean(query),
    )
    return rows


def search_stream(query):
    """
    Standard ScentHunter scraper contract.

    An empty result is NOT reported as NOT_FOUND unless discovery was
    actually verified. Technical failure remains visible to the caller.
    """

    query = clean(query)

    if not query:
        yield {
            "status": "success",
            "verified": True,
            "results": [],
            "error": None,
            "details": {
                "reason": "empty_query",
            },
        }
        return

    started = time.perf_counter()
    session = requests.Session()

    try:
        try:
            urls, discovery_meta = discover(
                session,
                query,
            )
        except StoreRequestError as exc:
            yield {
                "status": exc.status,
                "verified": False,
                "results": [],
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "url": exc.url,
                    "http_status": exc.http_status,
                },
                "details": {
                    "stage": "discovery",
                    "elapsed": round(
                        time.perf_counter()
                        - started,
                        3,
                    ),
                },
            }
            return
    finally:
        session.close()

    if not urls:
        verified = bool(
            discovery_meta.get(
                "verified"
            )
        )

        yield {
            "status": discovery_meta.get(
                "status",
                "success",
            ),
            "verified": verified,
            "results": [],
            "error": (
                None
                if verified
                else discovery_meta.get(
                    "failures"
                )
            ),
            "details": {
                "stage": "discovery",
                "candidate_count": 0,
                "discovery": discovery_meta.get(
                    "discovery"
                ),
                "elapsed": round(
                    time.perf_counter()
                    - started,
                    3,
                ),
            },
        }
        return

    results = []
    errors = []

    with ThreadPoolExecutor(
        max_workers=min(
            PRODUCT_WORKERS,
            len(urls),
        )
    ) as pool:
        futures = {
            pool.submit(
                _fetch_product,
                url,
                query,
            ): url
            for url in urls
        }

        for future in as_completed(
            futures
        ):
            url = futures[future]

            try:
                rows, meta = future.result()
            except Exception as exc:
                rows = []
                meta = {
                    "status": "error",
                    "url": url,
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }

            results.extend(rows)

            if meta.get("status") not in {
                "success",
                "partial",
            }:
                errors.append(meta)

    seen = set()
    deduped = []

    for row in results:
        identity = row.get(
            "identity"
        ) or {}

        variant_id = (
            identity.get(
                "store_variant_id"
            )
            or {}
        ).get("value")

        key = (
            row.get("url"),
            variant_id,
            row.get("size_ml"),
            row.get("price_num"),
            row.get("offer", {}).get(
                "availability"
            ),
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(row)

    deduped.sort(
        key=lambda item: (
            2
            if item.get("offer", {}).get(
                "availability"
            ) == "out_of_stock"
            else 0,
            (
                item.get("price_num")
                if item.get("price_num")
                is not None
                else 999999
            ),
            (
                item.get("attributes", {})
                .get("size_ml", {})
                .get("value")
                if isinstance(
                    item.get("attributes", {})
                    .get("size_ml"),
                    dict,
                )
                else 999999
            ),
        )
    )

    deduped = deduped[:MAX_RESULTS]

    if deduped and errors:
        status = "partial"
        verified = True
    elif deduped:
        status = "success"
        verified = True
    elif errors:
        status = "partial"
        verified = False
    else:
        status = "success"
        verified = True

    yield {
        "status": status,
        "verified": verified,
        "results": deduped,
        "error": errors or None,
        "details": {
            "stage": "product_fetch",
            "candidate_count": len(urls),
            "result_count": len(deduped),
            "error_count": len(errors),
            "elapsed": round(
                time.perf_counter()
                - started,
                3,
            ),
            "discovery": discovery_meta,
        },
    }


def search(query):
    """Compatibility API returning only result rows."""

    report = next(
        search_stream(query)
    )
    return report.get(
        "results",
        [],
    )


def scrape(query):
    return search(query)


def diagnose(query):
    query = clean(query)
    session = requests.Session()

    try:
        urls, meta = discover(
            session,
            query,
        )
        return {
            "diagnostic": True,
            "query": query,
            "status": meta.get(
                "status"
            ),
            "verified": meta.get(
                "verified"
            ),
            "candidate_count": len(urls),
            "candidates": urls[:50],
            "details": meta,
        }
    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument(
        "--diagnose",
        action="store_true",
    )

    args = parser.parse_args()

    report = (
        diagnose(args.query)
        if args.diagnose
        else next(
            search_stream(args.query)
        )
    )

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )
