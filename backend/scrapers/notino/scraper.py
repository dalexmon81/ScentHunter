"""Generic Notino.fr scraper for ScentHunter.

The scraper is deliberately product-agnostic. It discovers products from
Notino's own search results, validates candidates on their product pages and
never contains product-specific names, URLs, seeds or exceptions.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    PlaywrightTimeoutError = Exception
    sync_playwright = None

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp?exps={query}"

REQUEST_TIMEOUT = int(os.getenv("NOTINO_TIMEOUT_S", "20"))
BROWSER_TIMEOUT_MS = int(os.getenv("NOTINO_BROWSER_TIMEOUT_MS", "35000"))
MAX_CANDIDATES = int(os.getenv("NOTINO_MAX_CANDIDATES", "60"))
MAX_RESULTS = int(os.getenv("NOTINO_MAX_RESULTS", "20"))
MAX_VARIANTS = int(os.getenv("NOTINO_MAX_VARIANTS", "6"))
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
URL_RE = re.compile(r"(?:https?:)?//(?:www\.)?notino\.fr/[A-Za-z0-9_./?=&%+\-]+|/[A-Za-z0-9_./?=&%+\-]+")

NON_PRODUCT_FIRST_SEGMENTS = {
    "search.asp", "parfums", "parfums-homme", "parfums-femme", "cosmetiques",
    "maquillage", "cheveux", "corps", "visage", "promotions", "nouveaux",
    "marques", "panier", "checkout", "login", "account", "magazine", "contact",
    "brands", "blog", "beautyblog", "erotisme", "mere-et-enfant", "dermo-cosmetique",
}

GENERIC_QUERY_WORDS = {
    "eau", "de", "parfum", "parfums", "perfume", "perfumes", "edp", "edt",
    "extrait", "spray", "vaporisateur", "for", "pour", "the", "du", "des", "a", "an",
}

GENDER_ALIASES = {
    "him": "men", "his": "men", "man": "men", "men": "men", "homme": "men", "hommes": "men", "male": "men",
    "her": "women", "woman": "women", "women": "women", "femme": "women", "femmes": "women", "female": "women",
    "unisex": "unisex", "unisexe": "unisex", "mixte": "unisex",
}

STOCK_IN = ("en stock", "disponible", "available", "in stock")
STOCK_OUT = ("en rupture", "rupture de stock", "actuellement en rupture", "indisponible", "épuisé", "epuise", "out of stock", "sold out")


@dataclass
class Candidate:
    url: str
    name: str
    score: int
    source: str
    context: str = ""


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


def semantic_tokens(value: Any) -> list[str]:
    result: list[str] = []
    for token in tokens(value):
        mapped = GENDER_ALIASES.get(token, token)
        if mapped in GENERIC_QUERY_WORDS:
            continue
        result.append(mapped)
    return result


def semantic_match(name: str, query: str) -> bool:
    """Require the meaningful query sequence to occur contiguously in the name.

    This prevents e.g. "Hawas Black" from satisfying "Hawas for Him" merely
    because both are men's Hawas products.
    """
    wanted = semantic_tokens(query)
    actual = semantic_tokens(name)
    if not wanted:
        return False
    if len(wanted) == 1:
        return wanted[0] in actual
    for index in range(len(actual) - len(wanted) + 1):
        if actual[index:index + len(wanted)] == wanted:
            return True
    return False


def requested_size(query: str) -> float | None:
    match = SIZE_RE.search(clean(query))
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return value * 10 if match.group(2).lower() == "cl" else value


def requested_gender(query: str) -> str | None:
    found = {GENDER_ALIASES[token] for token in tokens(query) if token in GENDER_ALIASES}
    return next(iter(found)) if len(found) == 1 else None


def query_variants(query: str) -> list[str]:
    raw_tokens = tokens(query)
    if not raw_tokens:
        return []

    variants: list[str] = []
    seen: set[str] = set()

    def add(parts: Iterable[str]) -> None:
        value = clean(" ".join(parts))
        key = norm(value)
        if value and key not in seen:
            seen.add(key)
            variants.append(value)

    add(raw_tokens)
    add(t for t in raw_tokens if t not in GENERIC_QUERY_WORDS)

    # Identity-only form: remove generic words AND gender terms. This is the
    # important fallback for Notino searches that rank a gender phrase poorly.
    identity = [t for t in raw_tokens if t not in GENERIC_QUERY_WORDS and t not in GENDER_ALIASES]
    add(identity)

    if len(identity) > 1:
        add(identity[:2])
    if len(identity) > 2:
        add(identity[:3])

    # Last resort: search each meaningful identity token individually.
    for token in identity:
        add([token])

    return variants[:MAX_VARIANTS]


def normalise_url(href: Any) -> str | None:
    href = clean(href).replace("\\/", "/")
    if not href:
        return None
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
    if path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".svg", ".gif")):
        return None
    return "https://www.notino.fr" + path + (("?" + parsed.query) if parsed.query else "")


def looks_product_url(url: str) -> bool:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return False
    if parts[0].lower() in NON_PRODUCT_FIRST_SEGMENTS:
        return False
    if parsed.path.lower().endswith("search.asp"):
        return False
    last = norm(parts[-1])
    if not last:
        return False
    return len(last.split()) >= 2 or bool(re.search(r"p \d+", last))


def walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def json_ld_products(soup: BeautifulSoup) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for obj in walk_json(data):
            typ = obj.get("@type")
            if typ == "Product" or (isinstance(typ, list) and any(str(x).lower() == "product" for x in typ)):
                output.append(obj)
    return output


def parse_price(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return round(float(value), 2) if value > 0 else None
    text = clean(value)
    match = PRICE_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace(" ", "").replace("\xa0", "")
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
    result: list[float] = []
    for match in PRICE_RE.finditer(clean(text)):
        value = parse_price(match.group(0))
        if value is not None and value not in result:
            result.append(value)
    return result


def extract_size(text: str) -> float | None:
    match = SIZE_RE.search(clean(text))
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return value * 10 if match.group(2).lower() == "cl" else value


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


def brand_name(product: dict[str, Any]) -> str | None:
    brand = product.get("brand")
    if isinstance(brand, dict):
        value = clean(brand.get("name"))
        return value or None
    value = clean(brand)
    return value or None


def image_url(product: dict[str, Any], soup: BeautifulSoup) -> str | None:
    image = product.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    if image:
        return clean(image)
    meta = soup.select_one('meta[property="og:image"]')
    return clean(meta.get("content")) if meta and meta.get("content") else None


def offer_list(product: dict[str, Any]) -> list[dict[str, Any]]:
    offers = product.get("offers")
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [x for x in offers if isinstance(x, dict)]
    return []


def concentration_from_name(name: str) -> str | None:
    text = norm(name)
    for label, pattern in (
        ("Extrait de Parfum", r"\bextrait(?: de)? parfum\b"),
        ("Eau de Parfum", r"\beau de parfum\b|\bedp\b"),
        ("Eau de Toilette", r"\beau de toilette\b|\bedt\b"),
        ("Eau de Cologne", r"\beau de cologne\b|\bedc\b"),
        ("Parfum", r"\bparfum\b"),
    ):
        if re.search(pattern, text):
            return label
    return None


def candidate_score(name: str, url: str, query: str, context: str = "") -> int:
    score = 0
    if semantic_match(name, query):
        score += 200
    wanted = semantic_tokens(query)
    actual = semantic_tokens(name)
    score += 20 * len(set(wanted) & set(actual))
    if requested_gender(query) and requested_gender(query) == extract_gender(name + " " + context):
        score += 30
    wanted_size = requested_size(query)
    if wanted_size is not None and wanted_size == extract_size(name + " " + context):
        score += 20
    if "/p-" in url.lower():
        score += 5
    return score


def nearby_context(anchor: Any) -> str:
    node = anchor
    best = clean(anchor.get_text(" ", strip=True))
    for _ in range(7):
        if node is None:
            break
        text = clean(node.get_text(" ", strip=True))
        if 15 <= len(text) <= 1800 and (extract_prices(text) or any(x in norm(text) for x in STOCK_IN + STOCK_OUT)):
            best = text
            break
        node = getattr(node, "parent", None)
    return best


def extract_search_candidates(html: str, query: str) -> list[Candidate]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Candidate] = {}

    def add(url: str | None, name: str, source: str, context: str = "") -> None:
        if not url or not looks_product_url(url):
            return
        name = clean(name)
        if not name:
            return
        score = candidate_score(name, url, query, context)
        # Discovery is allowed to be broader than final validation. Keep only
        # candidates sharing at least one real identity token with the query.
        wanted = set(semantic_tokens(query))
        actual = set(semantic_tokens(name + " " + context + " " + url))
        if wanted and not (wanted & actual):
            return
        current = found.get(url)
        candidate = Candidate(url, name, score, source, context)
        if current is None or candidate.score > current.score:
            found[url] = candidate

    for product in json_ld_products(soup):
        url = normalise_url(product.get("url"))
        name = clean(product.get("name"))
        if url and name:
            add(url, name, "jsonld")

    for anchor in soup.find_all("a", href=True):
        url = normalise_url(anchor.get("href"))
        if not url or not looks_product_url(url):
            continue
        context = nearby_context(anchor)
        anchor_name = clean(anchor.get_text(" ", strip=True))
        if not anchor_name:
            image = anchor.find("img")
            anchor_name = clean((image or {}).get("alt")) if image else ""
        add(url, anchor_name or context, "dom", context)

    # Embedded product data often contains the product link even when the
    # rendered DOM hides it behind client-side components.
    raw_text = html.replace("\\/", "/")
    for match in URL_RE.finditer(raw_text):
        url = normalise_url(match.group(0))
        if not url or not looks_product_url(url):
            continue
        context = clean(raw_text[max(0, match.start() - 450):match.end() + 700])
        words = re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'&+\-]{1,}", context)
        name = clean(" ".join(words[:35]))
        add(url, name, "embedded", context)

    return sorted(found.values(), key=lambda c: c.score, reverse=True)[:MAX_CANDIDATES]


def product_from_page(html: str, final_url: str, query: str, diagnostic: bool = False) -> tuple[dict[str, Any] | None, str]:
    soup = BeautifulSoup(html, "html.parser")
    products = json_ld_products(soup)
    h1 = soup.find("h1")
    h1_name = clean(h1.get_text(" ", strip=True)) if h1 else ""

    selected: dict[str, Any] | None = None
    selected_name = ""
    for product in products:
        name = clean(product.get("name"))
        if name and semantic_match(name, query):
            selected = product
            selected_name = name
            break

    if selected is None and h1_name and semantic_match(h1_name, query):
        selected = {}
        selected_name = h1_name

    if not selected_name:
        return None, "product_identity_mismatch_or_unavailable"

    canonical_url = normalise_url((selected or {}).get("url")) or normalise_url(final_url) or final_url
    offers = offer_list(selected or {})

    price: float | None = None
    currency = "EUR"
    for offer in offers:
        offer_currency = clean(offer.get("priceCurrency")).upper()
        if offer_currency and offer_currency not in {"EUR", "€"}:
            continue
        value = parse_price(offer.get("price"))
        if value is not None:
            price = value
            break

    page_text = clean(soup.get_text(" ", strip=True))
    if price is None:
        prices = extract_prices(page_text)
        if prices:
            # Prefer a price close to the product heading / purchase block.
            price = prices[0]

    availability: bool | None = None
    availability_name = "unknown"
    for offer in offers:
        raw = clean(offer.get("availability"))
        if raw:
            availability, availability_name = availability_from_text(raw)
            if availability is not None:
                break
    if availability is None:
        availability, availability_name = availability_from_text(page_text)

    wanted_size = requested_size(query)
    page_size = extract_size(selected_name)
    if page_size is None:
        page_size = extract_size(page_text[:12000])
    if wanted_size is not None and page_size is not None and wanted_size != page_size:
        return None, "size_mismatch"

    gender = extract_gender(selected_name)
    if requested_gender(query) and gender not in {requested_gender(query), "unknown"}:
        return None, "gender_mismatch"

    brand = brand_name(selected or {})
    image = image_url(selected or {}, soup)
    concentration = concentration_from_name(selected_name)

    item = {
        "store": STORE,
        "source": {
            "source_name": selected_name,
            "source_brand": brand,
            "url": canonical_url,
            "image": image,
        },
        "identity": {
            "gtin": clean((selected or {}).get("gtin")) or None,
            "mpn": clean((selected or {}).get("mpn")) or None,
            "sku": clean((selected or {}).get("sku")) or None,
            "store_product_id": None,
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": page_size,
            "concentration": {"value": concentration, "source": "product_name"} if concentration else None,
            "gender": {"value": gender, "source": "product_name"},
            "packaging_type": {"value": "product", "source": "default"},
        },
        "offer": {
            "price": price,
            "currency": currency,
            "availability": availability_name,
        },
        "provenance": {
            "source_page": canonical_url,
            "product_source": "notino_product_page",
            "name_source": "jsonld" if selected_name and selected else "h1",
            "brand_source": "jsonld" if brand else None,
            "price_source": "jsonld" if any(parse_price(o.get("price")) is not None for o in offers) else "visible_page_price",
        },
        "raw_data": {"jsonld": selected or {}},
        "name": selected_name,
        "price": "" if price is None else f"{price:.2f}".replace(".", ",") + " €",
        "url": canonical_url,
        "image": image,
        "available": availability,
    }
    return item, "accepted"


def fetch_requests(session: requests.Session, url: str) -> str | None:
    try:
        response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if response.status_code >= 400:
            return None
        return response.text
    except requests.RequestException:
        return None


def search_requests(query: str, diagnostics: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    session = requests.Session()
    candidates: dict[str, Candidate] = {}
    variants = query_variants(query)

    for variant in variants:
        url = SEARCH_URL.format(query=quote_plus(variant))
        html = fetch_requests(session, url)
        if not html:
            if diagnostics is not None:
                diagnostics.append({"variant": variant, "mode": "requests", "status": "fetch_failed", "candidate_count": 0})
            continue
        found = extract_search_candidates(html, query)
        for candidate in found:
            current = candidates.get(candidate.url)
            if current is None or candidate.score > current.score:
                candidates[candidate.url] = candidate
        if diagnostics is not None:
            diagnostics.append({"variant": variant, "mode": "requests", "status": "ok", "candidate_count": len(found)})

    ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)
    results: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for candidate in ranked:
        html = fetch_requests(session, candidate.url)
        if not html:
            rejected.append({"url": candidate.url, "reason": "product_page_fetch_failed"})
            continue
        item, reason = product_from_page(html, candidate.url, query)
        if item:
            results.append(item)
        else:
            rejected.append({"url": candidate.url, "reason": reason})
        if len(results) >= MAX_RESULTS:
            break

    return deduplicate(results)


def search_playwright(query: str, diagnostics: list[dict[str, Any]] | None = None, rejected_out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if sync_playwright is None:
        return []

    candidates: dict[str, Candidate] = {}
    rejected = rejected_out if rejected_out is not None else []
    variants = query_variants(query)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="fr-FR",
                extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
                viewport={"width": 1365, "height": 900},
            )
            page = context.new_page()

            for variant in variants:
                url = SEARCH_URL.format(query=quote_plus(variant))
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
                    try:
                        page.wait_for_load_state("networkidle", timeout=12000)
                    except PlaywrightTimeoutError:
                        pass
                    page.wait_for_timeout(800)
                    html = page.content()
                    status = response.status if response else None
                    final_url = page.url
                except Exception as exc:
                    if diagnostics is not None:
                        diagnostics.append({"variant": variant, "mode": "playwright", "status": "error", "error": f"{type(exc).__name__}: {exc}", "candidate_count": 0})
                    continue

                found = extract_search_candidates(html, query)
                for candidate in found:
                    current = candidates.get(candidate.url)
                    if current is None or candidate.score > current.score:
                        candidates[candidate.url] = candidate

                if diagnostics is not None:
                    diagnostics.append({"variant": variant, "mode": "playwright", "status": "ok", "http_status": status, "final_url": final_url, "candidate_count": len(found)})

            ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)
            results: list[dict[str, Any]] = []

            for candidate in ranked:
                try:
                    response = page.goto(candidate.url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except PlaywrightTimeoutError:
                        pass
                    page.wait_for_timeout(500)
                    html = page.content()
                    final_url = page.url
                except Exception as exc:
                    rejected.append({"rank": len(rejected) + 1, "url": candidate.url, "reason": "product_page_navigation_error", "error": f"{type(exc).__name__}: {exc}"})
                    continue

                item, reason = product_from_page(html, final_url, query)
                if item:
                    results.append(item)
                else:
                    rejected.append({"rank": len(rejected) + 1, "url": candidate.url, "reason": reason, "context": candidate.context[:500], "sources": [candidate.source]})
                if len(results) >= MAX_RESULTS:
                    break

            browser.close()
            return deduplicate(results)
    except Exception as exc:
        LOGGER.warning("Notino Playwright error: %s", exc)
        if diagnostics is not None:
            diagnostics.append({"mode": "playwright", "status": "fatal_error", "error": f"{type(exc).__name__}: {exc}"})
        return []


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        url = clean(item.get("url"))
        name = norm(item.get("name"))
        if not url or not name:
            continue
        key = (url, name)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def search(query: str) -> list[dict[str, Any]]:
    query = clean(query)
    if not query:
        return []

    # Notino is client-rendered and can return a different ranking/HTML shape
    # to plain HTTP clients. Browser discovery is therefore the primary path.
    if BROWSER_ENABLED:
        results = search_playwright(query)
        if results:
            return results

    return search_requests(query)


def diagnose(query: str) -> dict[str, Any]:
    """Detailed, bounded diagnostic used by /diagnose-notino in ScentHunter."""
    query = clean(query)
    report: dict[str, Any] = {
        "query": query,
        "variants": query_variants(query),
        "browser_enabled": BROWSER_ENABLED,
        "discovery": [],
        "merged_candidates": 0,
        "validated_candidates": 0,
        "accepted_products": 0,
        "rejected_candidates": [],
        "final_results": [],
        "final_status": "no_valid_products",
    }
    if not query:
        report["final_status"] = "invalid_query"
        return report

    diagnostics: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    # Run the same primary path as search(), but keep its evidence.
    if BROWSER_ENABLED:
        results = search_playwright(query, diagnostics, rejected)
    if not results:
        results = search_requests(query, diagnostics)

    report["discovery"] = diagnostics
    report["rejected_candidates"] = rejected[:50]
    report["final_results"] = results
    report["accepted_products"] = len(results)
    report["validated_candidates"] = len(rejected) + len(results)
    report["merged_candidates"] = sum(int(x.get("candidate_count", 0) or 0) for x in diagnostics)
    report["final_status"] = "products_found" if results else "no_valid_products"
    return report
