from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple
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
BROWSER_TIMEOUT_MS = int(os.getenv("NOTINO_BROWSER_TIMEOUT_MS", "35000"))
PRODUCT_TIMEOUT_MS = int(os.getenv("NOTINO_PRODUCT_TIMEOUT_MS", "18000"))
MAX_CANDIDATES = int(os.getenv("NOTINO_MAX_CANDIDATES", "100"))
MAX_PRODUCT_PAGES = int(os.getenv("NOTINO_MAX_PRODUCT_PAGES", "60"))
BROWSER_ENABLED = os.getenv("NOTINO_BROWSER", "1").lower() not in {"0", "false", "no"}

LOGGER = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

PRICE_RE = re.compile(
    r"(?<![\d.,])"
    r"((?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.]\d{2})?)"
    r"\s*(?:€|EUR)"
    r"(?!\w)",
    re.I,
)

SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", re.I)

# These are structural navigation paths, not product-specific exceptions.
NON_PRODUCT_PATHS = {
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
    "magazine",
    "contact",
    "brands",
    "blog",
}

# Cloudflare/anti-bot challenge routes are structural infrastructure pages,
# never product pages. They are detected generically and surfaced in the
# diagnostic report instead of being treated as product candidates.
CHALLENGE_PATH_PREFIXES = {
    "challenges.cloudflare.com",
    "cdn-cgi",
    "challenge",
    "turnstile",
}

CHALLENGE_MARKERS = (
    "just a moment",
    "verify you are human",
    "checking your browser",
    "cf-chl-",
    "turnstile",
    "cloudflare",
)

NON_PRODUCT_TERMS = {
    "gift set",
    "set regalo",
    "coffret",
    "bundle",
    "deodorant",
    "deo spray",
    "shower gel",
    "body lotion",
    "after shave",
    "aftershave",
    "travel set",
    "discovery set",
}

OUT_OF_STOCK_TERMS = (
    "rupture de stock",
    "en rupture",
    "indisponible",
    "épuisé",
    "epuise",
    "out of stock",
    "sold out",
    "unavailable",
)

IN_STOCK_TERMS = (
    "en stock",
    "disponible",
    "available",
    "in stock",
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value: Any) -> str:
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(value: Any) -> List[str]:
    return [token for token in norm(value).split() if len(token) > 1]


def token_set(value: Any) -> set[str]:
    return set(tokens(value))


def _walk_json(value: Any) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def parse_json_ld(soup: BeautifulSoup) -> List[dict]:
    objects: List[dict] = []

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue

        raw = raw.strip()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        objects.extend(obj for obj in _walk_json(data) if isinstance(obj, dict))

    return objects


def product_json_ld(objects: Iterable[dict]) -> List[dict]:
    result = []

    for obj in objects:
        obj_type = obj.get("@type")
        if isinstance(obj_type, list):
            is_product = any(str(item).lower() == "product" for item in obj_type)
        else:
            is_product = str(obj_type or "").lower() == "product"

        if is_product:
            result.append(obj)

    return result


def _same_host(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False

    return host in {"notino.fr", "www.notino.fr"} or host.endswith(".notino.fr")


def normalise_url(href: Any) -> Optional[str]:
    if not href:
        return None

    href = clean(href).replace("\\/", "/").replace("\\u002F", "/")

    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(BASE_URL, href)

    try:
        parsed = urlparse(href)
    except Exception:
        return None

    if parsed.scheme not in {"http", "https"} or not _same_host(href):
        return None

    path = parsed.path.rstrip("/")
    if not path or path == "/":
        return None

    if path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".svg", ".gif")):
        return None

    # Fragments and tracking parameters are irrelevant for product identity.
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def is_cloudflare_challenge(html: str, url: str = "", title: str = "") -> bool:
    """
    Generic challenge detector.

    A challenge page is not a product page and must stop candidate extraction.
    This does not attempt to bypass or solve the challenge.
    """
    haystack = " ".join(
        [
            clean(url).lower(),
            clean(title).lower(),
            clean(html[:250000]).lower(),
        ]
    )

    if "challenges.cloudflare.com" in haystack:
        return True

    marker_hits = sum(
        1 for marker in CHALLENGE_MARKERS
        if marker in haystack
    )

    return marker_hits >= 2


