"""
Notino.fr scraper for ScentHunter.

Generic discovery:
- Notino internal search with progressively relaxed query variants.
- Search-result JSON-LD and DOM/card links.
- Product-page validation from H1, JSON-LD, visible data and URL.
- Requests first, Playwright fallback.
- No product-specific seeds, URLs, names, prices or exceptions.

Public interface:
    search(query) -> list[dict]
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from typing import Any, Iterable
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
SEARCH_URL = BASE_URL + "/search.asp?exps={query}"

REQUEST_TIMEOUT = int(os.getenv("NOTINO_TIMEOUT_S", "20"))
BROWSER_TIMEOUT_MS = int(os.getenv("NOTINO_BROWSER_TIMEOUT_MS", "35000"))
MAX_CANDIDATES = int(os.getenv("NOTINO_MAX_CANDIDATES", "80"))
MAX_RESULTS = int(os.getenv("NOTINO_MAX_RESULTS", "20"))
BROWSER_ENABLED = os.getenv("NOTINO_BROWSER", "1").lower() not in {"0", "false", "no"}

LOGGER = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

PRICE_RE = re.compile(
    r"(?<![\d.,])((?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.]\d{1,2})?)\s*(?:€|EUR)(?!\w)",
    re.I,
)
SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", re.I)

NON_PRODUCT_FIRST_SEGMENTS = {
    "search.asp", "parfums", "parfums-homme", "parfums-femme",
    "cosmetiques", "maquillage", "cheveux", "corps", "visage",
    "promotions", "nouveaux", "marques", "panier", "checkout",
    "login", "account", "magazine", "contact", "brands", "blog",
}

GENERIC_QUERY_WORDS = {
    "eau", "de", "parfum", "parfums", "perfume", "perfumes",
    "edp", "edt", "extrait", "spray", "vaporisateur",
    "for", "pour", "the", "du", "des", "a", "an",
}

GENDER_ALIASES = {
    "him": "men", "his": "men", "man": "men", "men": "men",
    "homme": "men", "hommes": "men", "male": "men",
    "her": "women", "woman": "women", "women": "women",
    "femme": "women", "femmes": "women", "female": "women",
    "unisex": "unisex", "unisexe": "unisex", "mixte": "unisex",
}

STOCK_IN = (
    "en stock", "disponible", "available", "in stock",
)
STOCK_OUT = (
    "en rupture", "rupture de stock", "actuellement en rupture",
    "indisponible", "épuisé", "epuise", "out of stock", "sold out",
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value)).lower()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(value: Any) -> list[str]:
    return [x for x in norm(value).split() if x]


def semantic_tokens(value: Any) -> set[str]:
    result = set()
    for token in tokens(value):
        mapped = GENDER_ALIASES.get(token, token)
        if mapped in GENERIC_QUERY_WORDS:
            continue
        result.add(mapped)
    return result


def requested_gender(query: str) -> str | None:
    found = {GENDER_ALIASES[t] for t in tokens(query) if t in GENDER_ALIASES}
    if len(found) == 1:
        return next(iter(found))
    return None


def requested_size(query: str) -> float | None:
    match = SIZE_RE.search(query)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10
    return value


def normalise_url(href: Any) -> str | None:
    href = clean(href)
    if not href:
        return None
    href = href.replace("\\/", "/")
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(BASE_URL, href)
    try:
        parsed = urlparse(href)
    except Exception:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in {"notino.fr", "www.notino.fr"}:
        return None
    path = parsed.path.rstrip("/")
    if not path or path == "/":
        return None
    if path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".svg", ".gif")):
        return None
    return f"https://www.notino.fr{path}"


def looks_product_url(url: str) -> bool:
    try:
        path = urlparse(url).path.strip("/")
    except Exception:
        return False
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return False
    if parts[0].lower() in NON_PRODUCT_FIRST_SEGMENTS:
        return False
    if "search.asp" in path.lower():
        return False
    last = norm(parts[-1])
    return bool(last) and (len(last.split()) >= 2 or re.search(r"\bp-\d+\b", last))


def walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def json_ld_products(soup: BeautifulSoup) -> list[dict[str, Any]]:
    products = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        for obj in walk_json(data):
            typ = obj.get("@type")
            if (
                typ == "Product"
                or (isinstance(typ, list) and any(str(x).lower() == "product" for x in typ))
            ):
                products.append(obj)
    return products


def parse_price(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = clean(value)
    match = PRICE_RE.search(text)
    if match:
        raw = match.group(1).replace(" ", "").replace("\xa0", "")
    else:
        raw = text.replace(",", ".")
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", raw):
            return None
    if raw.count(".") > 1:
        raw = raw.replace(".", "")
    elif "." in raw and "," not in raw and re.search(r"\.\d{3}$", raw):
        raw = raw.replace(".", "")
    raw = raw.replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return round(value, 2) if value > 0 else None


def extract_prices(text: str) -> list[float]:
    values = []
    for match in PRICE_RE.finditer(clean(text)):
        value = parse_price(match.group(0))
        if value is not None and value not in values:
            values.append(value)
    return values


def extract_size(text: str) -> float | None:
    match = SIZE_RE.search(clean(text))
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10
    return value


def extract_gender(text: str) -> str:
    value = norm(text)
    if re.search(r"\b(men|male|homme|hommes)\b", value):
        return "men"
    if re.search(r"\b(women|female|femme|femmes)\b", value):
        return "women"
    if re.search(r"\b(unisex|unisexe|mixte)\b", value):
        return "unisex"
    return "unknown"


def availability_from_text(text: str) -> tuple[bool | None, str]:
    low = norm(text)
    if any(term in low for term in STOCK_OUT):
        return False, "out_of_stock"
    if any(term in low for term in STOCK_IN):
        return True, "in_stock"
    return None, "unknown"


def product_identity_matches(name: str, query: str, page_text: str = "") -> bool:
    wanted = semantic_tokens(query)
    if not wanted:
        return False

    identity = semantic_tokens(name)
    if wanted.issubset(identity):
        return True

    # Some Notino pages use a shortened H1 while the full product name is
    # present in the product description/JSON-LD. Use the page only as a
    # secondary identity source, never as the sole source.
    page_identity = semantic_tokens(page_text[:20000])
    return wanted.issubset(page_identity) and len(wanted) <= 3


def candidate_score(name: str, url: str, query: str, context: str = "") -> int:
    wanted = semantic_tokens(query)
    identity = semantic_tokens(name)
    score = 0
    score += 100 if wanted and wanted.issubset(identity) else 0
    score += 10 * len(wanted & identity)
    if requested_gender(query):
        gender = requested_gender(query)
        if gender == extract_gender(name + " " + context):
            score += 20
    size = requested_size(query)
    if size is not None and size == extract_size(name + " " + context):
        score += 15
    if url.endswith("/"):
        score += 1
    return score


def extract_search_candidates(html: str, query: str) -> list[tuple[str, str, int]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: dict[str, tuple[str, int]] = {}

    # JSON-LD is useful for discovery, but MUST be filtered by query.
    for product in json_ld_products(soup):
        url = normalise_url(product.get("url"))
        if not url or not looks_product_url(url):
            continue
        name = clean(product.get("name"))
        if not name:
            continue
        score = candidate_score(name, url, query)
        if semantic_tokens(query).issubset(semantic_tokens(name)):
            candidates[url] = (name, max(score, 120))

    # DOM links are the main fallback. Search cards vary between desktop/mobile.
    for anchor in soup.find_all("a", href=True):
        url = normalise_url(anchor.get("href"))
        if not url or not looks_product_url(url):
            continue

        node = anchor
        best_context = clean(anchor.get_text(" ", strip=True))
        for _ in range(8):
            if node is None:
                break
            text = clean(node.get_text(" ", strip=True))
            if 20 <= len(text) <= 2500 and (extract_prices(text) or any(x in norm(text) for x in STOCK_IN + STOCK_OUT)):
                best_context = text
                break
            node = getattr(node, "parent", None)

        anchor_text = clean(anchor.get_text(" ", strip=True))
        combined = f"{anchor_text} {best_context}"
        wanted = semantic_tokens(query)

        # Discovery may be relaxed, but never accept a candidate with none of
        # the actual identity tokens.
        if not wanted or not (wanted & semantic_tokens(combined + " " + url)):
            continue

        name = anchor_text or best_context
        score = candidate_score(name, url, query, best_context)
        if url not in candidates or score > candidates[url][1]:
            candidates[url] = (name, score)

    ranked = sorted(
        ((url, name, score) for url, (name, score) in candidates.items()),
        key=lambda x: x[2],
        reverse=True,
    )
    return ranked[:MAX_CANDIDATES]


def extract_product_from_page(html: str, final_url: str, query: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    products = json_ld_products(soup)
    page_text = clean(soup.get_text(" ", strip=True))

    h1 = soup.find("h1")
    h1_name = clean(h1.get_text(" ", strip=True)) if h1 else ""

    selected: dict[str, Any] | None = None
    for product in products:
        product_name = clean(product.get("name"))
        product_url = normalise_url(product.get("url")) or final_url
        if not product_name:
            continue
        if product_identity_matches(product_name, query, page_text):
            selected = product
            final_url = product_url
            break

    name = clean((selected or {}).get("name")) or h1_name
    if not name:
        name = clean(page_text[:200])

    # Final identity gate. This is deliberately strict enough to prevent
    # unrelated products from leaking into ScentHunter.
    if not product_identity_matches(name, query, page_text):
        return None

    offers = (selected or {}).get("offers", {})
    offer_list = (
        [x for x in offers if isinstance(x, dict)]
        if isinstance(offers, list)
        else [offers] if isinstance(offers, dict) else []
    )

    price = None
    for offer in offer_list:
        currency = clean(offer.get("priceCurrency")).upper()
        if currency and currency not in {"EUR", "€"}:
            continue
        price = parse_price(offer.get("price"))
        if price is not None:
            break

    if price is None:
        prices = extract_prices(page_text)
        if prices:
            price = prices[0]

    if price is None:
        return None

    availability = None
    availability_name = "unknown"
    for offer in offer_list:
        raw = clean(offer.get("availability"))
        if raw:
            availability, availability_name = availability_from_text(raw)
            if availability is not None:
                break
    if availability is None:
        availability, availability_name = availability_from_text(page_text)

    # If a requested size exists, reject a different size when the page exposes
    # a clear size. If no size was requested, keep the product.
    wanted_size = requested_size(query)
    page_size = extract_size(name + " " + page_text[:12000])
    if wanted_size is not None and page_size is not None and wanted_size != page_size:
        return None

    return {
        "store": STORE,
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": normalise_url(final_url) or final_url,
        "available": availability,
        "availability": availability_name,
    }


def fetch_page(session: requests.Session, url: str) -> str | None:
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            return None
        return response.text
    except requests.RequestException:
        return None


def query_variants(query: str) -> list[str]:
    original = clean(query)
    words = tokens(original)
    variants = [original]

    # Remove generic presentation words and language/gender fillers.
    reduced = [w for w in words if w not in GENERIC_QUERY_WORDS]
    if reduced:
        variants.append(" ".join(reduced))

    # Keep the strongest identity tokens together. This is generic and does
    # not know any product names.
    if len(reduced) > 1:
        variants.append(" ".join(reduced[:2]))

    # Try the original words in reverse only when the site ranking is odd.
    if len(words) > 1:
        variants.append(" ".join(reversed(words)))

    output = []
    seen = set()
    for value in variants:
        value = clean(value)
        key = norm(value)
        if value and key not in seen:
            seen.add(key)
            output.append(value)
    return output


def search_requests(query: str) -> list[dict[str, Any]]:
    session = requests.Session()
    all_candidates: dict[str, tuple[str, int]] = {}

    for variant in query_variants(query):
        url = SEARCH_URL.format(query=quote_plus(variant))
        html = fetch_page(session, url)
        if not html:
            continue

        for candidate_url, name, score in extract_search_candidates(html, query):
            if candidate_url not in all_candidates or score > all_candidates[candidate_url][1]:
                all_candidates[candidate_url] = (name, score)

        # A strong candidate is enough; product-page validation below decides.
        if any(score >= 120 for _, score in all_candidates.values()):
            break

    ranked = sorted(
        ((url, name, score) for url, (name, score) in all_candidates.items()),
        key=lambda x: x[2],
        reverse=True,
    )

    results = []
    for url, fallback_name, _ in ranked[:MAX_CANDIDATES]:
        html = fetch_page(session, url)
        if not html:
            continue
        item = extract_product_from_page(html, url, query)
        if item:
            results.append(item)
        if len(results) >= MAX_RESULTS:
            break

    return deduplicate(results)


def search_playwright(query: str) -> list[dict[str, Any]]:
    if sync_playwright is None:
        return []

    candidates: dict[str, tuple[str, int]] = {}

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

            for variant in query_variants(query):
                url = SEARCH_URL.format(query=quote_plus(variant))
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
                    try:
                        page.wait_for_load_state("networkidle", timeout=12000)
                    except PlaywrightTimeoutError:
                        pass
                    page.wait_for_timeout(1200)
                    html = page.content()
                except Exception:
                    continue

                for candidate_url, name, score in extract_search_candidates(html, query):
                    if candidate_url not in candidates or score > candidates[candidate_url][1]:
                        candidates[candidate_url] = (name, score)

                if any(score >= 120 for _, score in candidates.values()):
                    break

            ranked = sorted(
                ((url, name, score) for url, (name, score) in candidates.items()),
                key=lambda x: x[2],
                reverse=True,
            )

            results = []
            for candidate_url, fallback_name, _ in ranked[:MAX_CANDIDATES]:
                try:
                    page.goto(
                        candidate_url,
                        wait_until="domcontentloaded",
                        timeout=BROWSER_TIMEOUT_MS,
                    )
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except PlaywrightTimeoutError:
                        pass
                    page.wait_for_timeout(600)
                    html = page.content()
                    final_url = page.url
                except Exception:
                    continue

                item = extract_product_from_page(html, final_url, query)
                if item:
                    results.append(item)
                if len(results) >= MAX_RESULTS:
                    break

            browser.close()
            return deduplicate(results)

    except Exception as exc:
        LOGGER.warning("Notino Playwright error: %s", exc)
        return []


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for item in items:
        url = clean(item.get("url"))
        price = clean(item.get("price"))
        if not url or not price:
            continue
        key = (url, price)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def search(query: str) -> list[dict[str, Any]]:
    query = clean(query)
    if not query:
        return []

    # Requests is cheap and deterministic. Playwright is the fallback for
    # Notino responses that require client-side rendering.
    results = search_requests(query)
    if results:
        return results

    if BROWSER_ENABLED:
        return search_playwright(query)

    return []
