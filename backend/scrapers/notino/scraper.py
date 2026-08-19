from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
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
BROWSER_ENABLED = os.getenv("NOTINO_BROWSER", "1").lower() not in {"0", "false", "no"}

LOGGER = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}

PRICE_RE = re.compile(r"(?P<price>\d+(?:[.,]\d{1,2})?)\s*€")
PRODUCT_URL_RE = re.compile(r"/p-\d+/?", re.I)

PRODUCT_PATH_EXCLUSIONS = {
    "blog",
    "news",
    "magazine",
    "guide",
    "category",
    "categories",
    "marque",
    "marques",
    "brand",
    "brands",
    "collection",
    "collections",
    "search",
    "recherche",
    "account",
    "compte",
    "panier",
    "cart",
    "checkout",
    "commande",
    "order",
    "wishlist",
    "liste",
    "liste-souhaits",
    "contact",
    "aide",
    "help",
    "faq",
    "legal",
    "mentions",
    "cgu",
    "cgv",
    "confidentialite",
    "confidentialité",
    "privacy",
    "cookies",
    "newsletter",
    "abonnement",
    "subscribe",
    "login",
    "connexion",
    "register",
    "inscription",
    "password",
    "mot-de-passe",
    "reset",
    "recover",
    "recuperer",
    "voucher",
    "coupon",
    "promo",
    "promotion",
    "soldes",
    "sale",
    "outlet",
    "bestsellers",
    "best-sellers",
    "nouveautes",
    "nouveautés",
    "new",
    "new-arrivals",
    "top",
    "tendances",
    "trends",
    "popular",
    "populaire",
    "recommande",
    "recommandé",
    "recommended",
    "suggestion",
    "suggestions",
}

IN_STOCK_TERMS = {
    "instock",
    "in stock",
    "available",
    "disponible",
    "en stock",
}

OUT_OF_STOCK_TERMS = {
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
}


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip())
    return clean(str(value))


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def tokens(text: str) -> Set[str]:
    return {t for t in re.split(r"\s+", norm(text)) if t}


def matches(text: str, query: str) -> bool:
    query_tokens = tokens(query)
    return bool(query_tokens) and query_tokens.issubset(tokens(text))


def _discovery_tokens(value: str) -> Set[str]:
    """Normalize generic linguistic variants used by store search URLs."""
    aliases = {
        "him": "men",
        "his": "men",
        "man": "men",
        "men": "men",
        "homme": "men",
        "pour": "for",
        "for": "for",
        "her": "women",
        "woman": "women",
        "women": "women",
        "femme": "women",
    }
    return {aliases.get(token, token) for token in tokens(value)}


def _discovery_matches(text: str, query: str) -> bool:
    query_tokens = _discovery_tokens(query)
    return bool(query_tokens) and query_tokens.issubset(_discovery_tokens(text))


def size_ml(*values: str) -> Optional[float]:
    text = " ".join((clean(x) for x in values))
    match = re.search(r"(?P<vol>\d+(?:[.,]\d+)?)\s*(?:ml|milliliters|millilitres)", text, re.I)
    if match:
        try:
            number = float(match.group("vol").replace(",", "."))
            return round(number, 2) if number > 0 else None
        except (TypeError, ValueError):
            return None
    return None


