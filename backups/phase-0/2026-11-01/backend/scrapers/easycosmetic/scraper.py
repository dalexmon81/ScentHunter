from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Easycosmetic"
BASE_URL = "https://www.easycosmetic.de"
SEARCH_URL = BASE_URL + "/suche?searchfor={}"
TIMEOUT = 5
BROWSER_TIMEOUT_MS = 4000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",

    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

BLOCKED_PATH_PARTS = (
    "/suche",
    "/service",
    "/kontakt",
    "/impressum",
    "/datenschutz",
    "/agb",
    "/versand",
    "/zahlung",
    "/marken",
    "/alle-marken",
    "/ingredients/",
    "/inhaltsstoffe/",
)

BLOCKED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".pdf",
)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalise_text(value: str) -> str:
    value = _clean(value).lower()
    value = re.sub(
        r"(?<=\d)\s*(?=[a-z])|(?<=[a-z])\s*(?=\d)",
        " ",
        value,
        flags=re.UNICODE,
    )
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _normalise_url(url: str) -> str:
    """Canonicalise product URLs for the German Easycosmetic storefront only.

    German storefront URLs are rejected rather than rewritten: regional product
    paths and variant IDs are not guaranteed to be interchangeable, and silently
    converting them could attach a German price to the wrong variant. Tracking
    and unrelated query parameters are discarded while numeric German variant
    IDs are preserved.
    """
    absolute = urljoin(BASE_URL, str(url or ""))
    parsed = urlparse(absolute)

    host = parsed.netloc.lower()
    allowed_hosts = {"easycosmetic.de", "www.easycosmetic.de"}
    if host not in allowed_hosts:
        return ""

    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path

    query = parse_qs(parsed.query, keep_blank_values=False)
    variant_values = query.get("variant", [])
    variant = ""
    for value in variant_values:
        candidate = _clean(value)
        if candidate.isdigit():
            variant = candidate
            break

    # Keep the exact official regional host that was requested.
    canonical = f"{parsed.scheme or 'https'}://{host}{path}".rstrip("/")
    if variant:
        canonical = f"{canonical}?variant={variant}"
    return canonical


def _query_tokens(query: str) -> List[str]:
    return [x for x in _normalise_text(query).split() if len(x) >= 2]


def _is_candidate_url(url: str) -> bool:
    if not url:
        return False

    parsed = urlparse(url)
    if parsed.netloc.lower() not in {
        "easycosmetic.de",
        "www.easycosmetic.de",
    }:
        return False

    path = parsed.path.lower()

    # Easycosmetic product URLs are not guaranteed to end in .aspx.
    # Keep the official-host and utility-path checks, but do not discard a
    # product solely because its URL format changed.
    if path in {"/", "/parfum", "/damenparfum", "/herrenparfum", "/neuheiten"}:
        return False

    if any(part in path for part in BLOCKED_PATH_PARTS):
        return False

    if path.endswith(BLOCKED_EXTENSIONS):
        return False

    return True


def _candidate_score(query: str, text: str, url: str) -> int:
    tokens = _query_tokens(query)
    if not tokens:
        return 0

    haystack = _normalise_text(f"{text} {url}")
    normalized_query = _normalise_text(query)
    score = 0

    for token in tokens:
        if token in haystack:
            score += 10

    if normalized_query and normalized_query in haystack:
        score += 25

    return score


class StoreRequestError(RuntimeError):
    def __init__(self, status: str, message: str, *, http_status: int | None = None):
        super().__init__(message)
        self.status = status
        self.http_status = http_status


def _request_html(url: str) -> str:
    request_error = None
    try:
        response = requests.get(
            url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True
        )
        final_host = urlparse(response.url).netloc.lower()
        if final_host not in {"easycosmetic.de", "www.easycosmetic.de"}:
            response.close()
            raise StoreRequestError(
                "error",
                f"German storefront redirected outside easycosmetic.de: {response.url}",
                http_status=response.status_code,
            )
        if 200 <= response.status_code < 400:
            return response.text

        code = response.status_code
        status = (
            "blocked" if code in {403, 429}
            else "unavailable" if 500 <= code <= 599
            else "error"
        )
        request_error = StoreRequestError(
            status, f"HTTP {code} for {url}", http_status=code
        )
        response.close()
    except requests.Timeout as exc:
        request_error = StoreRequestError("timeout", str(exc))
    except requests.ConnectionError as exc:
        request_error = StoreRequestError("unavailable", str(exc))
    except requests.RequestException as exc:
        request_error = StoreRequestError("error", str(exc))

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="de-DE",
                    extra_http_headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
},
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
                final_host = urlparse(page.url).netloc.lower()
                if final_host not in {"easycosmetic.de", "www.easycosmetic.de"}:
                    raise RuntimeError(
                        f"German storefront redirected outside easycosmetic.de: {page.url}"
                    )
                html = page.content()
                if not html or len(html) < 500:
                    raise RuntimeError(f"browser returned insufficient HTML for {url}")
                return html
            finally:
                browser.close()
    except Exception as browser_error:
        if request_error is not None:
            raise StoreRequestError(
                request_error.status,
                f"{request_error}; browser fallback failed "
                f"({type(browser_error).__name__}: {browser_error})",
                http_status=request_error.http_status,
            ) from browser_error
        raise StoreRequestError("error", str(browser_error)) from browser_error

def _extract_json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        raw = raw.strip()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        if isinstance(data, dict):
            items.append(data)
        elif isinstance(data, list):
            items.extend(x for x in data if isinstance(x, dict))

    return items


