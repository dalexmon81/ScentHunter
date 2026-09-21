"""ScentHunter - Easycosmetic generic store adapter.

Store-specific technical knowledge only. Canonical identity and matching are
owned by the central catalog/matcher.
"""

from __future__ import annotations

import json
import re
import time
from html import unescape
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Easycosmetic"
BASE_URL = "https://www.easycosmetic.de"
SEARCH_URL = BASE_URL + "/suche?searchfor={}"
TIMEOUT = (3.0, 8.0)
BROWSER_TIMEOUT_MS = 15000
MAX_CANDIDATES = 50
MAX_RESULTS = 80

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
}


class StoreRequestError(RuntimeError):
    def __init__(self, status, message, url=None, http_status=None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.http_status = http_status


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


def _norm(value: Any) -> str:
    text = _clean(value).casefold()
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: Any) -> List[str]:
    return [x for x in _norm(value).split() if len(x) >= 2]


def _query_matches(text: Any, query: Any) -> bool:
    wanted = _tokens(query)
    if not wanted:
        return False
    hay = set(_tokens(text))
    if all(token in hay for token in wanted):
        return True
    q = re.sub(r"[^\w]+", "", _norm(query))
    h = re.sub(r"[^\w]+", "", _norm(text))
    return bool(q and q in h)


def _normalise_url(url: Any) -> str:
    absolute = urljoin(BASE_URL, _clean(url))
    parsed = urlparse(absolute)
    if parsed.netloc.lower() not in {"easycosmetic.de", "www.easycosmetic.de"}:
        return ""
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return f"{BASE_URL}{path}".rstrip("/")


def _is_candidate_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"easycosmetic.de", "www.easycosmetic.de"}:
        return False
    path = parsed.path.lower()
    if any(
        part in path
        for part in (
            "/suche", "/service", "/kontakt", "/impressum",
            "/datenschutz", "/agb", "/versand", "/zahlung",
            "/marken", "/alle-marken", "/ingredients/",
            "/inhaltsstoffe/",
        )
    ):
        return False
    if path.endswith((".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".pdf")):
        return False
    # Easycosmetic product pages in the current site use .aspx paths.
    return path.endswith(".aspx")


def _candidate_score(query: str, text: str, url: str) -> int:
    wanted = _tokens(query)
    hay = _norm(f"{text} {url}")
    score = sum(10 for token in wanted if token in hay)
    if _norm(query) and _norm(query) in hay:
        score += 25
    return score


def _request_html(url: str) -> str:
    request_error = None
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if 200 <= response.status_code < 300:
            return response.text

        status = response.status_code
        response.close()
        if status in (401, 403):
            raise StoreRequestError(
                "blocked", f"Easycosmetic returned HTTP {status}",
                url=url, http_status=status,
            )
        if status == 429:
            raise StoreRequestError(
                "blocked", "Easycosmetic rate-limited the request",
                url=url, http_status=status,
            )
        if status >= 500:
            raise StoreRequestError(
                "unavailable", f"Easycosmetic returned HTTP {status}",
                url=url, http_status=status,
            )
        raise StoreRequestError(
            "error", f"Easycosmetic returned HTTP {status}",
            url=url, http_status=status,
        )
    except StoreRequestError:
        raise
    except requests.Timeout as exc:
        request_error = exc
    except requests.ConnectionError as exc:
        raise StoreRequestError(
            "unavailable", "Easycosmetic connection failed", url=url
        ) from exc
    except requests.RequestException as exc:
        request_error = exc

    # Browser fallback is a technical anti-bot/rendering mechanism, not
    # product-specific logic.
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="de-DE",
                    extra_http_headers={
                        "Accept-Language": HEADERS["Accept-Language"]
                    },
                )
                page = context.new_page()
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=BROWSER_TIMEOUT_MS,
                )
                status = response.status if response else 200
                if status in (401, 403, 429):
                    raise StoreRequestError(
                        "blocked",
                        f"Easycosmetic browser request returned HTTP {status}",
                        url=url,
                        http_status=status,
                    )
                if status >= 500:
                    raise StoreRequestError(
                        "unavailable",
                        f"Easycosmetic browser request returned HTTP {status}",
                        url=url,
                        http_status=status,
                    )
                html = page.content()
                if not html or len(html) < 500:
                    raise StoreRequestError(
                        "error",
                        "Easycosmetic browser returned insufficient HTML",
                        url=url,
                    )
                return html
            finally:
                browser.close()
    except StoreRequestError:
        raise
    except Exception as browser_error:
        if isinstance(request_error, requests.Timeout):
            raise StoreRequestError(
                "timeout",
                "Easycosmetic HTTP and browser requests timed out/failed",
                url=url,
            ) from browser_error
        raise StoreRequestError(
            "unavailable",
            f"Easycosmetic HTTP/browser request failed: {type(browser_error).__name__}",
            url=url,
        ) from browser_error