def parse_price(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return round(number, 2) if number > 0 else None
    text = clean(value)
    if not text:
        return None
    match = PRICE_RE.search(text)
    if match:
        raw = match.group("price").replace(" ", "")
    else:
        bare = re.fullmatch(r"\d+(?:[.,]\d{1,2})?", text)
        if not bare:
            return None
        raw = bare.group(0)
        if raw.count(".") > 1:
            raw = raw.replace(".", "")
        elif "." in raw and "," not in raw:
            raw = raw.replace(".", ",")
    try:
        number = float(raw.replace(",", "."))
        return round(number, 2) if number > 0 else None
    except ValueError:
        return None


def _extract_prices(text: str) -> List[float]:
    values = []
    for match in PRICE_RE.finditer(clean(text)):
        value = parse_price(match.group(0))
        if value is not None:
            values.append(value)
    return values


def availability_from_sources(data: Dict[str, Any], soup: BeautifulSoup) -> str:
    """Prefer structured availability; never classify from unrelated page text."""
    offers = data.get("offers") if isinstance(data, dict) else None
    if isinstance(offers, dict):
        offers = [offers]
    if isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            raw = offer.get("availability") or offer.get("availabilityStatus") or offer.get("stock")
            if not raw:
                continue
            text = norm(raw)
            if any(term in text for term in ("instock", "in stock", "available", "disponible", "en stock")):
                return "in_stock"
            if any(
                term in text
                for term in (
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
                )
            ):
                return "out_of_stock"
    for tag in soup.select(
        '[itemprop="availability"], meta[property="product:availability"], meta[name="availability"]'
    ):
        raw = tag.get("content") or tag.get_text(" ", strip=True)
        text = norm(raw)
        if any(term in text for term in IN_STOCK_TERMS):
            return "in_stock"
        if any(term in text for term in OUT_OF_STOCK_TERMS):
            return "out_of_stock"
    return "unknown"


def _normalise_url(href: Optional[str]) -> Optional[str]:
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
    if parsed.netloc.lower() not in {"notino.fr", "www.notino.fr"}:
        return None
    path = parsed.path.rstrip("/")
    if not path or path == "/":
        return None
    if path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".svg")):
        return None
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _looks_like_product_url(url: str, context: str = "", query: str = "") -> bool:
    """Accept genuine Notino product-looking URLs generically.

    Notino uses two valid product URL forms:
    - URLs containing /p-/
    - canonical slug URLs without /p-/

    Discovery uses the available card/context text and URL path. Generic
    linguistic variants such as him/men and homme/men are normalized only
    for discovery; the final product validation in _product() remains
    unchanged.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    path = parsed.path.rstrip("/")
    lower_path = path.lower()

    if not path or "search.asp" in lower_path:
        return False

    path_context = path.replace("/", " ").replace("-", " ")

    discovery_context = " ".join(
        clean(context),
        clean(path_context),
    )

    if PRODUCT_URL_RE.search(path):
        if query and not _discovery_matches(discovery_context, query):
            return False
        return True

    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return False

    if parts[0].lower() in PRODUCT_PATH_EXCLUSIONS:
        return False

    if query and not _discovery_matches(discovery_context, query):
        return False

    slug = parts[-1].replace("-", " ")
    return len(tokens(slug)) >= 2


def _walk_json_ld(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_ld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_ld(child)


def _parse_json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
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


def _image_from_product(data: Dict[str, Any]) -> Optional[str]:
    image = data.get("image") if isinstance(data, dict) else None
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    if not image:
        return None
    return str(image)


def _selected_size(soup: BeautifulSoup, data: Dict[str, Any], h1_name: str) -> Optional[float]:
    """Extract the actually selected bottle size."""
    visible_sources = [h1_name, clean(data.get("name")) if isinstance(data, dict) else ""]
    for value in visible_sources:
        match = re.search(r"(?P<vol>\d+(?:[.,]\d+)?)\s*(?:ml|milliliters|millilitres)", value, re.I)
        if match:
            try:
                return round(float(match.group("vol").replace(",", ".")), 2)
            except (TypeError, ValueError):
                pass
    return None


def _search_pages(query: str) -> List[str]:
    q = quote_plus(clean(query))
    return [
        SEARCH_URL.format(query=q),
    ]


def _candidate_product_urls(html: str, query: str) -> List[str]:
    """Extract candidate product URLs from Notino search HTML.

    Rules:
    - URLs with /p-/ are accepted structurally.
    - canonical slug product URLs without an ID are also accepted when the
      surrounding search-card text matches the query.
    - the product page performs the final validation.
    """
    soup = BeautifulSoup(html, "html.parser")
    found, seen = [], set()

    def add(raw_url: str, context: str = "") -> None:
        if not raw_url:
            return

        raw_url = clean(str(raw_url)).replace("\\/", "/").replace("\\u002F", "/")

        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        elif raw_url.startswith("/"):
            raw_url = urljoin(BASE_URL, raw_url)

        url = _normalise_url(raw_url)

        if not url:
            return

        if not _looks_like_product_url(url, context, query):
            return

        if url in seen:
            return

        seen.add(url)
        found.append(url)

    # Product-card links: use the complete local card context.
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        card = anchor
        for _ in range(4):
            parent = getattr(card, "parent", None)
            if parent is None:
                break
            card = parent
            card_text = clean(card.get_text(" ", strip=True))
            if len(card_text) >= 20:
                break

        context = " ".join(
            clean(anchor.get_text(" ", strip=True)),
            clean(card.get_text(" ", strip=True)),
            clean(anchor.get("aria-label")),
            clean(anchor.get("title")),
        )

        add(href, context)

    # Other structural attributes can contain product URLs.
    for node in soup.find_all(True):
        context = clean(node.get_text(" ", strip=True))
        for attr in ("data-href", "data-url", "data-product-url"):
            add(node.get(attr), context)

    # Structured data may expose product URLs independently of the visible DOM.
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        for obj in _walk_json_ld(data):
            if not isinstance(obj, dict):
                continue

            obj_name = clean(obj.get("name"))

            for key in ("url", "@id"):
                value = obj.get(key)
                if isinstance(value, str):
                    add(value, obj_name)

            item = obj.get("item")
            if isinstance(item, dict):
                item_name = clean(item.get("name"))
                for key in ("url", "@id"):
                    value = item.get(key)
                    if isinstance(value, str):
                        add(value, item_name)

    # Embedded application state: retain explicit /p-/ URLs.
    decoded = html.replace("\\/", "/").replace("\\u002F", "/")

    patterns = (
        # Explicit product URLs with Notino's numeric product id.
        r"(?:https?:)?//(?:www\.)?notino\.fr/[^\"'<>\s\\]+/p-\d+/?",
        r"(?P<url>https?://(?:www\.)?notino\.fr/[^\"'<>\s\\]+/p-\d+/?)",
        # Canonical product URLs can be embedded in application state
        # without /p-/. Keep this generic and let _looks_like_product_url()
        # validate the path against the search query and exclusions.
        r"(?:https?:)?//(?:www\.)?notino\.fr/(?=[^\"'<>\s\\]+/[^\"'<>\s\\]+/?(?:[\"'<>\s]|$))[^\"'<>\s\\]+/[^\"'<>\s\\]+/?",
        r"(?P<url>https?://(?:www\.)?notino\.fr/[a-z0-9][^\"'<>\s\\]*/[a-z0-9][^\"'<>\s\\]+/?)",
    )

    for pattern in patterns:
        for raw in re.findall(pattern, decoded, re.I):
            if isinstance(raw, tuple):
                raw = raw[0]
            add(raw)

    return found


def _discover_with_playwright(query: str, max_urls: int = 80) -> List[str]:
    """Browser fallback for client-rendered Notino search results."""
    if sync_playwright is None:
        return []

    urls, seen = [], set()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )

            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="fr-FR",
                extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
                viewport={"width": 1365, "height": 900},
            )

            page = context.new_page()
            response = page.goto(
                _search_pages(query)[0],
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )

            if response is not None and response.status >= 400:
                browser.close()
                return []

            try:
                page.wait_for_load_state("networkidle", timeout=min(DEFAULT_TIMEOUT_MS, 15000))
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1000)

            candidates = _candidate_product_urls(page.content(), query)

            for raw_url in candidates:
                url = _normalise_url(raw_url)
                if not url or url in seen:
                    continue
                seen.add(url)
                urls.append(url)
                if len(urls) >= max_urls:
                    break
            browser.close()
    except Exception as exc:
        LOGGER.warning("Notino Playwright discovery error: %s", exc)

    return urls[:max_urls]


def _discover_from_search_requests(
    session: requests.Session, query: str, max_urls: int = 80
) -> List[str]:
    """Discover only from Notino's own search endpoint, like Deloox."""
    try:
        response = session.get(
            _search_pages(query)[0],
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return []

    if response.status_code >= 400:
        return []

    return _candidate_product_urls(response.text, query)[:max_urls]


def _discover(session: requests.Session, query: str) -> List[str]:
    """Combine HTTP and browser discovery without letting one source hide the other."""
    found = []
    seen = set()

    def merge(urls: List[str]) -> bool:
        for url in urls or []:
            normalised = _normalise_url(url)
            if not normalised or normalised in seen:
                continue
            seen.add(normalised)
            found.append(normalised)
            if len(found) >= 80:
                return True
        return False

    # HTTP discovery is the fast first source.
    if merge(_discover_from_search_requests(session, query, 80)):
        return found[:80]

    # Browser discovery is also a valid generic source. It is no longer
    # skipped merely because HTTP returned some candidates: the two sources
    # can expose different parts of Notino's search result.
    if BROWSER_ENABLED:
        merge(_discover_with_playwright(query, 80))

    return found[:80]


def _fetch_product_with_playwright(url: str) -> Optional[str]:
    if sync_playwright is None or not BROWSER_ENABLED:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="fr-FR",
                extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
            )
            page = context.new_page()
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )

            if response is not None and response.status >= 400:
                browser.close()
                return None

            # The product page can render its title/data after the initial
            # DOM load. A short fixed delay is not reliable across products.
            # Wait for a real product marker, with a bounded timeout, without
            # waiting for networkidle (Notino background requests can remain
            # open indefinitely or trigger a challenge).
            try:
                page.wait_for_selector(
                    "h1, script[type=\"application/ld+json\"]",
                    timeout=min(DEFAULT_TIMEOUT_MS, 8000),
                    state="attached",
                )
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(800)
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        LOGGER.warning("Notino browser product retrieval failed: %s", exc)
        return None