def _is_structural_non_product_path(path: str) -> bool:
    parts = [part.lower() for part in path.strip("/").split("/") if part]

    if not parts:
        return True

    first = parts[0]
    if first in NON_PRODUCT_PATHS:
        return True

    if first in CHALLENGE_PATH_PREFIXES:
        return True

    if any(part in CHALLENGE_PATH_PREFIXES for part in parts[:3]):
        return True

    return False


def looks_product_like_url(url: str) -> bool:
    """
    Generic structural detector.

    It deliberately does NOT require the search query to appear in the URL.
    Notino can use opaque IDs, translated slugs, redirects and canonical URLs.
    The product page is responsible for final identity validation.
    """
    try:
        path = urlparse(url).path.strip("/")
    except Exception:
        return False

    if not path:
        return False

    parts = [part for part in path.split("/") if part]
    if not parts:
        return False

    if _is_structural_non_product_path(path):
        return False

    if re.search(r"/p-\d+$", "/" + path, re.I):
        return True

    # Canonical product URLs normally contain at least a category/slug
    # structure. This is intentionally broad; page validation decides.
    if len(parts) >= 2:
        last = parts[-1].replace("-", " ")
        if len(token_set(last)) >= 2:
            return True

    return False


def discovery_normalise(value: Any) -> str:
    """
    Generic search/discovery normalization.

    Only language variants are collapsed so discovery can compare French/English
    labels. Product validation remains stricter and uses the real product name.
    """
    aliases = {
        "him": "men",
        "his": "men",
        "man": "men",
        "men": "men",
        "homme": "men",
        "hommes": "men",
        "pour": "for",
        "for": "for",
        "her": "women",
        "woman": "women",
        "women": "women",
        "femme": "women",
        "femmes": "women",
        "unisexe": "unisex",
        "unisex": "unisex",
    }
    return " ".join(aliases.get(token, token) for token in tokens(value))


def discovery_matches(text: Any, query: Any) -> bool:
    query_tokens = set(discovery_normalise(query).split())
    if not query_tokens:
        return False

    text_tokens = set(discovery_normalise(text).split())
    return query_tokens.issubset(text_tokens)


def query_tokens(query: str) -> List[str]:
    ignored = {
        "eau",
        "de",
        "parfum",
        "perfume",
        "edp",
        "edt",
        "extrait",
        "spray",
        "ml",
        "for",
        "by",
    }
    return [token for token in tokens(query) if token not in ignored]


def product_identity_matches(name: str, brand: str, query: str) -> bool:
    identity = set(discovery_normalise(f"{name} {brand}").split())
    wanted = {
        token
        for token in discovery_normalise(query).split()
        if token not in {
            "eau", "de", "parfum", "perfume", "edp", "edt",
            "extrait", "spray", "ml", "for", "by",
        }
    }

    if not identity or not wanted:
        return False

    return wanted.issubset(identity)


def parse_size(*values: Any) -> Optional[float]:
    text = " ".join(clean(value) for value in values if value not in (None, ""))
    match = SIZE_RE.search(text)

    if not match:
        return None

    number = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        number *= 10

    return int(number) if number.is_integer() else number


def requested_size(query: str) -> Optional[float]:
    return parse_size(query)


