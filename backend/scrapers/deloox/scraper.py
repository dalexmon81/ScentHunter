"""ScentHunter - Deloox scraper.

Generic Deloox store adapter.

Responsibilities:
- Discover real Deloox product candidates without product-specific rules.
- Fetch and parse real product pages.
- Return normalized retailer offer data.
- Preserve technical failures instead of converting them to an empty result.
- Keep canonical product identity outside this scraper.

This file intentionally contains no perfume-specific URL, SKU, price,
variant, family or product-name map.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE = "https://www.deloox.be"

CONNECT_TIMEOUT = 3.5
READ_TIMEOUT = 8.0
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

MAX_DISCOVERY_PAGES = 8
MAX_CANDIDATES = 80
MAX_RESULTS = 80
PRODUCT_WORKERS = 6

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/json;q=0.9,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

SIZE_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
    re.I,
)

PRICE_RE = re.compile(
    r"(?:€\s*)?(\d{1,4}\s*[.,]\s*\d{2})(?:\s*€)?"
)

PRODUCT_PATH_RE = re.compile(
    r"/(?:product|produit|producto|prodotto)(?:/|\-)",
    re.I,
)


class StoreRequestError(RuntimeError):
    """Structured store-side request failure."""

    def __init__(self, status, message, url=None, http_status=None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.http_status = http_status


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", clean(value).lower()),
    ).strip()


def tokens(value):
    return {item for item in norm(value).split() if len(item) > 1}


def query_matches(text, query):
    wanted = tokens(query)
    if not wanted:
        return False
    hay = tokens(text)
    return wanted.issubset(hay)


def size_ml(*values):
    match = SIZE_RE.search(
        " ".join(clean(value) for value in values if value)
    )
    if not match:
        return None

    number = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        number *= 10

    return int(number) if number.is_integer() else number


def price_num(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 2)

    text = clean(value).replace("\xa0", " ")
    for raw in PRICE_RE.findall(text):
        try:
            number = float(
                raw.replace(" ", "").replace(",", ".")
            )
        except ValueError:
            continue

        if 0 < number < 10000:
            return round(number, 2)

    return None


def price_text(value):
    number = price_num(value)
    if number is None:
        return None
    return f"{number:.2f}".replace(".", ",") + " €"


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


def _image_url(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            result = _image_url(item)
            if result:
                return result
        return ""

    if isinstance(value, dict):
        for key in ("url", "src", "contentUrl", "image"):
            result = _image_url(value.get(key))
            if result:
                return result
        return ""

    value = clean(value)
    if not value or value.startswith("data:"):
        return ""

    if value.startswith("//"):
        return "https:" + value

    return urljoin(BASE, value)


def _image_from_node(node):
    if not node:
        return ""

    for candidate in node.find_all(["img", "source"]):
        for attr in (
            "src",
            "data-src",
            "data-lazy-src",
            "data-original",
            "data-image",
            "content",
        ):
            image = _image_url(candidate.get(attr))
            if image:
                return image

        for attr in ("srcset", "data-srcset"):
            raw = candidate.get(attr)
            if not raw:
                continue

            first = (
                str(raw)
                .split(",", 1)[0]
                .strip()
                .split(" ", 1)[0]
            )
            image = _image_url(first)
            if image:
                return image

    return ""


def _request(session, url, method="GET", allow_statuses=None):
    """Request a Deloox URL and preserve technical failures."""

    allow_statuses = set(allow_statuses or {200})

    for attempt in range(2):
        try:
            response = session.request(
                method,
                url,
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
                "Deloox request timed out",
                url=url,
            ) from exc
        except requests.ConnectionError as exc:
            if attempt == 0:
                time.sleep(0.25)
                continue
            raise StoreRequestError(
                "unavailable",
                "Deloox connection failed",
                url=url,
            ) from exc
        except requests.RequestException as exc:
            if attempt == 0:
                time.sleep(0.25)
                continue
            raise StoreRequestError(
                "error",
                f"Deloox request failed: {type(exc).__name__}",
                url=url,
            ) from exc

        status = response.status_code

        if status in allow_statuses:
            return response

        if status in (401, 403):
            raise StoreRequestError(
                "blocked",
                f"Deloox returned HTTP {status}",
                url=url,
                http_status=status,
            )

        if status == 429:
            if attempt == 0:
                time.sleep(0.6)
                continue
            raise StoreRequestError(
                "blocked",
                "Deloox rate-limited the request",
                url=url,
                http_status=status,
            )

        if status >= 500:
            if attempt == 0:
                time.sleep(0.35)
                continue
            raise StoreRequestError(
                "unavailable",
                f"Deloox returned HTTP {status}",
                url=url,
                http_status=status,
            )

        if 400 <= status < 500:
            raise StoreRequestError(
                "error",
                f"Deloox returned HTTP {status}",
                url=url,
                http_status=status,
            )

        raise StoreRequestError(
            "error",
            f"Unexpected Deloox HTTP status {status}",
            url=url,
            http_status=status,
        )

    raise StoreRequestError(
        "error",
        "Deloox request exhausted retries",
        url=url,
    )


def is_product_url(raw_url):
    try:
        parsed = urlparse(raw_url)
    except Exception:
        return False

    host = parsed.netloc.lower().split(":", 1)[0]
    if host not in {"deloox.be", "www.deloox.be"}:
        return False

    return bool(PRODUCT_PATH_RE.search(parsed.path))


def product_url(raw_url):
    if not raw_url:
        return ""

    url = urljoin(BASE + "/", clean(raw_url))
    url = url.split("#", 1)[0].split("?", 1)[0]

    return url if is_product_url(url) else ""


def _candidate_product_urls(html, query=None, discovery_query=None):
    """Extract product URLs from normal links and serialized page data."""

    soup = BeautifulSoup(html or "", "html.parser")
    found = []
    seen = set()

    def add(raw_url, context=""):
        url = product_url(raw_url)
        if not url or url in seen:
            return

        # Discovery is intentionally broader than final matching. Search
        # pages can omit part of a product title from the anchor text or
        # render it only in serialized data. Require at least one meaningful
        # discovery token here; _parse_product_page() remains authoritative
        # and validates the complete original query against the real product
        # name.
        discovery = clean(discovery_query or query)
        if discovery:
            wanted = tokens(discovery)
            hay = tokens(f"{context} {url}")
            if wanted and not (wanted & hay):
                return

        seen.add(url)
        found.append(url)

    for anchor in soup.find_all("a", href=True):
        add(
            anchor.get("href"),
            anchor.get_text(" ", strip=True),
        )

    raw = (html or "").replace("\\/", "/")

    patterns = (
        r'https?://(?:www\.)?deloox\.be/[^"\'<>\s]+/'
        r'(?:product|produit|producto|prodotto)(?:/|-)[^"\'<>\s?#]+',
        r'["\']((?:/)?(?:en/|nl/|fr/|it/)?'
        r'(?:product|produit|producto|prodotto)(?:/|-)'
        r'[^"\']+)["\']',
    )

    for pattern in patterns:
        for match in re.findall(pattern, raw, re.I):
            if isinstance(match, tuple):
                match = "".join(match)
            add(match)

    return found


def _category_links(html, query):
    """Find category URLs whose visible/slug text matches the query."""

    soup = BeautifulSoup(html or "", "html.parser")
    found = []
    seen = set()
    wanted = tokens(query)

    def add(raw_url, label=""):
        if not raw_url:
            return

        url = urljoin(BASE + "/", clean(raw_url))
        url = url.split("#", 1)[0]

        try:
            parsed = urlparse(url)
        except Exception:
            return

        host = parsed.netloc.lower().split(":", 1)[0]
        if host not in {"deloox.be", "www.deloox.be"}:
            return

        path = parsed.path.lower()
        if "/category/" not in path and "/categorie/" not in path:
            return

        slug = parsed.path.rsplit("/", 1)[-1]
        slug = re.sub(r"\.html$", "", slug, flags=re.I)

        haystack = tokens(f"{slug} {label}")
        if not wanted or not wanted.issubset(haystack):
            return

        if url in seen:
            return

        seen.add(url)
        found.append(url)

    for anchor in soup.find_all("a", href=True):
        add(
            anchor.get("href"),
            anchor.get_text(" ", strip=True),
        )

    raw = (html or "").replace("\\/", "/")
    for match in re.findall(
        r'["\']((?:https?:)?//(?:www\.)?deloox\.be)?'
        r'(/(?:en/|nl/|fr/|it/)?'
        r'(?:category|categorie)/[^"\']+\.html)["\']',
        raw,
        re.I,
    ):
        if isinstance(match, tuple):
            add("".join(match))
        else:
            add(match)

    return found


def _category_roots():
    """Generic Deloox fragrance entry points."""

    return (
        BASE + "/category/1000054/mens-fragrances.html",
        BASE + "/category/1075639/womens-fragrances.html",
        BASE + "/category/1075660/womens-perfume.html",
        BASE + "/category/1075750/mens-perfume.html",
        BASE + "/category/1025540/trending.html",
    )


def _pagination_urls(url):
    base = url.split("?", 1)[0]
    for page in range(1, MAX_DISCOVERY_PAGES + 1):
        yield f"{base}?page={page}"


def _discover_from_page(
    session,
    url,
    query,
    candidates,
    visited,
):
    if url in visited:
        return None

    visited.add(url)

    response = _request(session, url)
    product_urls = _candidate_product_urls(
        response.text,
        query,
    )

    for product in product_urls:
        candidates.setdefault(product, url)

    if len(candidates) >= MAX_CANDIDATES:
        return None

    for category in _category_links(response.text, query):
        if category in visited:
            continue
        for page_url in _pagination_urls(category):
            if page_url in visited:
                continue
            try:
                page_response = _request(session, page_url)
            except StoreRequestError:
                continue

            visited.add(page_url)

            for product in _candidate_product_urls(
                page_response.text,
                query,
            ):
                candidates.setdefault(product, page_url)

            if len(candidates) >= MAX_CANDIDATES:
                return None

    return response


def _search_endpoints(query):
    encoded = quote_plus(query)

    return (
        BASE + f"/chercher.html?q={encoded}",
        BASE + f"/en/search?query={encoded}",
        BASE + f"/en/search?q={encoded}",
        BASE + f"/nl/zoeken?query={encoded}",
        BASE + f"/nl/zoeken?q={encoded}",
        BASE + f"/fr/recherche?query={encoded}",
        BASE + f"/fr/recherche?q={encoded}",
    )


def _candidate_queries(query):
    q = clean(query)
    if not q:
        return []
    variants = [q]
    parts = q.split()
    removable = {
        "parfum", "perfume", "eau", "de", "toilette", "edt", "edp",
        "extrait", "extract", "for", "the", "and", "by",
    }
    broad = " ".join(p for p in parts if p.lower() not in removable).strip()
    if broad and norm(broad) != norm(q):
        variants.append(broad)
    for token in sorted(tokens(q), key=lambda x: (-len(x), x)):
        if token not in variants:
            variants.append(token)
    out=[]; seen=set()
    for item in variants:
        key=norm(item)
        if key and key not in seen:
            seen.add(key); out.append(item)
    return out


def _discover_from_search(session, query, candidates):
    """Use current Deloox search endpoints with generic discovery broadening."""
    for discovery_query in _candidate_queries(query):
        encoded = quote_plus(discovery_query)
        endpoints = (
            BASE + f"/chercher.html?q={encoded}",
            BASE + f"/en/search?query={encoded}",
            BASE + f"/en/search?q={encoded}",
            BASE + f"/nl/zoeken?query={encoded}",
            BASE + f"/nl/zoeken?q={encoded}",
            BASE + f"/fr/recherche?query={encoded}",
            BASE + f"/fr/recherche?q={encoded}",
        )

        for endpoint in endpoints:
            if len(candidates) >= MAX_CANDIDATES:
                return candidates
            try:
                response = _request(session, endpoint)
            except StoreRequestError:
                continue

            for product in _candidate_product_urls(
                response.text, query, discovery_query=discovery_query
            ):
                candidates.setdefault(product, endpoint)

            for page_url in _pagination_urls(endpoint):
                if len(candidates) >= MAX_CANDIDATES:
                    break
                if page_url == endpoint:
                    continue
                try:
                    page_response = _request(session, page_url)
                except StoreRequestError:
                    continue
                for product in _candidate_product_urls(
                    page_response.text, query, discovery_query=discovery_query
                ):
                    candidates.setdefault(product, page_url)

    return candidates


def _sitemap_urls(session):
    """Return product sitemap URLs discovered from sitemap indexes."""

    roots = (
        BASE + "/sitemap.xml",
        BASE + "/sitemap_index.xml",
    )

    sitemap_urls = []
    seen = set()

    for root in roots:
        try:
            response = _request(session, root)
        except StoreRequestError:
            continue

        soup = BeautifulSoup(
            response.text or "",
            "xml",
        )

        locs = [
            clean(node.get_text(" ", strip=True))
            for node in soup.find_all("loc")
        ]

        if not locs:
            locs = re.findall(
                r"<loc>\s*([^<]+)\s*</loc>",
                response.text or "",
                re.I,
            )

        for location in locs:
            location = clean(location)
            if not location:
                continue

            if location in seen:
                continue

            seen.add(location)
            sitemap_urls.append(location)

    return sitemap_urls


def _discover_from_sitemap(session, query, candidates):
    """Use sitemap data as a broad generic discovery fallback."""

    query_tokens = tokens(query)
    if not query_tokens:
        return candidates

    for sitemap_url in _sitemap_urls(session):
        if len(candidates) >= MAX_CANDIDATES:
            break

        try:
            response = _request(session, sitemap_url)
        except StoreRequestError:
            continue

        text = response.text or ""

        for raw_url in re.findall(
            r"<loc>\s*([^<]+)\s*</loc>",
            text,
            re.I,
        ):
            url = product_url(clean(raw_url))
            if not url:
                continue

            if query_matches(url, query):
                candidates.setdefault(url, sitemap_url)

        for product in _candidate_product_urls(
            text,
            query,
        ):
            candidates.setdefault(product, sitemap_url)

    return candidates


def discover(session, query):
    """
    Discover product URLs.

    Discovery is generic and query-driven. No product family, brand,
    variant, SKU, price or known-product map is used.
    """

    query = clean(query)
    if not query:
        return [], {
            "status": "success",
            "verified": True,
            "discovery": "empty_query",
        }

    candidates = {}
    visited = set()
    failures = []

    for root in _category_roots():
        try:
            _discover_from_page(
                session,
                root,
                query,
                candidates,
                visited,
            )
        except StoreRequestError as exc:
            failures.append(
                {
                    "status": exc.status,
                    "url": exc.url,
                    "http_status": exc.http_status,
                    "message": str(exc),
                }
            )

        if len(candidates) >= MAX_CANDIDATES:
            break

    if len(candidates) < MAX_CANDIDATES:
        try:
            _discover_from_search(
                session,
                query,
                candidates,
            )
        except StoreRequestError as exc:
            failures.append(
                {
                    "status": exc.status,
                    "url": exc.url,
                    "http_status": exc.http_status,
                    "message": str(exc),
                }
            )

    if len(candidates) < MAX_CANDIDATES:
        try:
            _discover_from_sitemap(
                session,
                query,
                candidates,
            )
        except StoreRequestError as exc:
            failures.append(
                {
                    "status": exc.status,
                    "url": exc.url,
                    "http_status": exc.http_status,
                    "message": str(exc),
                }
            )

    if len(candidates) < MAX_CANDIDATES:
        try:
            _discover_from_sitemap(session, query, candidates)
        except StoreRequestError as exc:
            failures.append(
                {
                    "status": exc.status,
                    "url": exc.url,
                    "http_status": exc.http_status,
                    "message": str(exc),
                }
            )

    urls = list(candidates.keys())[:MAX_CANDIDATES]

    if urls:
        return urls, {
            "status": "success" if not failures else "partial",
            "verified": True,
            "discovery": "catalog_candidates",
            "candidate_count": len(urls),
            "failures": failures,
        }

    if failures:
        first = failures[0]
        return [], {
            "status": first.get("status", "error"),
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


def _jsonld_products(soup):
    products = []

    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            data = json.loads(
                script.get_text(strip=True)
            )
        except Exception:
            continue

        queue = (
            list(data)
            if isinstance(data, list)
            else [data]
        )

        while queue:
            item = queue.pop(0)

            if isinstance(item, list):
                queue.extend(item)
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
            ):
                products.append(item)

            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

    return products


def _selected_size(soup, product):
    h1 = soup.find("h1")
    h1_name = (
        clean(h1.get_text(" ", strip=True))
        if h1
        else ""
    )

    selected = size_ml(h1_name)
    if selected is not None:
        return selected

    selectors = (
        'input[type="radio"][checked]',
        'input[type="radio"][aria-checked="true"]',
        'input[checked][name*="size" i]',
        "option[selected]",
        '[aria-selected="true"]',
    )

    for selector in selectors:
        for node in soup.select(selector):
            values = [
                node.get("value", ""),
                node.get("aria-label", ""),
                node.get("data-value", ""),
                node.get("data-size", ""),
                node.get_text(" ", strip=True),
            ]

            parent = node.parent
            if parent:
                values.append(
                    parent.get_text(" ", strip=True)
                )

            selected = size_ml(*values)
            if selected is not None:
                return selected

    return size_ml(
        product.get("name", ""),
        product.get("description", ""),
    )


def _availability_from_product(product, soup):
    offers = product.get("offers")

    if isinstance(offers, dict):
        offers = [offers]

    if isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue

            state = availability(
                offer.get("availability")
                or offer.get("availabilityStatus")
                or offer.get("stock")
            )

            if state != "unknown":
                return state

    for node in soup.select(
        '[itemprop="availability"], '
        'meta[property="product:availability"], '
        'meta[name="availability"]'
    ):
        state = availability(
            node.get("content")
            or node.get_text(" ", strip=True)
        )
        if state != "unknown":
            return state

    return "unknown"


def _parse_product_page(url, query):
    session = requests.Session()

    try:
        response = _request(session, url)
        soup = BeautifulSoup(
            response.text or "",
            "html.parser",
        )

        products = _jsonld_products(soup)
        if not products:
            return [], {
                "status": "partial",
                "url": url,
                "reason": "no_product_jsonld",
            }

        rows = []

        for product in products:
            name = clean(product.get("name"))
            if not name:
                continue

            if not query_matches(name, query):
                continue

            brand = product.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")

            offers = product.get("offers")
            if isinstance(offers, dict):
                offers = [offers]

            if not isinstance(offers, list):
                offers = []

            image = _image_url(product.get("image"))
            selected_size = _selected_size(
                soup,
                product,
            )
            page_availability = (
                _availability_from_product(
                    product,
                    soup,
                )
            )

            emitted_offer = False

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                number = price_num(
                    offer.get("price")
                )

                if number is None:
                    continue

                state = availability(
                    offer.get("availability")
                    or offer.get("availabilityStatus")
                    or offer.get("stock")
                )

                if state == "unknown":
                    state = page_availability

                rows.append(
                    {
                        "store": STORE,
                        "brand": clean(brand),
                        "name": name,
                        "price": price_text(number),
                        "price_num": number,
                        "url": url,
                        "image": image,
                        "image_url": image,
                        "available": (
                            state != "out_of_stock"
                        ),
                        "availability": state,
                        "size_ml": selected_size,
                        "identity": {
                            "gtin": (
                                {
                                    "value": clean(
                                        product.get("gtin13")
                                        or product.get("gtin")
                                    ),
                                    "source": "jsonld",
                                }
                                if product.get("gtin13")
                                or product.get("gtin")
                                else None
                            ),
                            "mpn": (
                                {
                                    "value": clean(
                                        product.get("mpn")
                                    ),
                                    "source": "jsonld",
                                }
                                if product.get("mpn")
                                else None
                            ),
                            "sku": (
                                {
                                    "value": clean(
                                        product.get("sku")
                                    ),
                                    "source": "jsonld",
                                }
                                if product.get("sku")
                                else None
                            ),
                        },
                    }
                )
                emitted_offer = True

            if not emitted_offer and page_availability == "out_of_stock":
                rows.append(
                    {
                        "store": STORE,
                        "brand": clean(brand),
                        "name": name,
                        "price": None,
                        "price_num": None,
                        "url": url,
                        "image": image,
                        "image_url": image,
                        "available": False,
                        "availability": "out_of_stock",
                        "size_ml": selected_size,
                        "identity": {
                            "gtin": None,
                            "mpn": None,
                            "sku": None,
                        },
                    }
                )

        if rows:
            return rows, {
                "status": "success",
                "url": url,
            }

        return [], {
            "status": "partial",
            "url": url,
            "reason": "product_page_did_not_match_query",
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
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        session.close()


def parse_product(url, query):
    """Public single-product parser kept for diagnostics/tests."""

    rows, _meta = _parse_product_page(
        url,
        clean(query),
    )
    return rows


def _search_stream_generator(query):
    """
    Main scraper contract.

    The caller must never interpret an unverified empty result as NOT_FOUND.
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
                        time.perf_counter() - started,
                        3,
                    ),
                },
            }
            return

    finally:
        session.close()

    if not urls:
        status = discovery_meta.get(
            "status",
            "success",
        )
        verified = bool(
            discovery_meta.get("verified")
        )

        yield {
            "status": status,
            "verified": verified,
            "results": [],
            "error": (
                None
                if verified
                else discovery_meta.get("failures")
            ),
            "details": {
                "stage": "discovery",
                "candidate_count": 0,
                "discovery": discovery_meta.get(
                    "discovery"
                ),
                "elapsed": round(
                    time.perf_counter() - started,
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
                _parse_product_page,
                url,
                query,
            ): url
            for url in urls
        }

        for future in as_completed(futures):
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

            if meta.get("status") not in (
                "success",
                "partial",
            ):
                errors.append(meta)

    seen = set()
    deduped = []

    for row in results:
        key = (
            row.get("url"),
            row.get("size_ml"),
            row.get("price_num"),
            row.get("availability"),
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(row)

    deduped.sort(
        key=lambda item: (
            2
            if item.get("availability")
            == "out_of_stock"
            else 0,
            item.get("price_num")
            if item.get("price_num") is not None
            else 999999,
            item.get("size_ml")
            if item.get("size_ml") is not None
            else 999999,
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
                time.perf_counter() - started,
                3,
            ),
            "discovery": discovery_meta,
        },
    }



def search_stream(query, emit=None):
    """Native ScentHunter callback contract.

    The store implementation below remains the authoritative discovery/fetch
    logic. This adapter only bridges its report-generator form to the common
    callback contract used by main.py.
    """
    report = None
    for value in _search_stream_generator(query):
        report = value
        if isinstance(value, dict) and callable(emit):
            for row in value.get("results") or []:
                if isinstance(row, dict):
                    emit(row)

    if report is None:
        return {
            "status": "error",
            "verified": False,
            "results": [],
            "error": "empty_stream",
            "details": {},
        }

    return report

def search(query):
    """Compatibility API returning only result rows."""

    report = search_stream(query)
    return report.get("results", [])


def scrape(query):
    return search(query)


def search_deloox(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    report = search_stream(args.query)
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )
