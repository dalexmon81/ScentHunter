from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Easycosmetic"
BASE_URL = "https://www.easycosmetic.de"
SEARCH_URL = BASE_URL + "/suche?searchfor={}"
TIMEOUT = 15
BROWSER_TIMEOUT_MS = 15000

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
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
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
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _normalise_url(url: str) -> str:
    absolute = urljoin(BASE_URL, str(url or ""))
    parsed = urlparse(absolute)

    if parsed.netloc.lower() not in {"easycosmetic.de", "www.easycosmetic.de"}:
        return ""

    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path

    # Product URLs on Easycosmetic are stable without query/fragment.
    return f"{BASE_URL}{path}".rstrip("/")


def _query_tokens(query: str) -> List[str]:
    return [x for x in _normalise_text(query).split() if len(x) >= 2]


def _is_candidate_url(url: str) -> bool:
    if not url:
        return False

    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"easycosmetic.de", "www.easycosmetic.de"}:
        return False

    path = parsed.path.lower()

    if not path.endswith(".aspx"):
        return False

    if any(part in path for part in BLOCKED_PATH_PARTS):
        return False

    if path.endswith(BLOCKED_EXTENSIONS):
        return False

    return True


def _is_bundle_product(name: str) -> bool:
    """
    Reject obvious multi-product sets/boxes from single-product searches.

    This is intentionally conservative: only explicit bundle/box/set terms
    are rejected, so normal product-family searches remain broad.
    """
    normalized = _normalise_text(name)

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

    return any(marker in normalized for marker in bundle_markers)


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

    if _is_bundle_product(text):
        score -= 1000

    return score


def _request_html(url: str) -> str:
    """
    Primary HTTP path.

    If Easycosmetic rejects the requests client (403/429/5xx) or the
    connection fails, fall back to a real Chromium page. This keeps the
    scraper generic and avoids making the whole store fail just because
    the retailer treats Render's HTTP client differently from a browser.
    """
    request_error: Optional[Exception] = None

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if 200 <= response.status_code < 400:
            return response.text

        request_error = requests.HTTPError(
            f"HTTP {response.status_code} for {url}"
        )

        # A browser fallback is particularly useful for bot/rate-limit
        # responses. Do not silently accept an error page as HTML.
        if response.status_code not in {403, 429, 500, 502, 503, 504}:
            response.raise_for_status()

    except requests.RequestException as exc:
        request_error = exc

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="de-DE",
                    extra_http_headers={
                        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"
                    },
                )
                page = context.new_page()
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=BROWSER_TIMEOUT_MS,
                )
                html = page.content()
                if not html or len(html) < 500:
                    raise RuntimeError(
                        f"browser returned insufficient HTML for {url}"
                    )
                return html
            finally:
                browser.close()

    except Exception as browser_error:
        if request_error is not None:
            raise RuntimeError(
                f"HTTP failed ({type(request_error).__name__}: "
                f"{request_error}); browser fallback failed "
                f"({type(browser_error).__name__}: {browser_error})"
            ) from browser_error
        raise


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


def _find_product_json(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    for item in _extract_json_ld(soup):
        for node in _walk_json_ld(item):
            item_type = node.get("@type")
            if item_type == "Product":
                return node
            if isinstance(item_type, list) and "Product" in item_type:
                return node
    return None


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


def _availability_from_page(text: str) -> Tuple[bool, str]:
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

    return True, ""


def _extract_candidate_links(
    soup: BeautifulSoup,
    query: str,
) -> List[Dict[str, Any]]:
    candidates: Dict[str, Dict[str, Any]] = {}

    def add(url: str, text: str) -> None:
        url = _normalise_url(url)
        if not _is_candidate_url(url):
            return

        if _is_bundle_product(text):
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

    # Normal search-result anchors.
    for link in soup.find_all("a", href=True):
        add(link.get("href", ""), link.get_text(" ", strip=True))

    # Some Easycosmetic pages expose product URLs in structured data.
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


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)

    if not query:
        return []

    search_url = SEARCH_URL.format(quote_plus(query))
    html = _request_html(search_url)
    soup = BeautifulSoup(html, "html.parser")

    return _extract_candidate_links(soup, query)


def parse_product(url: str) -> Optional[Dict[str, Any]]:
    url = _normalise_url(url)

    if not _is_candidate_url(url):
        return None

    html = _request_html(url)
    soup = BeautifulSoup(html, "html.parser")
    product_json = _find_product_json(soup)

    name = ""
    brand = ""
    price: Optional[float] = None
    currency = "EUR"
    availability = ""
    image = ""

    if product_json:
        name = _clean(product_json.get("name"))
        brand = _extract_brand(product_json)
        price, currency, availability = _extract_offer_data(product_json)

        image_data = product_json.get("image")
        if isinstance(image_data, str):
            image = image_data
        elif isinstance(image_data, list) and image_data:
            image = _clean(image_data[0])

    if not name:
        h1 = soup.find("h1")
        if h1:
            name = _clean(h1.get_text(" ", strip=True))

    page_text = _clean(soup.get_text(" ", strip=True))

    if price is None:
        price = _extract_price_from_text(page_text)

    page_available, page_availability = _availability_from_page(page_text)

    available = page_available
    if availability:
        normalized = _normalise_text(availability)

        if any(
            marker in normalized
            for marker in (
                "out of stock",
                "nicht auf lager",
                "ausverkauft",
                "unavailable",
                "nicht verfugbar",
            )
        ):
            available = False
        elif any(
            marker in normalized
            for marker in (
                "in stock",
                "auf lager",
                "lieferbar",
                "available",
                "verfugbar",
            )
        ):
            available = True
    else:
        availability = page_availability

    if not name:
        return None

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
        "url": url,
    }


def search_stream(query: str, emit=None):
    candidates = search(query)

    def rows():
        for candidate in candidates:
            url = candidate.get("url")
            if not url:
                continue

            try:
                row = parse_product(url)
            except Exception:
                # A single bad product must never kill the whole store.
                continue

            if row:
                yield row

    if callable(emit):
        for row in rows():
            emit(row)
        return None

    return rows()


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
    result = diagnose("Liquid Brun")
    print(json.dumps(result, ensure_ascii=False, indent=2))