def parse_price(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        return round(number, 2) if number > 0 else None

    text = clean(value)
    match = PRICE_RE.search(text)

    if match:
        raw = match.group(1).replace(" ", "").replace("\u00a0", "")
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
    except ValueError:
        return None

    return round(number, 2) if number > 0 else None


def extract_prices(text: str) -> List[float]:
    values = []

    for match in PRICE_RE.finditer(clean(text)):
        value = parse_price(match.group(0))
        if value is not None:
            values.append(value)

    return values


def extract_concentration(*values: Any) -> Optional[str]:
    text = norm(" ".join(clean(value) for value in values if value))

    rules = (
        ("Eau de Toilette", r"\beau de toilette\b|\bedt\b"),
        ("Eau de Parfum", r"\beau de parfum\b|\bedp\b"),
        ("Eau de Cologne", r"\beau de cologne\b|\bedc\b"),
        ("Extrait de Parfum", r"\bextrait(?: de parfum)?\b"),
        ("Parfum", r"\bparfum\b"),
    )

    for label, pattern in rules:
        if re.search(pattern, text, re.I):
            return label

    return None


def extract_gender(*values: Any) -> str:
    text = norm(" ".join(clean(value) for value in values if value))

    if re.search(r"\b(men|male|homme|pour homme|hommes)\b", text):
        return "men"

    if re.search(r"\b(women|female|femme|pour femme|femmes)\b", text):
        return "women"

    if re.search(r"\b(unisex|unisexe|mixte)\b", text):
        return "unisex"

    return "unknown"


def extract_name(soup: BeautifulSoup, data: Optional[dict] = None) -> str:
    if isinstance(data, dict):
        value = clean(data.get("name"))
        if value:
            return value

    for selector in (
        "h1",
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
    ):
        node = soup.select_one(selector)
        if not node:
            continue

        value = (
            node.get("content")
            if node.name == "meta"
            else node.get_text(" ", strip=True)
        )
        value = clean(value)

        if value:
            return value

    if soup.title:
        return clean(soup.title.get_text(" ", strip=True))

    return ""


def extract_brand(data: Optional[dict]) -> str:
    if not isinstance(data, dict):
        return ""

    brand = data.get("brand")

    if isinstance(brand, dict):
        brand = brand.get("name")

    return clean(brand)


def extract_image(soup: BeautifulSoup, data: Optional[dict], page_url: str) -> Optional[str]:
    image = data.get("image") if isinstance(data, dict) else None

    if isinstance(image, list):
        image = next((item for item in image if item), None)

    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")

    image = clean(image)

    if not image:
        node = soup.select_one(
            'meta[property="og:image"], meta[name="twitter:image"]'
        )
        if node:
            image = clean(node.get("content"))

    if not image:
        return None

    return urljoin(page_url, image)


def _offer_list(data: Optional[dict]) -> List[dict]:
    if not isinstance(data, dict):
        return []

    offers = data.get("offers")

    if isinstance(offers, dict):
        return [offers]

    if isinstance(offers, list):
        return [item for item in offers if isinstance(item, dict)]

    return []


def extract_offer_price(soup: BeautifulSoup, data: Optional[dict]) -> Optional[float]:
    for offer in _offer_list(data):
        for key in ("price", "lowPrice", "highPrice"):
            value = parse_price(offer.get(key))
            if value is not None:
                return value

    for selector in (
        'meta[itemprop="price"]',
        'meta[property="product:price:amount"]',
        "[data-price]",
    ):
        for node in soup.select(selector):
            value = (
                node.get("content")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )
            parsed = parse_price(value)
            if parsed is not None:
                return parsed

    prices = extract_prices(soup.get_text(" ", strip=True))
    return prices[0] if prices else None


def extract_availability(soup: BeautifulSoup, data: Optional[dict]) -> str:
    for offer in _offer_list(data):
        raw = (
            offer.get("availability")
            or offer.get("availabilityStatus")
            or offer.get("stock")
        )
        text = norm(raw)

        if not text:
            continue

        if any(term in text for term in (
            "instock",
            "in stock",
            "available",
            "disponible",
            "en stock",
        )):
            return "in_stock"

        if any(term in text for term in (
            "outofstock",
            "out of stock",
            "soldout",
            "sold out",
            "unavailable",
            "not available",
            "indisponible",
            "rupture",
            "epuise",
        )):
            return "out_of_stock"

    for node in soup.select(
        '[itemprop="availability"], '
        'meta[property="product:availability"], '
        'meta[name="availability"]'
    ):
        raw = node.get("content") or node.get_text(" ", strip=True)
        text = norm(raw)

        if any(term in text for term in IN_STOCK_TERMS):
            return "in_stock"

        if any(term in text for term in OUT_OF_STOCK_TERMS):
            return "out_of_stock"

    # Use visible product-page text only as a final generic fallback.
    # It is never used during candidate discovery.
    text = norm(soup.get_text(" ", strip=True))

    if any(term in text for term in OUT_OF_STOCK_TERMS):
        return "out_of_stock"

    if any(term in text for term in IN_STOCK_TERMS):
        return "in_stock"

    return "unknown"


def _canonical_url(soup: BeautifulSoup, current_url: str) -> str:
    node = soup.select_one('link[rel="canonical"]')
    if node and node.get("href"):
        value = normalise_url(node.get("href"))
        if value:
            return value

    return normalise_url(current_url) or current_url


def _extract_product_id(url: str) -> Optional[str]:
    match = re.search(r"/p-(\d+)(?:/|$)", url, re.I)
    return match.group(1) if match else None


def parse_product_html(
    url: str,
    html: str,
    query: str,
    candidate_context: str = "",
) -> Optional[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    objects = parse_json_ld(soup)
    products = product_json_ld(objects)

    data = products[0] if products else {}
    name = extract_name(soup, data)
    brand = extract_brand(data)

    # If multiple Product objects exist, use the one whose identity matches.
    if products:
        for candidate in products:
            candidate_name = clean(candidate.get("name"))
            candidate_brand = extract_brand(candidate)
            if product_identity_matches(candidate_name, candidate_brand, query):
                data = candidate
                name = candidate_name
                brand = candidate_brand
                break

    if not name:
        return None

    # The product page is authoritative for product identity, but search
    # engines can express generic query intent in the result-card context
    # rather than repeating every query token in the product H1/JSON-LD.
    # Use the candidate context only as corroborating discovery evidence.
    #
    # This keeps specific product searches strict: when the result-card
    # context does not support the query and the product identity does not
    # support it either, the candidate is rejected.
    page_identity_match = product_identity_matches(
        name,
        brand,
        query,
    )
    discovery_context_match = discovery_matches(
        candidate_context,
        query,
    )

    if not page_identity_match and not discovery_context_match:
        return None

    size = parse_size(
        name,
        data.get("name") if isinstance(data, dict) else "",
    )

    wanted_size = requested_size(query)
    if wanted_size is not None and size is not None:
        if float(wanted_size) != float(size):
            return None

    concentration_value = extract_concentration(name)
    gender_value = extract_gender(name)

    product_url = _canonical_url(soup, url)
    price = extract_offer_price(soup, data)
    availability = extract_availability(soup, data)
    image = extract_image(soup, data, product_url)

    gtin = clean(
        data.get("gtin13")
        or data.get("gtin")
        or data.get("gtin8")
        or data.get("isbn")
    ) or None

    sku = clean(data.get("sku")) or None
    mpn = clean(data.get("mpn")) or None
    product_id = _extract_product_id(product_url)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand or None,
            "url": product_url,
            "image": image,
        },
        "identity": {
            "gtin": {
                "value": gtin,
                "source": "jsonld",
            } if gtin else None,
            "mpn": {
                "value": mpn,
                "source": "jsonld",
            } if mpn else None,
            "sku": {
                "value": sku,
                "source": "jsonld",
            } if sku else None,
            "store_product_id": {
                "value": product_id or sku,
                "source": "notino_product_url_or_sku",
            } if (product_id or sku) else None,
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {
                "value": size,
                "source": "product_name",
            } if size is not None else None,
            "concentration": {
                "value": concentration_value,
                "source": "product_name",
            } if concentration_value else None,
            "gender": {
                "value": gender_value,
                "source": "product_name",
            },
            "packaging_type": {
                "value": "product",
                "source": "default",
            },
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": availability,
        },
        "provenance": {
            "source_page": product_url,
            "product_source": "notino_product_page",
            "name_source": "h1_or_jsonld",
            "brand_source": "jsonld",
            "price_source": "jsonld_meta_or_visible_price",
        },
        "raw_data": {
            "jsonld": data,
        },
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €" if price is not None else "",
        "url": product_url,
        "image": image,
        "available": availability == "in_stock",
    }


