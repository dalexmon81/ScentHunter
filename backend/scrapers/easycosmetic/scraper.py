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
}

# These are generic site/navigation exclusions, not perfume/product rules.
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
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".pdf",
)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalise_url(url: str) -> str:
    absolute = urljoin(BASE_URL, url)
    parsed = urlparse(absolute)

    if parsed.netloc.lower() not in {
        "easycosmetic.de",
        "www.easycosmetic.de",
    }:
        return ""

    path = parsed.path or "/"
    return f"https://www.easycosmetic.de{path}".rstrip("/")


def _normalise_text(value: str) -> str:
    value = _clean(value).lower()
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _query_tokens(query: str) -> List[str]:
    return [
        token
        for token in _normalise_text(query).split()
        if len(token) >= 2
    ]


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

    if not path.endswith(".aspx"):
        return False

    if any(part in path for part in BLOCKED_PATH_PARTS):
        return False

    if path.endswith(BLOCKED_EXTENSIONS):
        return False

    return True


def _candidate_score(query: str, text: str, url: str) -> int:
    """
    Generic relevance score based only on the user's query.

    There are no hard-coded product names, brands, categories or perfume
    rules here. The same logic is used for every search term.
    """
    tokens = _query_tokens(query)

    if not tokens:
        return 0

    haystack = _normalise_text(f"{text} {url}")

    score = 0

    for token in tokens:
        if token in haystack:
            score += 10

    normalized_query = _normalise_text(query)

    if normalized_query and normalized_query in haystack:
        score += 25

    return score


def _request(url: str) -> requests.Response:
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


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
            items.extend(
                item for item in data if isinstance(item, dict)
            )

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

    # Remove currency and unrelated characters while preserving separators.
    raw = re.sub(r"[^\d,.\-]", "", raw)

    if not raw:
        return None

    # German decimal format: 1.299,99
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
            price = _price_to_float(match.group(1))
            if price is not None:
                return price

    return None


def _extract_brand(product_json: Dict[str, Any]) -> str:
    brand = product_json.get("brand")

    if isinstance(brand, dict):
        return _clean(brand.get("name"))

    if isinstance(brand, list):
        for item in brand:
            if isinstance(item, dict):
                name = _clean(item.get("name"))
            else:
                name = _clean(item)

            if name:
                return name

        return ""

    return _clean(brand)


def _extract_offer_data(
    product_json: Dict[str, Any],
) -> Tuple[Optional[float], str, str]:
    offers = product_json.get("offers")

    if isinstance(offers, dict):
        price = _price_to_float(offers.get("price"))
        currency = _clean(offers.get("priceCurrency")) or "EUR"
        availability = _clean(offers.get("availability"))
        return price, currency, availability

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

    # Generic availability language used by the retailer.
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


def search(query: str) -> List[Dict[str, Any]]:
    """
    Search Easycosmetic for any user query.

    The function is completely generic. It does not know any perfume,
    brand, product name, volume or category in advance.
    """
    query = _clean(query)

    if not query:
        return []

    search_url = SEARCH_URL.format(quote_plus(query))
    response = _request(search_url)
    soup = BeautifulSoup(response.text, "html.parser")

    candidates: Dict[str, Dict[str, Any]] = {}

    for link in soup.find_all("a", href=True):
        href = _normalise_url(link.get("href", ""))

        if not _is_candidate_url(href):
            continue

        anchor_text = _clean(link.get_text(" ", strip=True))
        score = _candidate_score(query, anchor_text, href)

        # Search pages can contain unrelated internal .aspx links.
        # Keep candidates that have at least one query-token match.
        if score <= 0:
            continue

        current = candidates.get(href)

        candidate = {
            "shop": STORE,
            "url": href,
            "name": anchor_text,
            "_score": score,
        }

        if current is None or score > current["_score"]:
            candidates[href] = candidate

    ordered = sorted(
        candidates.values(),
        key=lambda item: (-item["_score"], item["url"]),
    )

    for item in ordered:
        item.pop("_score", None)

    return ordered


def parse_product(url: str) -> Optional[Dict[str, Any]]:
    """
    Parse one Easycosmetic product page using structured product data
    first and HTML text as a fallback.
    """
    url = _normalise_url(url)

    if not _is_candidate_url(url):
        return None

    response = _request(url)
    soup = BeautifulSoup(response.text, "html.parser")

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

        price, currency, availability = _extract_offer_data(
            product_json
        )

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

    if not availability:
        _, availability = _availability_from_page(page_text)

    available, fallback_availability = _availability_from_page(page_text)

    if availability:
        normalized_availability = _normalise_text(availability)

        if any(
            marker in normalized_availability
            for marker in (
                "outofstock",
                "out of stock",
                "nicht auf lager",
                "ausverkauft",
                "unavailable",
                "nicht verfugbar",
            )
        ):
            available = False
        elif any(
            marker in normalized_availability
            for marker in (
                "instock",
                "in stock",
                "auf lager",
                "lieferbar",
                "available",
                "verfugbar",
            )
        ):
            available = True

    if not availability:
        availability = fallback_availability

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


def search_stream(
    query: str,
    emit=None,
):
    """
    Generic streaming interface.

    When ScentHunter supplies an emit callback, each parsed product is
    emitted immediately. Without a callback, the function yields rows.
    """
    candidates = search(query)

    def rows():
        for candidate in candidates:
            url = candidate.get("url")

            if not url:
                continue

            try:
                row = parse_product(url)
            except requests.RequestException:
                continue
            except Exception:
                continue

            if not row:
                continue

            yield row

    if callable(emit):
        for row in rows():
            emit(row)
        return None

    return rows()


def diagnose(query: str) -> Dict[str, Any]:
    """
    Standalone diagnostic function.

    Useful before integrating the scraper into the ScentHunter store
    list. It reports search candidates, parsed products and errors.
    """
    query = _clean(query)

    report: Dict[str, Any] = {
        "diagnostic": True,
        "store": STORE,
        "query": query,
        "search_url": (
            SEARCH_URL.format(quote_plus(query))
            if query
            else None
        ),
        "candidate_count": 0,
        "candidates": [],
        "products": [],
        "errors": [],
    }

    try:
        candidates = search(query)
    except Exception as exc:
        report["errors"].append(
            {
                "stage": "search",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
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
            report["errors"].append(
                {
                    "stage": "parse_product",
                    "url": url,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    return report


if __name__ == "__main__":
    # Manual smoke test only.
    # This query is NOT part of the scraper logic and can be changed
    # freely when testing different products.
    test_query = "Liquid Brun"

    print("Easycosmetic scraper smoke test")
    print("=" * 60)
    print(f"Query: {test_query}")
    print()

    try:
        result = diagnose(test_query)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"FATAL ERROR: {type(exc).__name__}: {exc}")