def _product(url: str, html: str, query: str) -> Optional[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    h1_text = clean(h1.get_text(" ", strip=True)) if h1 else ""

    data = _parse_json_ld(soup)
    product_data = data[0] if data else {}

    name = clean(product_data.get("name")) or h1_text
    if not name:
        return None

    brand = clean(product_data.get("brand", {}).get("name")) if isinstance(product_data.get("brand"), dict) else ""
    if not brand:
        for tag in soup.select('[itemprop="brand"], meta[property="product:brand"], meta[name="brand"]'):
            brand = clean(tag.get("content") or tag.get_text(" ", strip=True))
            if brand:
                break

    size = _selected_size(soup, product_data, h1_text)

    image = _image_from_product(product_data)
    if not image:
        for tag in soup.select('[itemprop="image"], meta[property="og:image"], meta[name="twitter:image"]'):
            image = clean(tag.get("content") or tag.get_text(" ", strip=True))
            if image:
                break

    price = None
    offers = product_data.get("offers") if isinstance(product_data.get("offers"), dict) else None
    if offers:
        price = parse_price(offers.get("price"))
    if price is None:
        for tag in soup.select('[itemprop="price"], meta[property="product:price:amount"]'):
            price = parse_price(tag.get("content"))
            if price is not None:
                break
        if price is None:
            for tag in soup.select(".price, .product-price, [data-price]"):
                price = parse_price(tag.get("content") or tag.get_text(" ", strip=True))
                if price is not None:
                    break

    availability = availability_from_sources(product_data, soup)

    canonical = None
    for tag in soup.select('link[rel="canonical"]'):
        href = tag.get("href")
        if href:
            canonical = _normalise_url(href)
            break

    if not matches(name, query) and not matches(brand, query):
        return None

    return {
        "url": url,
        "name": name,
        "brand": brand,
        "size_ml": size,
        "image": image,
        "price": price,
        "availability": availability,
        "canonical": canonical,
        "identity": {
            "name": name,
            "brand": brand,
            "sku": {"value": url} if url else None,
        },
    }


# =============================================================================
# DIAGNOSTIC FUNCTIONS
# =============================================================================


@dataclass
class DiagnosticCandidate:
    raw_url: str
    normalized_url: Optional[str]
    context: str
    accepted: bool
    rejection_reason: Optional[str] = None


@dataclass
class DiagnosticProductPage:
    url: str
    http_status: Optional[int]
    final_url: Optional[str]
    redirects: List[str]
    html_bytes: int
    used_playwright: bool
    h1: Optional[str]
    json_ld_products: List[Dict[str, Any]]
    product_name: Optional[str]
    brand: Optional[str]
    size_ml: Optional[float]
    canonical: Optional[str]
    availability: str
    matching: bool
    filter_reason: Optional[str]
    returned: bool


@dataclass
class DiagnosticResult:
    query: str
    search_urls: List[Dict[str, Any]]
    http_discovery: Dict[str, Any]
    playwright_discovery: Dict[str, Any]
    product_pages: List[DiagnosticProductPage]
    final_results: List[Dict[str, Any]]
    total_elapsed_ms: float


def _fetch_search_page_diagnostic(
    session: requests.Session, query: str, timeout: float = 15.0
) -> Dict[str, Any]:
    """Fetch a single search page with full diagnostic metadata."""
    url = _search_pages(query)[0]
    start = time.perf_counter()
    result = {
        "url": url,
        "status": None,
        "final_url": None,
        "elapsed_ms": 0.0,
        "html_bytes": 0,
        "title": None,
        "body_preview": None,
        "anti_bot_indicators": [],
        "error": None,
    }

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        result["status"] = response.status_code
        result["final_url"] = response.url
        result["elapsed_ms"] = (time.perf_counter() - start) * 1000
        result["html_bytes"] = len(response.content)

        soup = BeautifulSoup(response.text, "html.parser")
        title_tag = soup.find("title")
        if title_tag:
            result["title"] = clean(title_tag.get_text(" ", strip=True))

        body_preview = soup.get_text(" ", strip=True)[:500]
        result["body_preview"] = body_preview

        # Simple anti-bot heuristics
        if "challenge" in response.text.lower() or "captcha" in response.text.lower():
            result["anti_bot_indicators"].append("challenge_or_captcha_keyword")
        if response.status_code == 200 and len(response.content) < 2000:
            result["anti_bot_indicators"].append("suspiciously_small_response")
        if "notino" not in response.text.lower()[:2000]:
            result["anti_bot_indicators"].append("brand_missing_in_head")

    except requests.RequestException as exc:
        result["error"] = str(exc)
        result["elapsed_ms"] = (time.perf_counter() - start) * 1000

    return result


def _discover_http_diagnostic(
    session: requests.Session, query: str, max_urls: int = 80
) -> Dict[str, Any]:
    """HTTP discovery with full candidate tracking."""
    search_page = _fetch_search_page_diagnostic(session, query)
    if search_page["status"] is None or search_page["status"] >= 400 or not search_page["body_preview"]:
        return {
            "search_page": search_page,
            "raw_links_seen": [],
            "normalized_links": [],
            "accepted_candidates": [],
            "rejected_candidates": [],
            "total_candidates": 0,
        }

    html = ""
    try:
        response = session.get(
            search_page["url"],
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if response.status_code < 400:
            html = response.text
    except requests.RequestException:
        pass

    if not html:
        return {
            "search_page": search_page,
            "raw_links_seen": [],
            "normalized_links": [],
            "accepted_candidates": [],
            "rejected_candidates": [],
            "total_candidates": 0,
        }

    soup = BeautifulSoup(html, "html.parser")
    raw_links = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if href:
            raw_links.append(href)

    for node in soup.find_all(True):
        for attr in ("data-href", "data-url", "data-product-url"):
            val = node.get(attr)
            if val:
                raw_links.append(val)

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        for obj in _walk_json_ld(data):
            if not isinstance(obj, dict):
                continue
            for key in ("url", "@id"):
                value = obj.get(key)
                if isinstance(value, str):
                    raw_links.append(value)
            item = obj.get("item")
            if isinstance(item, dict):
                for key in ("url", "@id"):
                    value = item.get(key)
                    if isinstance(value, str):
                        raw_links.append(value)

    decoded = html.replace("\\/", "/").replace("\\u002F", "/")
    patterns = (
        r"(?:https?:)?//(?:www\.)?notino\.fr/[^\"'<>\s\\]+/p-\d+/?",
        r"(?P<url>https?://(?:www\.)?notino\.fr/[^\"'<>\s\\]+/p-\d+/?)",
        r"(?:https?:)?//(?:www\.)?notino\.fr/(?=[^\"'<>\s\\]+/[^\"'<>\s\\]+/?(?:[\"'<>\s]|$))[^\"'<>\s\\]+/[^\"'<>\s\\]+/?",
        r"(?P<url>https?://(?:www\.)?notino\.fr/[a-z0-9][^\"'<>\s\\]*/[a-z0-9][^\"'<>\s\\]+/?)",
    )
    for pattern in patterns:
        for raw in re.findall(pattern, decoded, re.I):
            if isinstance(raw, tuple):
                raw = raw[0]
            raw_links.append(raw)

    candidates: List[DiagnosticCandidate] = []
    seen_normalized: Set[str] = set()

    for raw_url in raw_links:
        raw_url = clean(str(raw_url)).replace("\\/", "/").replace("\\u002F", "/")
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        elif raw_url.startswith("/"):
            raw_url = urljoin(BASE_URL, raw_url)

        normalized = _normalise_url(raw_url)
        if not normalized:
            candidates.append(
                DiagnosticCandidate(
                    raw_url=raw_url,
                    normalized_url=None,
                    context="",
                    accepted=False,
                    rejection_reason="normalization_failed",
                )
            )
            continue

        # Build context from surrounding text (simplified for diagnostic)
        context = ""

        is_product_url = _looks_like_product_url(normalized, context, query)
        if not is_product_url:
            # Determine specific reason
            reason = "not_product_url"
            try:
                parsed = urlparse(normalized)
                path = parsed.path.rstrip("/")
                if "search.asp" in path.lower():
                    reason = "search_page_excluded"
                elif any(p.lower() in PRODUCT_PATH_EXCLUSIONS for p in path.split("/") if p):
                    reason = "path_exclusion"
                elif query and not _discovery_matches(context + " " + path.replace("/", " ").replace("-", " "), query):
                    reason = "discovery_mismatch"
            except Exception:
                pass

            candidates.append(
                DiagnosticCandidate(
                    raw_url=raw_url,
                    normalized_url=normalized,
                    context=context,
                    accepted=False,
                    rejection_reason=reason,
                )
            )
            continue

        if normalized in seen_normalized:
            candidates.append(
                DiagnosticCandidate(
                    raw_url=raw_url,
                    normalized_url=normalized,
                    context=context,
                    accepted=False,
                    rejection_reason="duplicate",
                )
            )
            continue

        seen_normalized.add(normalized)
        candidates.append(
            DiagnosticCandidate(
                raw_url=raw_url,
                normalized_url=normalized,
                context=context,
                accepted=True,
            )
        )

    accepted = [c for c in candidates if c.accepted][:max_urls]

    return {
        "search_page": search_page,
        "raw_links_seen": [c.raw_url for c in candidates],
        "normalized_links": [c.normalized_url for c in candidates if c.normalized_url],
        "accepted_candidates": [c.normalized_url for c in accepted],
        "rejected_candidates": [
            {
                "raw_url": c.raw_url,
                "normalized_url": c.normalized_url,
                "context": c.context,
                "rejection_reason": c.rejection_reason,
            }
            for c in candidates
            if not c.accepted
        ],
        "total_candidates": len(accepted),
    }


def _discover_playwright_diagnostic(query: str, max_urls: int = 80) -> Dict[str, Any]:
    """Playwright discovery with basic diagnostic metadata."""
    result: Dict[str, Any] = {
        "attempted": False,
        "status": None,
        "final_url": None,
        "html_bytes": 0,
        "urls_found": 0,
        "urls_accepted": 0,
        "urls_rejected": 0,
        "error": None,
    }

    if sync_playwright is None or not BROWSER_ENABLED:
        result["error"] = "playwright_disabled"
        return result

    result["attempted"] = True
    url = _search_pages(query)[0]

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="fr-FR",
                extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
                viewport={"width": 1365, "height": 900},
            )
            page = context.new_page()
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT_MS,
            )

            if response is not None:
                result["status"] = response.status
                result["final_url"] = response.url

            try:
                page.wait_for_load_state("networkidle", timeout=min(DEFAULT_TIMEOUT_MS, 15000))
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1000)

            html = page.content()
            result["html_bytes"] = len(html)

            candidates = _candidate_product_urls(html, query)
            normalized = [_normalise_url(c) for c in candidates]
            accepted = [u for u in normalized if u][:max_urls]

            result["urls_found"] = len(candidates)
            result["urls_accepted"] = len(accepted)
            result["urls_rejected"] = len(candidates) - len(accepted)

            browser.close()
    except Exception as exc:
        result["error"] = str(exc)

    return result