def _card_context(anchor) -> str:
    pieces = [
        anchor.get_text(" ", strip=True),
        anchor.get("aria-label"),
        anchor.get("title"),
    ]

    image = anchor.find("img")
    if image:
        pieces.extend([
            image.get("alt"),
            image.get("title"),
        ])

    node = anchor
    for _ in range(5):
        node = getattr(node, "parent", None)
        if node is None:
            break

        text = clean(node.get_text(" ", strip=True))
        if len(text) >= 30:
            pieces.append(text)
            break

    return clean(" ".join(str(piece or "") for piece in pieces))


def extract_candidates_from_html(html: str, page_url: str, query: str) -> List[Dict[str, Any]]:
    """
    Generic candidate extraction.

    Important: discovery never rejects a structurally plausible product URL
    merely because its URL slug does not contain the query. Query relevance is
    only a ranking signal here; the product page performs the authoritative
    validation.
    """
    soup = BeautifulSoup(html, "html.parser")

    if is_cloudflare_challenge(html, page_url):
        return []

    candidates: Dict[str, Dict[str, Any]] = {}

    def add(raw_url: Any, context: str = "", source: str = "dom") -> None:
        url = normalise_url(raw_url)
        if not url or not looks_product_like_url(url):
            return

        entry = candidates.get(url)
        if entry is None:
            entry = {
                "url": url,
                "context": "",
                "sources": set(),
            }
            candidates[url] = entry

        entry["context"] = clean(
            " ".join(
                value
                for value in (entry.get("context"), context)
                if value
            )
        )
        entry["sources"].add(source)

    # Visible DOM links are the primary discovery source.
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        context = _card_context(anchor)
        add(href, context, "dom")

    # Generic data attributes used by client-rendered product cards.
    for node in soup.find_all(True):
        context = clean(node.get_text(" ", strip=True))
        for attribute in (
            "data-href",
            "data-url",
            "data-product-url",
            "data-link",
            "data-product-link",
        ):
            add(node.get(attribute), context, "data")

    # Structured data can expose item URLs even when the visible anchor is
    # generated only after hydration.
    for obj in _walk_json(_parse_all_json_scripts(soup)):
        if not isinstance(obj, dict):
            continue

        context = clean(obj.get("name"))

        for key in ("url", "@id"):
            value = obj.get(key)
            if isinstance(value, str):
                add(value, context, "jsonld")

        item = obj.get("item")
        if isinstance(item, dict):
            item_context = clean(item.get("name"))
            for key in ("url", "@id"):
                value = item.get(key)
                if isinstance(value, str):
                    add(value, item_context, "jsonld")

    # Embedded state often contains URLs escaped as JSON strings.
    decoded = (
        html
        .replace("\\/", "/")
        .replace("\\u002F", "/")
    )

    patterns = (
        r'(?:https?:)?//(?:www\.)?notino\.fr/[^"\'<>\s\\]+',
        r'(?P<path>/[a-z0-9][^"\'<>\s\\]*)',
    )

    for pattern in patterns:
        for match in re.finditer(pattern, decoded, re.I):
            raw = match.group("path") if "path" in match.groupdict() else match.group(0)
            add(raw, "", "embedded")

    query_rank = discovery_normalise(query)

    ranked = []
    for entry in candidates.values():
        context = entry["context"]
        exact = discovery_matches(context, query)
        partial = sum(
            1
            for token in discovery_normalise(query).split()
            if token in discovery_normalise(context).split()
        )

        source_bonus = len(entry["sources"])
        url_bonus = 2 if re.search(r"/p-\d+$", entry["url"], re.I) else 0

        ranked.append(
            (
                0 if exact else 1,
                -partial,
                -source_bonus,
                -url_bonus,
                -len(query_rank),
                entry["url"],
                entry,
            )
        )

    ranked.sort(key=lambda item: item[:-1])
    return [item[-1] for item in ranked[:MAX_CANDIDATES]]


def _parse_all_json_scripts(soup: BeautifulSoup) -> List[Any]:
    values: List[Any] = []

    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        if not raw:
            continue

        text = raw.strip()
        if not text:
            continue

        if not (
            text.startswith("{")
            or text.startswith("[")
        ):
            continue

        try:
            values.append(json.loads(text))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    return values


def _browser_context():
    if sync_playwright is None or not BROWSER_ENABLED:
        return None

    playwright = sync_playwright().start()

    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ],
    )

    context = browser.new_context(
        user_agent=HEADERS["User-Agent"],
        locale="fr-FR",
        extra_http_headers={
            "Accept-Language": HEADERS["Accept-Language"],
        },
        viewport={
            "width": 1365,
            "height": 900,
        },
        ignore_https_errors=True,
    )

    return playwright, browser, context


def _wait_search_page(page) -> None:
    try:
        page.wait_for_load_state(
            "domcontentloaded",
            timeout=BROWSER_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        pass

    # Hydration and product cards can appear after DOMContentLoaded.
    try:
        page.wait_for_selector(
            "a[href]",
            timeout=min(BROWSER_TIMEOUT_MS, 10000),
            state="attached",
        )
    except PlaywrightTimeoutError:
        pass

    # Give client rendering a bounded window without requiring networkidle.
    page.wait_for_timeout(1200)


def _browser_discover_resources(
    query: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Optional[Tuple[Any, Any, Any]]]:
    """
    Open the search page and keep the same browser context alive.

    Cookies/session state established by the search page are therefore reused
    when product pages are opened.
    """
    report = {
        "enabled": BROWSER_ENABLED,
        "available": sync_playwright is not None,
        "status": None,
        "final_url": None,
        "html_bytes": 0,
        "candidate_count": 0,
        "challenge_detected": False,
        "attempts": 0,
        "error": None,
    }

    if sync_playwright is None or not BROWSER_ENABLED:
        report["error"] = "playwright_unavailable"
        return [], report, None

    resources = None

    try:
        resources = _browser_context()
        if resources is None:
            report["error"] = "browser_context_unavailable"
            return [], report, None

        playwright, browser, context = resources

        search_url = SEARCH_URL.format(query=quote_plus(query))
        candidates: List[Dict[str, Any]] = []

        # A small bounded retry is useful for transient challenge responses.
        # It does not attempt to solve or circumvent the challenge.
        for attempt in range(1, 3):
            report["attempts"] = attempt
            page = context.new_page()

            try:
                response = page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=BROWSER_TIMEOUT_MS,
                )

                if response is not None:
                    report["status"] = response.status

                report["final_url"] = page.url
                _wait_search_page(page)

                html = page.content()
                report["html_bytes"] = len(html.encode("utf-8"))

                title = ""
                try:
                    title = page.title()
                except Exception:
                    pass

                challenge = is_cloudflare_challenge(
                    html,
                    page.url,
                    title,
                )

                report["challenge_detected"] = challenge

                if challenge:
                    LOGGER.info(
                        "Notino search returned a Cloudflare challenge on attempt %s",
                        attempt,
                    )
                    try:
                        page.close()
                    except Exception:
                        pass

                    if attempt < 2:
                        # Give a transient challenge/cookie response a bounded
                        # opportunity to clear before the next normal request.
                        try:
                            context.new_page().close()
                        except Exception:
                            pass
                        continue

                    return [], report, resources

                # Trigger lazy loading without depending on networkidle.
                for _ in range(4):
                    try:
                        page.evaluate(
                            "window.scrollBy(0, Math.max(700, window.innerHeight * 0.9));"
                        )
                    except Exception:
                        break
                    page.wait_for_timeout(450)

                html = page.content()
                report["html_bytes"] = len(html.encode("utf-8"))

                candidates = extract_candidates_from_html(
                    html,
                    page.url,
                    query,
                )
                report["candidate_count"] = len(candidates)

                try:
                    page.close()
                except Exception:
                    pass

                return candidates, report, resources

            except Exception as exc:
                report["error"] = f"{type(exc).__name__}: {exc}"
                try:
                    page.close()
                except Exception:
                    pass
                if attempt >= 2:
                    raise

        return candidates, report, resources

    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        LOGGER.warning("Notino browser discovery failed: %s", exc)

        if resources is not None:
            playwright, browser, context = resources
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            try:
                playwright.stop()
            except Exception:
                pass

        return [], report, None


