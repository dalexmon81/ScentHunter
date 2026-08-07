"""
Notino.fr scraper for ScentHunter.

Primary: Playwright + Chromium.
Fallback: requests + BeautifulSoup.

No Google/Bing.
No hardcoded products or prices.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
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

DEFAULT_TIMEOUT_MS = int(os.getenv("NOTINO_TIMEOUT_MS", "30000"))
BROWSER_ENABLED = os.getenv("NOTINO_BROWSER", "1").lower() not in {
    "0", "false", "no"
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
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalise_url(href: str) -> str | None:
    if not href:
        return None

    href = href.strip()

    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(BASE_URL, href)

    parsed = urlparse(href)

    if parsed.scheme not in {"http", "https"}:
        return None

    if parsed.netloc.lower() not in {"notino.fr", "www.notino.fr"}:
        return None

    path = parsed.path.rstrip("/")

    if not path or path == "/":
        return None

    if path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".svg")):
        return None

    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _looks_like_product_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.strip("/").lower()

    if not path:
        return False

    first_segment = path.split("/", 1)[0]

    if first_segment in PRODUCT_PATH_EXCLUSIONS:
        return False

    if "search.asp" in path:
        return False

    return len(path.split("/")) >= 2


def _extract_prices(text: str) -> list[str]:
    prices: list[str] = []

    for match in PRICE_RE.finditer(_clean(text)):
        raw = match.group(1).replace(" ", "")

        if raw.count(".") > 1:
            raw = raw.replace(".", "")
        elif "." in raw and "," not in raw:
            raw = raw.replace(".", ",")

        value = f"{raw} €"

        if value not in prices:
            prices.append(value)

    return prices


def _is_stock_text(text: str) -> bool:
    low = _clean(text).lower()

    stock_terms = (
        "en stock",
        "disponible",
        "en rupture",
        "rupture de stock",
        "indisponible",
        "épuisé",
        "epuise",
    )

    return any(term in low for term in stock_terms)


def _candidate_container(anchor) -> Any:
    node = anchor

    for _ in range(6):
        if not node:
            break

        text = _clean(node.get_text(" ", strip=True))

        if len(text) >= 20 and (_extract_prices(text) or _is_stock_text(text)):
            return node

        node = getattr(node, "parent", None)

    return anchor.parent


def _name_from_container(container, fallback: str) -> str:
    if container is None:
        return fallback

    for selector in ("h1", "h2", "h3", "h4"):
        element = container.select_one(selector)

        if element:
            text = _clean(element.get_text(" ", strip=True))

            if 2 <= len(text) <= 300:
                return text

    anchor = container.find("a", href=True)

    if anchor:
        text = _clean(anchor.get_text(" ", strip=True))

        if 2 <= len(text) <= 300:
            return text

    return fallback


def _walk_json_ld(value: Any):
    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from _walk_json_ld(child)

    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_ld(child)


def _parse_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []

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


def _results_from_json_ld(soup: BeautifulSoup) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[str] = set()

    for product in _parse_json_ld(soup):
        url = _normalise_url(str(product.get("url", "")))

        if not url or not _looks_like_product_url(url):
            continue

        name = _clean(product.get("name"))
        offers = product.get("offers", {})

        if isinstance(offers, list):
            offer_list = [x for x in offers if isinstance(x, dict)]
        elif isinstance(offers, dict):
            offer_list = [offers]
        else:
            offer_list = []

        for offer in offer_list:
            price_value = offer.get("price")
            currency = _clean(offer.get("priceCurrency"))
            availability = _clean(offer.get("availability"))

            if price_value is None:
                continue

            if currency and currency.upper() not in {"EUR", "€"}:
                continue

            raw_price = _clean(price_value).replace(".", ",")

            if not raw_price:
                continue

            key = f"{url}|{raw_price}"

            if key in seen:
                continue

            seen.add(key)

            output.append({
                "store": STORE,
                "name": name or url.rstrip("/").split("/")[-1],
                "price": f"{raw_price} €",
                "url": url,
                "availability": availability,
            })

    return output


def _results_from_html(html: str, query: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in _results_from_json_ld(soup):
        results.append(item)
        seen.add(item["url"])

    for anchor in soup.find_all("a", href=True):
        url = _normalise_url(anchor.get("href", ""))

        if not url or url in seen or not _looks_like_product_url(url):
            continue

        container = _candidate_container(anchor)

        if container is None:
            continue

        text = _clean(container.get_text(" ", strip=True))

        if len(text) > 2500:
            continue

        prices = _extract_prices(text)

        if not prices:
            continue

        name = _name_from_container(container, _clean(query))
        low = text.lower()
        availability = ""

        if "rupture de stock" in low or "en rupture" in low:
            availability = "Rupture de stock"
        elif "en stock" in low:
            availability = "En stock"
        elif "disponible" in low:
            availability = "Disponible"

        results.append({
            "store": STORE,
            "name": name,
            "price": prices[0],
            "url": url,
            "availability": availability,
        })

        seen.add(url)

        if len(results) >= 50:
            break

    return results


def _deduplicate(items: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item in items:
        url = _clean(item.get("url"))
        price = _clean(item.get("price"))

        if not url or not price:
            continue

        key = (url, price)

        if key in seen:
            continue

        seen.add(key)
        output.append(item)

    return output


def _search_with_requests(query: str) -> list[dict[str, str]]:
    url = SEARCH_URL.format(query=quote_plus(query))

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        LOGGER.warning("Notino requests error: %s", exc)
        return []

    if response.status_code == 403:
        LOGGER.warning("Notino returned HTTP 403 to requests")
        return []

    if response.status_code >= 400:
        LOGGER.warning("Notino returned HTTP %s", response.status_code)
        return []

    return _deduplicate(_results_from_html(response.text, query))


def _search_with_playwright(query: str) -> list[dict[str, str]]:
    if sync_playwright is None:
        LOGGER.warning("Playwright is not installed")
        return []

    url = SEARCH_URL.format(query=quote_plus(query))

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
                viewport={"width": 1365, "height": 900},
            )

            page = context.new_page()

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )

            if response is not None and response.status == 403:
                browser.close()
                LOGGER.warning("Notino returned HTTP 403 to Playwright")
                return []

            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=min(DEFAULT_TIMEOUT_MS, 15000),
                )
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(1500)
            html = page.content()
            browser.close()

    except PlaywrightTimeoutError as exc:
        LOGGER.warning("Notino Playwright timeout: %s", exc)
        return []

    except Exception as exc:
        LOGGER.warning("Notino Playwright error: %s", exc)
        return []

    return _deduplicate(_results_from_html(html, query))


def search(query: str) -> list[dict[str, str]]:
    query = _clean(query)

    if not query:
        return []

    if BROWSER_ENABLED:
        browser_results = _search_with_playwright(query)

        if browser_results:
            return browser_results

    return _search_with_requests(query)