def _walk_json_ld(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_ld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_ld(child)


def _find_product_json(
    soup: BeautifulSoup,
    requested_url: str = "",
) -> Optional[Dict[str, Any]]:
    """Select the JSON-LD Product corresponding to the requested variant URL.

    Easycosmetic can embed Product objects for multiple bottle sizes in one
    document. Selecting the first Product assigns its size, image, price and
    stock status to every variant URL.
    """
    products: List[Dict[str, Any]] = []
    for item in _extract_json_ld(soup):
        for node in _walk_json_ld(item):
            item_type = node.get("@type")
            if item_type == "Product" or (
                isinstance(item_type, list) and "Product" in item_type
            ):
                products.append(node)

    if not products:
        return None

    requested_values = parse_qs(urlparse(requested_url).query).get("variant", [])
    requested_variant = requested_values[0] if requested_values else ""
    if requested_variant:
        for product in products:
            candidate_urls: List[str] = []
            product_url = product.get("url")
            if isinstance(product_url, str):
                candidate_urls.append(product_url)

            offers = product.get("offers")
            offer_list = offers if isinstance(offers, list) else [offers]
            for offer in offer_list:
                if isinstance(offer, dict):
                    offer_url = offer.get("url")
                    if isinstance(offer_url, str):
                        candidate_urls.append(offer_url)

            for candidate_url in candidate_urls:
                candidate_values = parse_qs(
                    urlparse(candidate_url).query
                ).get("variant", [])
                if candidate_values and candidate_values[0] == requested_variant:
                    return product

    # A variant URL with no matching structured object must not silently be
    # assigned another variant's JSON-LD data. Return None so callers can use
    # the requested URL and selected-image evidence instead.
    if requested_variant:
        return None

    return products[0]


def _extract_image_url(value: Any) -> str:
    if isinstance(value, str):
        value = value.strip()
        if value:
            return urljoin(BASE_URL, value)
        return ""

    if isinstance(value, dict):
        for key in ("contentUrl", "url", "src", "image"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return urljoin(BASE_URL, candidate.strip())
        return ""

    if isinstance(value, list):
        for item in value:
            image = _extract_image_url(item)
            if image:
                return image

    return ""


def _extract_image_url_for_size(value: Any, size_ml: Optional[int]) -> str:
    """Choose an image for the parsed bottle size when JSON-LD exposes several."""
    if size_ml is None:
        return _extract_image_url(value)

    candidates: List[str] = []

    def collect(item: Any) -> None:
        if isinstance(item, str):
            candidate = item.strip()
            if candidate:
                candidates.append(urljoin(BASE_URL, candidate))
        elif isinstance(item, dict):
            for key in ("contentUrl", "url", "src", "image"):
                child = item.get(key)
                if isinstance(child, (str, dict, list)):
                    collect(child)
        elif isinstance(item, list):
            for child in item:
                collect(child)

    collect(value)
    for candidate in candidates:
        if re.search(rf"(?<!\d){size_ml}\s?ml\b", candidate, flags=re.I):
            return candidate
    return candidates[0] if candidates else ""


def _extract_page_image(
    soup: BeautifulSoup,
    product_name: str = "",
) -> str:
    selectors = (
        'meta[property="og:image"]',
        'meta[property="og:image:url"]',
        'meta[name="twitter:image"]',
    )

    for selector in selectors:
        meta = soup.select_one(selector)
        if meta:
            image = _extract_image_url(meta.get("content"))
            if image:
                return image

    normalized_product = _normalise_text(product_name)

    if normalized_product:
        for img in soup.find_all("img"):
            descriptive = _normalise_text(
                f"{img.get('alt', '')} {img.get('title', '')}"
            )

            if normalized_product in descriptive or (
                descriptive
                and all(
                    token in descriptive
                    for token in normalized_product.split()
                    if len(token) >= 3
                )
            ):
                for attribute in (
                    "src",
                    "data-src",
                    "data-original",
                    "data-lazy-src",
                ):
                    image = _extract_image_url(img.get(attribute))
                    if image:
                        return image

    for img in soup.find_all("img"):
        for attribute in (
            "src",
            "data-src",
            "data-original",
            "data-lazy-src",
        ):
            image = _extract_image_url(img.get(attribute))
            if image and "cdn2.easycosmetic.de" in image.lower():
                return image

    return ""


def _price_to_float(value: Any) -> Optional[float]:
    if value is None:
        return None

    raw = _clean(value)
    raw = re.sub(r"[^\d,.\-]", "", raw)

    if not raw:
        return None

    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")

    try:
        return float(raw)
    except ValueError:
        return None


def _extract_price_from_text(text: str) -> Optional[float]:
    patterns = (
        r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*€",
        r"(\d+(?:,\d{2}))\s*€",
        r"€\s*(\d{1,3}(?:\.\d{3})*,\d{2})",
        r"€\s*(\d+(?:,\d{2}))",
        r"(\d{1,3}(?:,\d{3})*\.\d{2})\s*€",
        r"€\s*(\d{1,3}(?:,\d{3})*\.\d{2})",
    )

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = _price_to_float(match.group(1))
            if value is not None:
                return value

    return None


def _extract_selected_variant_price(soup: BeautifulSoup) -> Optional[float]:
    """Read the displayed price from the product detail, not recommendations.

    Easycosmetic's JSON-LD can contain a stale/cached offer that differs from
    the price currently shown for the selected bottle size. Prefer a price
    explicitly attached to the product detail (itemprop/data-price or a
    product-price element); never scan the whole document for the first euro
    amount, because variant selectors and recommendation cards contain other
    prices.
    """
    h1 = soup.find("h1")
    if h1 is None:
        return None

    # Walk outward from the title and stop at a bounded product-detail scope.
    # This avoids accidentally selecting a price from a recommendation grid.
    roots = []
    node = h1
    for _ in range(7):
        if node is None:
            break
        if getattr(node, "name", None) in {"main", "article"}:
            roots.append(node)
            break
        classes = " ".join(node.get("class", [])).lower() if getattr(node, "attrs", None) else ""
        node_id = str(node.get("id") or "").lower() if getattr(node, "attrs", None) else ""
        if any(marker in f"{classes} {node_id}" for marker in (
            "product-detail", "productdetail", "product-info", "productinfo",
            "product-price", "productpage", "product-page", "product__info",
        )):
            roots.append(node)
            break
        node = node.parent

    # Also check the nearest section/container around the title if the site
    # doesn't use a recognizable product-detail class.
    if not roots:
        node = h1
        for _ in range(4):
            node = getattr(node, "parent", None)
            if node is None:
                break
            if getattr(node, "name", None) in {"section", "article", "main"}:
                roots.append(node)
                break
    if not roots:
        return None

    root = roots[0]
    # Visible price nodes must win over metadata. Easycosmetic sometimes
    # leaves an outdated itemprop/meta price in the HTML while the selected
    # variant's visible price is already updated. Metadata is a last resort.
    selectors = (
        '[class*="product-price"]', '[class*="price-current"]',
        '[class*="priceCurrent"]', '[class~="price"]',
        '[data-price]', '[itemprop="price"]', 'meta[itemprop="price"]',
    )
    rejected = ("old", "was", "strike", "cross", "regular", "uvp", "list-price", "discount-percent")
    for selector in selectors:
        for element in root.select(selector):
            classes = " ".join(element.get("class", [])).lower()
            element_id = str(element.get("id") or "").lower()
            if any(marker in f"{classes} {element_id}" for marker in rejected):
                continue
            raw = element.get("content") or element.get("data-price") or element.get_text(" ", strip=True)
            price = _price_to_float(raw)
            if price is None:
                price = _extract_price_from_text(_clean(raw))
            if price is not None and price > 0:
                return price
    return None


def _extract_brand(product_json: Dict[str, Any]) -> str:
    brand = product_json.get("brand")

    if isinstance(brand, dict):
        return _clean(brand.get("name"))

    if isinstance(brand, list):
        for item in brand:
            name = _clean(item.get("name") if isinstance(item, dict) else item)
            if name:
                return name
        return ""

    return _clean(brand)


def _extract_offer_data(
    product_json: Dict[str, Any],
) -> Tuple[Optional[float], str, str]:
    offers = product_json.get("offers")

    if isinstance(offers, dict):
        return (
            _price_to_float(offers.get("price")),
            _clean(offers.get("priceCurrency")) or "EUR",
            _clean(offers.get("availability")),
        )

    if isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue

            price = _price_to_float(offer.get("price"))
            currency = _clean(offer.get("priceCurrency")) or "EUR"
            availability = _clean(offer.get("availability"))

            if price is not None or availability:
                return price, currency, availability

    return None, "EUR", ""


def _availability_from_page(text: str) -> Tuple[Optional[bool], str]:
    normalized = _normalise_text(text)

    if "nicht auf lager" in normalized:
        return False, "Out of stock"
    if "ausverkauft" in normalized:
        return False, "Out of stock"
    if "nicht verfugbar" in normalized:
        return False, "Unavailable"
    if "auf lager" in normalized:
        return True, "In stock"
    if "sofort lieferbar" in normalized:
        return True, "In stock"
    if "lieferbar" in normalized:
        return True, "Available"

    # Unknown is not the same as in stock. Do not turn a missing stock signal
    # into a positive availability claim.
    return None, ""


def _extract_candidate_links(
    soup: BeautifulSoup,
    query: str,
) -> List[Dict[str, Any]]:
    candidates: Dict[str, Dict[str, Any]] = {}

    def add(url: str, text: str) -> None:
        url = _normalise_url(url)
        if not _is_candidate_url(url):
            return

        normalized_candidate_text = _normalise_text(
            f"{text} {url}"
        )

        bundle_markers = (
            "box",
            "gift set",
            "set",
            "geschenkset",
            "duftset",
            "parfumset",
            "bundle",
            "duo",
            "trio",
            "discovery set",
            "coffret",
        )

        for marker in bundle_markers:
            marker_normalized = _normalise_text(marker)
            if not marker_normalized:
                continue

            if re.search(
                rf"\b{re.escape(marker_normalized)}\b",
                normalized_candidate_text,
            ):
                return

        score = _candidate_score(query, text, url)
        if score <= 0:
            return

        current = candidates.get(url)
        row = {
            "shop": STORE,
            "url": url,
            "name": _clean(text),
            "_score": score,
        }

        if current is None or score > current["_score"]:
            candidates[url] = row

    for link in soup.find_all("a", href=True):
        add(link.get("href", ""), link.get_text(" ", strip=True))

    for item in _extract_json_ld(soup):
        for node in _walk_json_ld(item):
            if _clean(node.get("@type")) != "Product":
                continue

            url = node.get("url")
            name = node.get("name")
            if isinstance(url, str):
                add(url, _clean(name))

    ordered = sorted(
        candidates.values(),
        key=lambda item: (-item["_score"], item["url"]),
    )

    for item in ordered:
        item.pop("_score", None)

    return ordered


def _extract_variant_urls(html: str, product_url: str) -> List[str]:
    """Find variant IDs only from links/data explicitly tied to the same
    German product path. German links are rejected, never rewritten."""

    base = _normalise_url(product_url)
    parsed_base = urlparse(base)
    if not base or not parsed_base.path:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    candidates = set()

    def consider(raw_value: str) -> None:
        if not raw_value:
            return

        value = (
            str(raw_value)
            .replace("\\/", "/")
            .replace("&amp;", "&")
            .replace("\\u0026", "&")
        )

        for match in re.finditer(
            r"""https?://[^"'\s<>]+|/[^"'\s<>]+""",
            value,
            flags=re.IGNORECASE,
        ):
            raw_url = match.group(0)
            absolute = urljoin(base, raw_url)
            parsed = urlparse(absolute)

            host = (parsed.hostname or "").lower().rstrip(".")
            if host not in {"easycosmetic.de", "www.easycosmetic.de"}:
                continue

            if parsed.path.rstrip("/") != parsed_base.path.rstrip("/"):
                continue

            params = parse_qs(parsed.query, keep_blank_values=False)
            variant_values = params.get("variant", [])
            if variant_values and variant_values[0].isdigit():
                candidates.add(variant_values[0])

        for match in re.finditer(
            r"""(?:data-variant(?:-id)?|data-product-variant|variantId|variant_id)"""
            r"""\s*["']?\s*[:=]\s*["']?(\d+)""",
            value,
            flags=re.IGNORECASE,
        ):
            candidates.add(match.group(1))

    for tag in soup.find_all(True):
        for attr, value in tag.attrs.items():
            if isinstance(value, list):
                value = " ".join(str(x) for x in value)

            if not isinstance(value, str):
                continue

            attr_name = attr.lower()
            if (
                "variant" in attr_name
                or "easycosmetic" in value.lower()
                or ".aspx" in value.lower()
            ):
                consider(value)

    for script in soup.find_all("script"):
        consider(script.string or script.get_text(" ", strip=False))

    return sorted(
        {
            f"https://www.easycosmetic.de{parsed_base.path}?variant={variant_id}"
            for variant_id in candidates
            if variant_id.isdigit()
        }
    )


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        search._last_product_errors = []
        search._last_candidate_count = 0
        search._last_variant_url_count = 0
        return []

    html = _request_html(SEARCH_URL.format(quote_plus(query)))
    soup = BeautifulSoup(html, "html.parser")
    candidates = _extract_candidate_links(soup, query)
    errors: List[Exception] = []

    # Fetch candidate pages concurrently. The previous implementation fetched
    # each page serially and then fetched every variant again during parsing,
    # multiplying latency by the number of search results and bottle sizes.
    max_workers = min(8, max(1, len(candidates)))
    page_html: Dict[str, str] = {}

    def fetch_candidate(candidate: Dict[str, Any]):
        url = _normalise_url(candidate.get("url", ""))
        if not url:
            return url, None, None
        try:
            return url, _request_html(url), None
        except Exception as exc:
            return url, None, exc

    if candidates:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(fetch_candidate, candidate) for candidate in candidates]
            for future in as_completed(futures):
                url, candidate_html, error = future.result()
                if error is not None:
                    errors.append(error)
                elif url and candidate_html:
                    page_html[url] = candidate_html

    # Discover variants from candidate HTML already fetched above.
    product_urls: List[str] = []
    seen_urls = set()
    for candidate in candidates:
        url = _normalise_url(candidate.get("url", ""))
        if not url:
            continue
        candidate_html = page_html.get(url)
        discovered = _extract_variant_urls(candidate_html, url) if candidate_html else []
        for variant_url in discovered:
            variant_url = _normalise_url(variant_url)
            if variant_url and variant_url not in seen_urls:
                seen_urls.add(variant_url)
                product_urls.append(variant_url)
        if url not in seen_urls:
            seen_urls.add(url)
            product_urls.append(url)

    # Fetch only the variants not already fetched as candidate pages, in
    # parallel, and parse the same response. This avoids duplicate requests.
    missing_urls = [url for url in product_urls if url not in page_html]
    if missing_urls:
        with ThreadPoolExecutor(max_workers=min(8, len(missing_urls))) as pool:
            future_to_url = {pool.submit(_request_html, url): url for url in missing_urls}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    page_html[url] = future.result()
                except Exception as exc:
                    errors.append(exc)

    results: List[Dict[str, Any]] = []
    for url in product_urls:
        page = page_html.get(url)
        if not page:
            continue
        try:
            row = _parse_product_html(url, page)
        except Exception as exc:
            errors.append(exc)
            continue
        if row:
            results.append(row)

    # Keep distinct selected variant URLs even when product names are identical.
    deduplicated = {}
    for row in results:
        row_url = _normalise_url(row.get("url", ""))
        if row_url:
            deduplicated[row_url] = row
    results = list(deduplicated.values())

    search._last_product_errors = errors
    search._last_candidate_count = len(candidates)
    search._last_variant_url_count = len(product_urls)
    return results



def search_stream(query: str, emit=None):
    query = _clean(query)
    if not query:
        return {
            "status": "success", "verified": True, "results": [],
            "error": None, "details": {"reason": "empty_query"},
        }

    try:
        results = search(query)
    except StoreRequestError as exc:
        return {
            "status": exc.status, "verified": False, "results": [],
            "error": str(exc), "details": {"http_status": exc.http_status},
        }
    except requests.Timeout as exc:
        return {"status": "timeout", "verified": False, "results": [],
                "error": str(exc), "details": {}}
    except requests.ConnectionError as exc:
        return {"status": "unavailable", "verified": False, "results": [],
                "error": str(exc), "details": {}}
    except Exception as exc:
        return {
            "status": "error", "verified": False, "results": [],
            "error": str(exc), "details": {"exception": type(exc).__name__},
        }

    results = results if isinstance(results, list) else []
    if emit is not None:
        for row in results:
            emit(row)

    if results:
        return {
            "status": "success", "verified": True, "results": results,
            "error": None, "details": {"count": len(results)},
        }

    errors = getattr(search, "_last_product_errors", []) or []
    if errors:
        first = errors[0]
        if isinstance(first, StoreRequestError):
            return {
                "status": first.status, "verified": False, "results": [],
                "error": str(first),
                "details": {
                    "candidate_count": getattr(search, "_last_candidate_count", 0),
                    "error_count": len(errors),
                    "http_status": first.http_status,
                },
            }
        return {
            "status": "partial", "verified": False, "results": [],
            "error": str(first),
            "details": {
                "candidate_count": getattr(search, "_last_candidate_count", 0),
                "error_count": len(errors),
            },
        }

    return {
        "status": "success", "verified": True, "results": [],
        "error": None,
        "details": {
            "candidate_count": getattr(search, "_last_candidate_count", 0),
            "reason": "verified_empty_search",
        },
    }

def _extract_size_ml(
    soup: BeautifulSoup,
    product_name: str,
    url: str,
    product_image: str = "",
    product_json: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Extract size without borrowing evidence from a different variant."""
    def parse_size(value: Any) -> Optional[int]:
        text = _clean(value)
        if not text:
            return None
        matches = re.findall(
            r"(?<!\d)(\d{1,4}(?:[.,]\d{1,2})?)\s*(ml|milliliter|millilitre|liter|litre|l)\b",
            text,
            flags=re.I,
        )
        for number, unit in matches:
            try:
                amount = float(number.replace(",", "."))
            except ValueError:
                continue
            if unit.lower() in {"l", "liter", "litre"}:
                amount *= 1000
            if 1 <= amount <= 10000 and amount.is_integer():
                return int(amount)
        return None

    has_variant = bool(parse_qs(urlparse(url).query).get("variant"))

    if has_variant:
        # The .de storefront often omits the selected article number from
        # visible text, while the selected main product image contains the
        # bottle size in its alt text or filename (for example "-10ml.png").
        # Prefer that selected image over JSON-LD images, which can be stale
        # or describe a different variant.
        product_tokens = [
            token for token in _normalise_text(product_name).split()
            if len(token) >= 3
        ]
        main_image = soup.select_one(
            ".content-left img.product, img.product, "
            ".product-image img, #product-image img"
        )
        image_candidates = []
        if main_image:
            image_candidates.append(" ".join((
                str(main_image.get("alt") or ""),
                str(main_image.get("title") or ""),
                str(main_image.get("src") or ""),
                str(main_image.get("data-src") or ""),
            )))
        if product_image:
            image_candidates.append(product_image)

        for description in image_candidates:
            normalized = _normalise_text(description)
            # Require product-name evidence in the image description to avoid
            # interpreting unrelated gallery artwork as the selected bottle.
            if product_tokens and all(token in normalized for token in product_tokens):
                size = parse_size(description)
                if size is not None:
                    return size

        # Selected size controls are also valid when the markup explicitly
        # marks them as selected. Do not fall back to generic H1/JSON-LD text
        # for variant URLs, because it may describe another size.
        for node in soup.select(
            'option[selected], input[type="radio"][checked], '
            'input[type="radio"][aria-checked="true"], '
            '[aria-selected="true"], [aria-checked="true"]'
        ):
            size = parse_size(" ".join((
                node.get_text(" ", strip=True),
                str(node.get("value") or ""),
                str(node.get("aria-label") or ""),
                str(node.get("title") or ""),
                str(node.get("data-value") or ""),
            )))
            if size is not None:
                return size
        return None

    # Non-variant product pages retain the existing text/JSON-LD fallbacks.
    for value in (product_name, url):
        size = parse_size(value)
        if size is not None:
            return size

    if isinstance(product_json, dict):
        for key in ("name", "description"):
            size = parse_size(product_json.get(key))
            if size is not None:
                return size
        selected_image = _extract_image_url(product_json.get("image"))
        if selected_image:
            size = parse_size(selected_image)
            if size is not None:
                return size

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text(" ", strip=True)
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        objects = payload if isinstance(payload, list) else [payload]
        while objects:
            obj = objects.pop(0)
            if not isinstance(obj, dict):
                continue
            if isinstance(obj.get("@graph"), list):
                objects.extend(obj["@graph"])
            if isinstance(obj.get("mainEntity"), dict):
                objects.append(obj["mainEntity"])
            item_type = obj.get("@type")
            if item_type == "Product" or (
                isinstance(item_type, list) and "Product" in item_type
            ):
                for key in ("name", "description"):
                    size = parse_size(obj.get(key))
                    if size is not None:
                        return size

    for node in soup.select(
        'option[selected], input[type="radio"][checked], '
        'input[type="radio"][aria-checked="true"], '
        '[aria-selected="true"], [aria-checked="true"]'
    ):
        size = parse_size(" ".join((
            node.get_text(" ", strip=True),
            str(node.get("value") or ""),
            str(node.get("aria-label") or ""),
            str(node.get("title") or ""),
            str(node.get("data-value") or ""),
        )))
        if size is not None:
            return size

    size = parse_size(product_image)
    if size is not None:
        return size

    return None

def _parse_product_html(url: str, html: str) -> Optional[Dict[str, Any]]:
    url = _normalise_url(url)

    if not _is_candidate_url(url):
        return None

    soup = BeautifulSoup(html or "", "html.parser")
    product_json = _find_product_json(soup, url)

    name = ""
    brand = ""
    price: Optional[float] = None
    currency = "EUR"
    availability = ""
    image = ""

    # Proven fix:
    # Easycosmetic's visible H1 is the authoritative product identity.
    # JSON-LD is still used for brand/offer/image data and is used as
    # a fallback name only when no H1 is available.
    h1 = soup.find("h1")
    if h1:
        name = _clean(h1.get_text(" ", strip=True))

    if product_json:
        jsonld_name = _clean(product_json.get("name"))

        if not name:
            name = jsonld_name

        brand = _extract_brand(product_json)
        price, currency, availability = _extract_offer_data(product_json)
        image = _extract_image_url(product_json.get("image"))

    if not image:
        image = _extract_page_image(soup, name)

    page_text = _clean(soup.get_text(" ", strip=True))

    # The visible price on the German product detail is authoritative for
    # this storefront, with or without a ?variant= parameter. JSON-LD can be
    # cached or can describe a different regional/default offer. Only use the
    # narrowly scoped product-detail price; never guess from arbitrary page text.
    displayed_price = _extract_selected_variant_price(soup)
    if displayed_price is not None:
        price = displayed_price

    page_available, page_availability = _availability_from_page(page_text)

    available = page_available
    if availability:
        normalized = _normalise_text(availability)
        # Schema.org availability often arrives as a URL, e.g.
        # https://schema.org/OutOfStock. Normalization turns that into tokens
        # such as "https schema org outofstock", not "out of stock".
        compact = re.sub(r"[^a-z0-9]+", "", normalized)

        if any(
            marker in normalized or marker in compact
            for marker in (
                "out of stock",
                "outofstock",
                "sold out",
                "soldout",
                "nicht auf lager",
                "ausverkauft",
                "unavailable",
                "nicht verfugbar",
                "discontinued",
            )
        ):
            available = False
            availability = "Out of stock"
        elif any(
            marker in normalized or marker in compact
            for marker in (
                "in stock",
                "instock",
                "limited availability",
                "limitedavailability",
                "online only",
                "onlineonly",
                "auf lager",
                "lieferbar",
                "available",
                "verfugbar",
            )
        ):
            available = True
            availability = "In stock"
        elif "preorder" in compact or "pre order" in normalized:
            available = None
            availability = "Preorder"
        else:
            # Preserve an unknown signal as unknown instead of trusting a
            # potentially contradictory page-text heuristic.
            available = None
    else:
        availability = page_availability

    if not name:
        return None

    size_ml = _extract_size_ml(
        soup, name, url, image, product_json=product_json
    )
    if product_json:
        # Some Easycosmetic Product objects expose multiple images. Select the
        # one matching the parsed bottle size instead of blindly taking index 0.
        variant_image = _extract_image_url_for_size(
            product_json.get("image"), size_ml
        )
        if variant_image:
            image = variant_image

    return {
        "shop": STORE,
        "brand": brand,
        "name": name,
        "price": f"{price:.2f} €" if price is not None else None,
        "price_num": price,
        "currency": currency or "EUR",
        "available": available,
        "availability": availability,
        "image": image,
        "size_ml": size_ml,
        "url": url,
    }


def extract_product_page(session, url: str, slug: str = "", html: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parse a German storefront page while preserving regional provenance.

    The catalog engine validates the final response host before calling this
    adapter and passes the HTML from that same response. Reusing that HTML
    avoids a second request that could time out or return different variant
    content. Standalone callers without HTML use the guarded request helper,
    which rejects redirects outside easycosmetic.de.
    """
    normalized_url = _normalise_url(url)
    if not _is_candidate_url(normalized_url):
        return None

    if html is not None:
        return _parse_product_html(normalized_url, html)

    german_html = _request_html(normalized_url)
    return _parse_product_html(normalized_url, german_html)


def parse_product(url: str) -> Optional[Dict[str, Any]]:
    """Standalone scraper entry point used by diagnostics and direct callers."""
    normalized_url = _normalise_url(url)
    if not _is_candidate_url(normalized_url):
        return None
    return _parse_product_html(normalized_url, _request_html(normalized_url))


def diagnose(query: str) -> Dict[str, Any]:
    query = _clean(query)

    report: Dict[str, Any] = {
        "diagnostic": True,
        "store": STORE,
        "query": query,
        "search_url": SEARCH_URL.format(quote_plus(query)) if query else None,
        "candidate_count": 0,
        "candidates": [],
        "products": [],
        "errors": [],
    }

    if not query:
        return report

    try:
        candidates = search(query)
    except Exception as exc:
        report["errors"].append({
            "stage": "search",
            "error": f"{type(exc).__name__}: {exc}",
        })
        return report

    report["candidate_count"] = len(candidates)
    report["candidates"] = candidates[:20]

    for candidate in candidates[:10]:
        url = candidate.get("url")
        if not url:
            continue

        try:
            product = parse_product(url)
            if product:
                report["products"].append(product)
        except Exception as exc:
            report["errors"].append({
                "stage": "parse_product",
                "url": url,
                "error": f"{type(exc).__name__}: {exc}",
            })

    return report


if __name__ == "__main__":
    result = diagnose("Dior")
    print(json.dumps(result, ensure_ascii=False, indent=2))