def browser_discover(query: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    candidates, report, resources = _browser_discover_resources(query)

    if resources is not None:
        playwright, browser, context = resources
        try:
            context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
        try:
            playwright.stop()
        except Exception:
            pass

    return candidates, report


def _fetch_product_browser(
    context,
    url: str,
) -> Optional[str]:
    page = context.new_page()

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=PRODUCT_TIMEOUT_MS,
        )

        # A non-2xx navigation response is not sufficient reason to discard
        # the browser DOM. Notino may still have rendered usable content.
        if response is not None and response.status >= 400:
            LOGGER.info(
                "Notino product navigation returned HTTP %s; inspecting DOM",
                response.status,
            )

        try:
            page.wait_for_selector(
                'h1, script[type="application/ld+json"], link[rel="canonical"]',
                timeout=min(PRODUCT_TIMEOUT_MS, 9000),
                state="attached",
            )
        except PlaywrightTimeoutError:
            pass

        page.wait_for_timeout(500)
        return page.content()

    except Exception as exc:
        LOGGER.debug("Notino product browser fetch failed for %s: %s", url, exc)
        return None

    finally:
        try:
            page.close()
        except Exception:
            pass


def _fetch_http(session: requests.Session, url: str) -> Optional[str]:
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code >= 400:
            return None

        if not _same_host(response.url):
            return None

        return response.text

    except requests.RequestException:
        return None