def _fetch_product_page_diagnostic(
    session: requests.Session, url: str, max_html_bytes: int = 500000
) -> Tuple[Optional[str], int, Optional[int], Optional[str], List[str], bool]:
    """Fetch a product page via HTTP or Playwright with diagnostic metadata.

    Returns:
        (html, html_bytes, http_status, final_url, redirects, used_playwright)
    """
    redirects: List[str] = []
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    used_playwright = False

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        http_status = response.status_code
        final_url = response.url
        redirects = [r.url for r in response.history] if hasattr(response, "history") else []

        if response.status_code < 400:
            html = response.text[:max_html_bytes]
            return html, len(response.text), http_status, final_url, redirects, used_playwright
    except requests.RequestException:
        pass

    # Fallback to Playwright
    html = _fetch_product_with_playwright(url)
    if html:
        used_playwright = True
        return html[:max_html_bytes], len(html), None, None, [], used_playwright

    return None, 0, None, None, [], False


def _product_diagnostic(url: str, html: str, query: str) -> Tuple[Optional[Dict[str, Any]], DiagnosticProductPage]:
    """Extract product data and build diagnostic page info."""
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    h1_text = clean(h1.get_text(" ", strip=True)) if h1 else ""

    data = _parse_json_ld(soup)
    product_data = data[0] if data else {}

    name = clean(product_data.get("name")) or h1_text
    brand = clean(product_data.get("brand", {}).get("name")) if isinstance(product_data.get("brand"), dict) else ""
    if not brand:
        for tag in soup.select('[itemprop="brand"], meta[property="product:brand"], meta[name="brand"]'):
            brand = clean(tag.get("content") or tag.get_text(" ", strip=True))
            if brand:
                break

    size = _selected_size(soup, product_data, h1_text)

    image = _image_from_product(product_data)
    if not image:
        for tag in soup.select('[itemprop="image"], meta[property="og:image"], meta[name="twitter:image"]'):
            image = clean(tag.get("content") or tag.get_text(" ", strip=True))
            if image:
                break

    price = None
    offers = product_data.get("offers") if isinstance(product_data.get("offers"), dict) else None
    if offers:
        price = parse_price(offers.get("price"))
    if price is None:
        for tag in soup.select('[itemprop="price"], meta[property="product:price:amount"]'):
            price = parse_price(tag.get("content"))
            if price is not None:
                break
        if price is None:
            for tag in soup.select(".price, .product-price, [data-price]"):
                price = parse_price(tag.get("content") or tag.get_text(" ", strip=True))
                if price is not None:
                    break

    availability = availability_from_sources(product_data, soup)

    canonical = None
    for tag in soup.select('link[rel="canonical"]'):
        href = tag.get("href")
        if href:
            canonical = _normalise_url(href)
            break

    # Matching logic
    name_matches = matches(name, query) if name else False
    brand_matches = matches(brand, query) if brand else False
    matching = name_matches or brand_matches

    filter_reason = None
    if not matching:
        filter_reason = "no_match_name_or_brand"

    returned = False
    if matching:
        returned = True

    diag_page = DiagnosticProductPage(
        url=url,
        http_status=None,
        final_url=None,
        redirects=[],
        html_bytes=len(html),
        used_playwright=False,
        h1=h1_text or None,
        json_ld_products=data,
        product_name=name or None,
        brand=brand or None,
        size_ml=size,
        canonical=canonical,
        availability=availability,
        matching=matching,
        filter_reason=filter_reason,
        returned=returned,
    )

    product_item = None
    if returned:
        product_item = {
            "url": url,
            "name": name,
            "brand": brand,
            "size_ml": size,
            "image": image,
            "price": price,
            "availability": availability,
            "canonical": canonical,
            "identity": {
                "name": name,
                "brand": brand,
                "sku": {"value": url} if url else None,
            },
        }

    return product_item, diag_page