def _jsonld_objects(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    output = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        output.extend(_walk_jsonld(data))
    return output


def _walk_jsonld(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_jsonld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_jsonld(child)


def _find_product_json(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    for node in _jsonld_objects(soup):
        typ = node.get("@type")
        types = typ if isinstance(typ, list) else [typ]
        if "Product" in types:
            return node
    return None


def _image_url(value: Any) -> str:
    if isinstance(value, str):
        return urljoin(BASE_URL, value.strip()) if value.strip() else ""
    if isinstance(value, dict):
        for key in ("contentUrl", "url", "src", "image"):
            result = _image_url(value.get(key))
            if result:
                return result
    if isinstance(value, list):
        for item in value:
            result = _image_url(item)
            if result:
                return result
    return ""


def _page_image(soup: BeautifulSoup, product_name: str = "") -> str:
    for selector in (
        'meta[property="og:image"]',
        'meta[property="og:image:url"]',
        'meta[name="twitter:image"]',
    ):
        node = soup.select_one(selector)
        if node:
            image = _image_url(node.get("content"))
            if image:
                return image

    wanted = _norm(product_name)
    if wanted:
        for img in soup.find_all("img"):
            descriptive = _norm(f"{img.get('alt', '')} {img.get('title', '')}")
            if descriptive and (
                wanted in descriptive
                or all(token in descriptive for token in wanted.split() if len(token) >= 3)
            ):
                for attr in ("src", "data-src", "data-original", "data-lazy-src"):
                    image = _image_url(img.get(attr))
                    if image:
                        return image

    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-original", "data-lazy-src"):
            image = _image_url(img.get(attr))
            if image and "cdn2.easycosmetic.de" in image.lower():
                return image

    return ""


def _price_number(value: Any) -> Optional[float]:
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


def _page_price(text: str) -> Optional[float]:
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
            value = _price_number(match.group(1))
            if value is not None:
                return value
    return None


def _brand(product: Dict[str, Any]) -> Optional[str]:
    value = product.get("brand")
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                item = item.get("name")
            if _clean(item):
                return _clean(item)
        return None
    return _clean(value) or None


def _offer(product: Dict[str, Any]):
    offers = product.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return None, "EUR", ""
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        price = _price_number(offer.get("price"))
        currency = _clean(offer.get("priceCurrency")) or "EUR"
        availability = _clean(offer.get("availability"))
        if price is not None or availability:
            return price, currency, availability
    return None, "EUR", ""


def _availability(text: str, json_availability: str = ""):
    normalized = _norm(json_availability)
    if any(x in normalized for x in ("outofstock", "ausverkauft", "unavailable", "nichtverfugbar")):
        return "out_of_stock"
    if any(x in normalized for x in ("instock", "available", "verfugbar", "lieferbar")):
        return "in_stock"

    normalized = _norm(text)
    if "nicht auf lager" in normalized or "ausverkauft" in normalized:
        return "out_of_stock"
    if "nicht verfugbar" in normalized:
        return "out_of_stock"
    if "auf lager" in normalized or "sofort lieferbar" in normalized:
        return "in_stock"
    if "lieferbar" in normalized:
        return "in_stock"
    return "unknown"


def _extract_product(url: str, query: str):
    try:
        html = _request_html(url)
    except StoreRequestError as exc:
        return [], {
            "status": exc.status,
            "url": exc.url,
            "http_status": exc.http_status,
            "error": str(exc),
        }

    soup = BeautifulSoup(html, "html.parser")
    product = _find_product_json(soup)

    h1 = soup.find("h1")
    name = _clean(h1.get_text(" ", strip=True)) if h1 else ""
    if not name and product:
        name = _clean(product.get("name"))

    if not name:
        return [], {"status": "partial", "url": url, "reason": "missing_name"}

    if not _query_matches(f"{name} {url}", query):
        return [], {"status": "partial", "url": url, "reason": "query_mismatch"}

    brand = _brand(product or {})
    price, currency, json_availability = _offer(product or {})
    page_text = _clean(soup.get_text(" ", strip=True))

    if price is None:
        price = _page_price(page_text)

    state = _availability(page_text, json_availability)

    image = _image_url((product or {}).get("image")) if product else ""
    if not image:
        image = _page_image(soup, name)

    size_ml = None
    size_match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", name, re.I)
    if size_match:
        size_ml = float(size_match.group(1).replace(",", "."))
        if size_match.group(2).lower() == "cl":
            size_ml *= 10
        if size_ml.is_integer():
            size_ml = int(size_ml)

    concentration = None
    lower_name = _norm(name)
    if "eau de toilette" in lower_name or re.search(r"\bedt\b", lower_name):
        concentration = "Eau de Toilette"
    elif "eau de parfum" in lower_name or re.search(r"\bedp\b", lower_name):
        concentration = "Eau de Parfum"
    elif "extrait de parfum" in lower_name or re.search(r"\bextrait\b", lower_name):
        concentration = "Extrait de Parfum"
    elif re.search(r"\bparfum\b", lower_name):
        concentration = "Parfum"

    gtin = None
    mpn = None
    sku = None
    product_id = None

    if product:
        gtin = _clean(
            product.get("gtin13")
            or product.get("gtin12")
            or product.get("gtin14")
            or product.get("gtin")
        ) or None
        mpn = _clean(product.get("mpn")) or None
        sku = _clean(product.get("sku")) or None
        product_id = _clean(
            product.get("productID")
            or product.get("productId")
            or sku
        ) or None

    row = {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand,
            "url": url,
            "image": image or None,
        },
        "identity": {
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
            "mpn": {"value": mpn, "source": "jsonld"} if mpn else None,
            "sku": {"value": sku, "source": "jsonld"} if sku else None,
            "store_product_id": (
                {"value": product_id, "source": "jsonld"}
                if product_id else None
            ),
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": (
                {"value": size_ml, "source": "product_title"}
                if size_ml is not None else None
            ),
            "concentration": (
                {"value": concentration, "source": "product_title"}
                if concentration else None
            ),
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
        },
        "offer": {
            "price": price,
            "currency": currency or "EUR",
            "availability": state,
        },
        "provenance": {
            "name": "easycosmetic_h1_or_jsonld",
            "brand": "jsonld" if brand else None,
            "price": "jsonld_or_page",
            "availability": "jsonld_or_page",
            "image": "jsonld_or_page" if image else None,
        },
        "raw_data": {"product_url": url},
        "name": name,
        "brand": brand,
        "price": f"{price:.2f} €" if price is not None else None,
        "price_num": price,
        "url": url,
        "available": (
            True if state == "in_stock"
            else False if state == "out_of_stock"
            else None
        ),
        "availability": state,
        "size_ml": size_ml,
        "size": (
            f"{int(size_ml)} ml"
            if size_ml is not None and float(size_ml).is_integer()
            else f"{size_ml} ml"
            if size_ml is not None else None
        ),
        "concentration": concentration,
        "image": image or None,
        "image_url": image or None,
        "gtin": gtin,
        "mpn": mpn,
        "sku": sku,
        "store_product_id": product_id,
    }
    return [row], {"status": "success", "url": url}


def _extract_candidates(html: str, query: str):
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: Dict[str, Dict[str, Any]] = {}

    def add(raw_url, text):
        url = _normalise_url(raw_url)
        if not _is_candidate_url(url):
            return
        score = _candidate_score(query, text, url)
        if score <= 0:
            return
        existing = candidates.get(url)
        if existing is None or score > existing["_score"]:
            candidates[url] = {
                "url": url,
                "name": _clean(text),
                "_score": score,
            }

    for link in soup.find_all("a", href=True):
        add(link.get("href"), link.get_text(" ", strip=True))

    for node in _jsonld_objects(soup):
        for item in _walk_jsonld(node):
            if _clean(item.get("@type")) != "Product":
                continue
            add(item.get("url"), item.get("name"))

    ordered = sorted(
        candidates.values(),
        key=lambda x: (-x["_score"], x["url"]),
    )
    for item in ordered:
        item.pop("_score", None)
    return ordered[:MAX_CANDIDATES]


def _discover(query):
    url = SEARCH_URL.format(quote_plus(query))
    try:
        html = _request_html(url)
    except StoreRequestError as exc:
        return [], {
            "status": exc.status,
            "verified": False,
            "failures": [{
                "status": exc.status,
                "url": exc.url,
                "http_status": exc.http_status,
                "message": str(exc),
            }],
        }

    candidates = _extract_candidates(html, query)
    if candidates:
        return candidates, {
            "status": "success",
            "verified": True,
            "discovery": "live_search",
            "candidate_count": len(candidates),
            "failures": [],
        }

    page_text = _norm(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    zero_markers = (
        "keine ergebnisse",
        "keine produkte",
        "0 produkte",
        "keine treffer",
        "keine suchergebnisse",
    )

    if any(marker in page_text for marker in zero_markers):
        return [], {
            "status": "success",
            "verified": True,
            "discovery": "verified_empty",
            "candidate_count": 0,
            "failures": [],
        }

    return [], {
        "status": "success",
        "verified": False,
        "discovery": "search_unverified",
        "candidate_count": 0,
        "failures": [],
    }


def search_stream(query: str):
    query = _clean(query)
    started = time.perf_counter()

    if not query:
        yield {
            "status": "success",
            "verified": True,
            "results": [],
            "error": None,
            "details": {"reason": "empty_query"},
        }
        return

    candidates, discovery = _discover(query)

    if not candidates:
        yield {
            "status": discovery.get("status", "error"),
            "verified": bool(discovery.get("verified")),
            "results": [],
            "error": (
                None
                if discovery.get("verified")
                else discovery.get("failures")
            ),
            "details": {
                "stage": "discovery",
                "candidate_count": 0,
                "discovery": discovery,
                "elapsed": round(time.perf_counter() - started, 3),
            },
        }
        return

    results = []
    errors = []

    with ThreadPoolExecutor(
        max_workers=min(8, len(candidates))
    ) as pool:
        futures = {
            pool.submit(_extract_product, item["url"], query): item
            for item in candidates
        }
        for future in as_completed(futures):
            try:
                rows, meta = future.result()
            except Exception as exc:
                rows, meta = [], {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            results.extend(rows)
            if meta.get("status") not in {"success", "partial"}:
                errors.append(meta)

    deduped = []
    seen = set()
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
        key=lambda row: (
            2 if row.get("availability") == "out_of_stock" else 0,
            row.get("price_num") if row.get("price_num") is not None else 999999,
            row.get("size_ml") if row.get("size_ml") is not None else 999999,
        )
    )
    deduped = deduped[:MAX_RESULTS]

    if deduped and errors:
        status, verified = "partial", True
    elif deduped:
        status, verified = "success", True
    elif errors:
        status, verified = "partial", False
    else:
        status, verified = "success", True

    yield {
        "status": status,
        "verified": verified,
        "results": deduped,
        "error": errors or None,
        "details": {
            "stage": "product_fetch",
            "candidate_count": len(candidates),
            "result_count": len(deduped),
            "error_count": len(errors),
            "elapsed": round(time.perf_counter() - started, 3),
            "discovery": discovery,
        },
    }


def search(query):
    return next(search_stream(query)).get("results", [])


def scrape(query):
    return search(query)


def search_easycosmetic(query):
    return search(query)


def diagnose(query):
    report = next(search_stream(query))
    return {
        "diagnostic": True,
        "store": STORE,
        "query": _clean(query),
        **report,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generic Easycosmetic scraper")
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(diagnose(" ".join(args.query)), ensure_ascii=False, indent=2))