def _candidate_key(url: str) -> str:
    return (normalise_url(url) or url).lower()


def _validate_candidate(
    session: requests.Session,
    browser_context,
    candidate: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    url = candidate["url"]

    html = None

    # Browser-first for Notino product pages because the same anti-bot layer
    # that affects search can affect direct product requests.
    if browser_context is not None:
        html = _fetch_product_browser(browser_context, url)

    if not html:
        html = _fetch_http(session, url)

    if not html:
        return None

    return parse_product_html(
        url,
        html,
        query,
        candidate_context=clean(candidate.get("context", "")),
    )


def _rank_browser_candidates(
    candidates: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    """Rank discovered URLs without making discovery depend on a product name."""
    query_n = discovery_normalise(query)
    query_parts = set(query_n.split())

    ranked = []
    for candidate in candidates:
        context_n = discovery_normalise(candidate.get("context", ""))
        context_parts = set(context_n.split())
        overlap = len(query_parts & context_parts)
        exact = bool(query_parts) and query_parts.issubset(context_parts)
        source_count = len(candidate.get("sources", set()))
        url = candidate.get("url", "")

        ranked.append((
            0 if exact else 1,
            -overlap,
            -source_count,
            url,
            candidate,
        ))

    ranked.sort(key=lambda item: item[:-1])
    return [item[-1] for item in ranked[:MAX_CANDIDATES]]


def _search_internal(
    query: str,
    diagnostic: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Browser-first Notino search.

    Notino commonly protects direct HTTP requests with Cloudflare. Therefore
    the search page and product pages share one Playwright browser context.
    There is deliberately no HTTP discovery fallback here: browser discovery
    is the authoritative path for this scraper.
    """
    session = requests.Session()

    browser_candidates, browser_report, browser_resources = (
        _browser_discover_resources(query)
    )

    candidates = _rank_browser_candidates(browser_candidates, query)

    report = {
        "query": query,
        "search_url": SEARCH_URL.format(query=quote_plus(query)),
        "discovery_mode": "playwright_browser_first",
        "browser_discovery": browser_report,
        "merged_candidates": len(candidates),
        "validated_candidates": 0,
        "accepted_products": 0,
        "rejected_candidates": [],
    }

    if browser_report.get("challenge_detected"):
        report["discovery_blocked_by_challenge"] = True
        report["discovery_block_reason"] = "cloudflare_challenge"

    results: List[Dict[str, Any]] = []
    seen_products = set()
    browser_context = None

    if browser_resources is not None:
        _, _, browser_context = browser_resources

    try:
        for index, candidate in enumerate(candidates[:MAX_PRODUCT_PAGES]):
            report["validated_candidates"] = index + 1

            product = _validate_candidate(
                session,
                browser_context,
                candidate,
                query,
            )

            if product is None:
                if diagnostic and len(report["rejected_candidates"]) < 50:
                    report["rejected_candidates"].append({
                        "rank": index + 1,
                        "url": candidate["url"],
                        "context": candidate.get("context", ""),
                        "sources": sorted(candidate.get("sources", set())),
                        "reason": "product_page_identity_mismatch_or_unavailable",
                    })
                continue

            store_product_id = product["identity"].get("store_product_id")
            if isinstance(store_product_id, dict):
                store_product_id = store_product_id.get("value")

            key = (
                product["url"].lower(),
                norm(product["name"]),
                store_product_id,
            )

            if key in seen_products:
                continue

            seen_products.add(key)
            results.append(product)

        report["accepted_products"] = len(results)
        return results, report

    finally:
        session.close()

        if browser_resources is not None:
            playwright, browser, context = browser_resources
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            try:
                playwright.stop()
            except Exception:
                pass


def search(query: str) -> List[Dict[str, Any]]:
    query = clean(query)
    if not query:
        return []

    try:
        results, _ = _search_internal(query, diagnostic=False)
        return results
    except Exception as exc:
        LOGGER.exception("Notino search failed: %s", exc)
        return []


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)


def diagnose(query: str) -> Dict[str, Any]:
    """
    Full generic discovery diagnostic.

    It reports the complete chain:
    search response -> candidate extraction -> product validation -> results.
    It never assumes or names a particular product.
    """
    query = clean(query)

    if not query:
        return {
            "query": "",
            "error": "empty_query",
        }

    try:
        results, report = _search_internal(query, diagnostic=True)
        report["final_results"] = results

        if report.get("discovery_blocked_by_challenge"):
            report["final_status"] = "blocked_by_cloudflare_challenge"
        elif results:
            report["final_status"] = "products_found"
        else:
            report["final_status"] = "no_valid_products"

        return report
    except Exception as exc:
        LOGGER.exception("Notino diagnostic failed: %s", exc)
        return {
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "final_results": [],
        }


def diagnostic_json(query: str) -> str:
    return json.dumps(
        diagnose(query),
        ensure_ascii=False,
        indent=2,
        default=str,
    )