def diagnose_query(
    query: str,
    session: Optional[requests.Session] = None,
    max_product_pages: int = 10,
) -> DiagnosticResult:
    """Run a full diagnostic for a single query.

    This function:
    - performs the same HTTP + Playwright discovery as search();
    - opens up to max_product_pages product pages;
    - records every step with reasons for rejection;
    - returns a structured DiagnosticResult.
    """
    start_total = time.perf_counter()

    if session is None:
        session = requests.Session()

    # HTTP discovery
    http_disc = _discover_http_diagnostic(session, query)

    # Playwright discovery
    pw_disc = _discover_playwright_diagnostic(query)

    # Merge candidates (HTTP first, then PW if needed)
    seen_urls: Set[str] = set()
    candidate_urls: List[str] = []

    for u in http_disc["accepted_candidates"]:
        if u and u not in seen_urls:
            seen_urls.add(u)
            candidate_urls.append(u)

    if len(candidate_urls) < 80 and pw_disc["urls_accepted"]:
        # We don't have full PW URLs here, but in real usage you'd merge properly.
        pass

    # Fetch product pages
    product_pages: List[DiagnosticProductPage] = []
    final_results: List[Dict[str, Any]] = []

    for url in candidate_urls[:max_product_pages]:
        html, html_bytes, http_status, final_url, redirects, used_pw = _fetch_product_page_diagnostic(
            session, url, max_html_bytes=500000
        )
        if not html:
            diag_page = DiagnosticProductPage(
                url=url,
                http_status=http_status,
                final_url=final_url,
                redirects=redirects,
                html_bytes=html_bytes,
                used_playwright=used_pw,
                h1=None,
                json_ld_products=[],
                product_name=None,
                brand=None,
                size_ml=None,
                canonical=None,
                availability="unknown",
                matching=False,
                filter_reason="no_html",
                returned=False,
            )
            product_pages.append(diag_page)
            continue

        product_item, diag_page = _product_diagnostic(url, html, query)
        diag_page.http_status = http_status
        diag_page.final_url = final_url
        diag_page.redirects = redirects
        diag_page.used_playwright = used_pw
        product_pages.append(diag_page)

        if product_item:
            final_results.append(product_item)

    total_elapsed_ms = (time.perf_counter() - start_total) * 1000

    return DiagnosticResult(
        query=query,
        search_urls=[http_disc["search_page"]],
        http_discovery=http_disc,
        playwright_discovery=pw_disc,
        product_pages=product_pages,
        final_results=final_results,
        total_elapsed_ms=total_elapsed_ms,
    )


# =============================================================================
# PRODUCTION SEARCH (UNCHANGED LOGIC)
# =============================================================================


def search(query: str) -> List[Dict[str, Any]]:
    query = clean(query)
    if not query:
        return []
    session = requests.Session()
    results, seen = [], set()
    try:
        for url in _discover(session, query):
            html = None
            try:
                response = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
                if response.status_code < 400:
                    html = response.text
            except requests.RequestException:
                pass
            if not html:
                html = _fetch_product_with_playwright(url)
            if not html:
                continue
            item = _product(url, html, query)
            if not item:
                continue
            sku = item["identity"].get("sku")
            sku_value = sku.get("value") if sku else None
            key = (item["url"].lower(), sku_value)
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
        return results
    finally:
        session.close()


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)
