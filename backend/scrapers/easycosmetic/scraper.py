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
    value = re.sub(
        r"(?<=\d)\s*(?=[a-z])|(?<=[a-z])\s*(?=\d)",
        " ",
        value,
        flags=re.UNICODE,
    )
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
                    extra_http_headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"},
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
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


def _find_product_json(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    for item in _extract_json_ld(soup):
        for node in _walk_json_ld(item):
            item_type = node.get("@type")
            if item_type == "Product":
                return node
            if isinstance(item_type, list) and "Product" in item_type:
                return node
    return None


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


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        search._last_product_errors = []
        search._last_candidate_count = 0
        return []

    try:
        html = _request_html(SEARCH_URL.format(quote_plus(query)))
    except Exception:
        raise

    soup = BeautifulSoup(html, "html.parser")
    candidates = _extract_candidate_links(soup, query)
    results: List[Dict[str, Any]] = []
    product_errors = []

    for candidate in candidates:
        url = candidate.get("url")
        if not url:
            continue
        try:
            row = parse_product(url)
        except StoreRequestError as exc:
            product_errors.append(exc)
            continue
        except Exception as exc:
            product_errors.append(exc)
            continue
        if row:
            results.append(row)

    search._last_product_errors = product_errors
    search._last_candidate_count = len(candidates)
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
    results = search(query)

    def rows():
        yield from results

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
    result = diagnose("Dior")
    print(json.dumps(result, ensure_ascii=False, indent=2))
