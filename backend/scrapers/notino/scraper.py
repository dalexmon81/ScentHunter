from __future__ import annotations

import json
import logging
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
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
SEARCH_URL = BASE_URL + "/search.asp?exps={query}"

TIMEOUT = int(os.getenv("NOTINO_TIMEOUT_S", "12"))
BROWSER_TIMEOUT_MS = int(os.getenv("NOTINO_BROWSER_TIMEOUT_MS", "22000"))
PRODUCT_TIMEOUT_MS = int(os.getenv("NOTINO_PRODUCT_TIMEOUT_MS", "16000"))

BROWSER_ENABLED = (
    os.getenv("NOTINO_BROWSER", "1").strip().lower()
    not in {"0", "false", "no", "off"}
)

MAX_CANDIDATES = int(os.getenv("NOTINO_MAX_CANDIDATES", "16"))
MAX_RESULTS = int(os.getenv("NOTINO_MAX_RESULTS", "12"))

LOGGER = logging.getLogger(__name__)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
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
    r"((?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.]\d{1,2})?)"
    r"\s*(?:€|EUR)(?!\w)",
    re.I,
)

SIZE_RE = re.compile(
    r"(?<!\d)"
    r"(\d{1,4}(?:[.,]\d{1,2})?)"
    r"\s*"
    r"(ml|cl|dl|l|oz|fl\.?\s*oz)"
    r"\b",
    re.I,
)

PRODUCT_RE = re.compile(
    r"/p-(\d+)(?:/|$)",
    re.I,
)

PRODUCT_URL_RE = re.compile(
    r"https?://(?:www\.)?notino\.fr/[^\s<>\"'\]\[()]+",
    re.I,
)

IN_STOCK_TERMS = (
    "en stock",
    "disponible",
    "available",
    "in stock",
    "ajouter au panier",
    "ajouter au panier",
)

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


GENERIC_QUERY_WORDS = {
    "pour",
    "femme",
    "femmes",
    "homme",
    "hommes",
    "for",
    "the",
    "and",
    "avec",
    "de",
    "du",
    "des",
    "la",
    "le",
    "les",
    "un",
    "une",
    "par",
    "eau",
    "edp",
    "edt",
    "parfum",
    "parfums",
    "perfume",
    "perfumes",
    "woman",
    "women",
    "man",
    "men",
    "unisex",
    "unisexe",
    "extrait",
    "spray",
    "vaporisateur",
    "eau-de-parfum",
    "eau-de-toilette",
}


NON_PERFUME_MARKERS = {
    "gift set",
    "set regalo",
    "discovery set",
    "fragrance set",
    "perfume set",
    "coffret",
    "bundle",
    "travel set",
    "kit",
    "duo",
    "trio",
    "mystery box",
    "tester",
    "testeur",
    "sample",
    "shampoo",
    "shower gel",
    "body wash",
    "body lotion",
    "body cream",
    "body milk",
    "deodorant",
    "deo spray",
    "aftershave",
    "after shave",
    "body spray",
    "hair mist",
    "makeup",
    "cosmetics",
    "cosmetic",
    "skincare",
    "skin care",
}


def clean(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\\/", "/")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def norm(value: Any) -> str:
    text = clean(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(value: Any) -> List[str]:
    return re.findall(r"[a-z0-9]+", clean(value).lower())


def token_set(value: Any) -> set[str]:
    return {x for x in tokens(value) if len(x) > 1}


def query_identity_tokens(query: str) -> List[str]:
    result: List[str] = []

    for token in tokens(query):
        if token in GENERIC_QUERY_WORDS:
            continue

        if token not in result:
            result.append(token)

    return result


def query_matches_name(name: str, query: str) -> bool:
    name_tokens = token_set(name)
    required = query_identity_tokens(query)

    if not name_tokens or not required:
        return False

    if not all(token in name_tokens for token in required):
        return False

    q = norm(query)
    n = norm(name)

    if not q or not n:
        return False

    q_words = q.split()
    n_words = n.split()

    if len(q_words) <= len(n_words):
        sequence_found = False

        for index in range(
            0,
            len(n_words) - len(q_words) + 1,
        ):
            if n_words[index:index + len(q_words)] == q_words:
                sequence_found = True
                break

        if not sequence_found:
            # A strict sequence is preferred, but for retailer titles
            # containing the brand in front we allow token matching.
            if not all(word in n_words for word in q_words):
                return False

    gender_patterns = (
        (
            r"\b(?:pour|for)\s+(?:femme|femmes|woman|women)\b",
            r"\b(?:pour|for)\s+(?:femme|femmes|woman|women)\b",
        ),
        (
            r"\b(?:pour|for)\s+(?:homme|hommes|man|men)\b",
            r"\b(?:pour|for)\s+(?:homme|hommes|man|men)\b",
        ),
    )

    for query_pattern, name_pattern in gender_patterns:
        if re.search(query_pattern, q):
            if not re.search(name_pattern, n):
                return False

    if re.search(r"\b(?:unisex|unisexe)\b", q):
        if not re.search(r"\b(?:unisex|unisexe)\b", n):
            return False

    return True


def requested_sizes(query: str) -> List[Tuple[str, str]]:
    result = []

    for match in SIZE_RE.finditer(clean(query)):
        number = match.group(1).replace(",", ".")
        unit = re.sub(r"\s+", "", match.group(2).lower())
        result.append((number, unit))

    return result


def size_matches(text: str, size: Tuple[str, str]) -> bool:
    number, unit = size

    number_pattern = re.escape(number).replace(
        r"\.",
        r"[.,]",
    )

    unit_pattern = re.escape(unit)

    pattern = re.compile(
        rf"\b{number_pattern}\s*{unit_pattern}\b",
        re.I,
    )

    return bool(pattern.search(clean(text)))


def requested_size_ok(text: str, query: str) -> bool:
    sizes = requested_sizes(query)

    if not sizes:
        return True

    return any(
        size_matches(text, requested)
        for requested in sizes
    )


def looks_like_non_perfume(value: Any) -> bool:
    text = norm(value)

    for marker in NON_PERFUME_MARKERS:
        if norm(marker) in text:
            return True

    return False


def parse_price(value: Any) -> Optional[float]:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            number = float(value)
            return round(number, 2) if number > 0 else None
        except Exception:
            return None

    text = clean(value)

    if not text:
        return None

    match = PRICE_RE.search(text)

    if match:
        raw = match.group(1).replace(" ", "")
    else:
        bare = re.fullmatch(
            r"\d+(?:[.,]\d{1,2})?",
            text,
        )

        if not bare:
            return None

        raw = bare.group(0)

    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")

    try:
        number = float(raw)

        if number <= 0:
            return None

        return round(number, 2)

    except Exception:
        return None


def extract_prices(text: Any) -> List[float]:
    values: List[float] = []

    for match in PRICE_RE.finditer(clean(text)):
        value = parse_price(match.group(0))

        if value is not None:
            values.append(value)

    return values


def extract_size(text: Any) -> Optional[float]:
    match = SIZE_RE.search(clean(text))

    if not match:
        return None

    try:
        value = float(
            match.group(1).replace(",", ".")
        )
    except Exception:
        return None

    unit = re.sub(
        r"\s+",
        "",
        match.group(2).lower(),
    )

    if unit == "cl":
        value *= 10
    elif unit == "dl":
        value *= 100
    elif unit == "l":
        value *= 1000

    if unit not in {"ml", "cl", "dl", "l"}:
        return None

    return value


def extract_concentration(text: Any) -> str:
    low = clean(text).lower()

    if (
        "eau de parfum" in low
        or "eau-de-parfum" in low
        or re.search(r"\bedp\b", low)
    ):
        return "Eau de Parfum"

    if (
        "eau de toilette" in low
        or "eau-de-toilette" in low
        or re.search(r"\bedt\b", low)
    ):
        return "Eau de Toilette"

    if (
        "extrait de parfum" in low
        or "parfum extrait" in low
        or re.search(r"\bextrait\b", low)
    ):
        return "Extrait"

    if re.search(r"\bparfum\b", low):
        return "Parfum"

    return ""


def extract_gender(text: Any) -> str:
    low = clean(text).lower()

    if re.search(
        r"\b(?:pour|for)\s+(?:femme|femmes|woman|women)\b",
        low,
    ):
        return "female"

    if re.search(
        r"\b(?:pour|for)\s+(?:homme|hommes|man|men)\b",
        low,
    ):
        return "male"

    if "unisex" in low or "unisexe" in low:
        return "unisex"

    return ""


def availability_from_text(text: Any) -> str:
    low = clean(text).lower()

    if any(term in low for term in OUT_OF_STOCK_TERMS):
        return "out_of_stock"

    if any(term in low for term in IN_STOCK_TERMS):
        return "in_stock"

    return "unknown"


def availability_from_jsonld(
    data: Dict[str, Any],
) -> str:
    offers = data.get("offers")

    if isinstance(offers, dict):
        offers = [offers]

    if not isinstance(offers, list):
        return "unknown"

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        raw = (
            offer.get("availability")
            or offer.get("availabilityStatus")
            or offer.get("stock")
            or ""
        )

        low = norm(raw)

        if any(
            marker in low
            for marker in (
                "instock",
                "in stock",
                "available",
                "disponible",
                "en stock",
            )
        ):
            return "in_stock"

        if any(
            marker in low
            for marker in (
                "outofstock",
                "out of stock",
                "soldout",
                "sold out",
                "unavailable",
                "indisponible",
                "rupture",
                "epuise",
            )
        ):
            return "out_of_stock"

    return "unknown"


def normalise_url(href: Any) -> Optional[str]:
    if not href:
        return None

    value = clean(href)

    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = urljoin(BASE_URL, value)

    try:
        parsed = urlparse(value)
    except Exception:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None

    if parsed.netloc.lower() not in {
        "notino.fr",
        "www.notino.fr",
    }:
        return None

    path = parsed.path.rstrip("/")

    if not path:
        return None

    if path.lower().endswith(
        (
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".svg",
            ".gif",
        )
    ):
        return None

    return (
        f"{parsed.scheme}://{parsed.netloc}{path}"
    )


def product_id(url: str) -> Optional[str]:
    match = PRODUCT_RE.search(url or "")

    if not match:
        return None

    return match.group(1)


def looks_like_product_url(
    url: str,
    context: str = "",
    query: str = "",
) -> bool:
    url = normalise_url(url)

    if not url:
        return False

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    path = parsed.path.rstrip("/")

    if not path:
        return False

    low_path = path.lower()

    if "search.asp" in low_path:
        return False

    if PRODUCT_RE.search(path):
        return True

    parts = [
        part
        for part in path.split("/")
        if part
    ]

    if len(parts) < 2:
        return False

    exclusions = {
        "search",
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
    }

    if parts[0].lower() in exclusions:
        return False

    combined = (
        clean(context)
        + " "
        + path.replace("/", " ")
    )

    if query and not query_matches_name(
        combined,
        query,
    ):
        # Slug-only URLs are accepted later if their
        # actual product page validates the query.
        if not PRODUCT_RE.search(path):
            return False

    return True


def walk_json(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from walk_json(child)

    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def parse_jsonld(
    soup: BeautifulSoup,
) -> List[Dict[str, Any]]:
    products: List[Dict[str, Any]] = []

    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        raw = (
            script.string
            or script.get_text()
        )

        if not raw:
            continue

        try:
            data = json.loads(raw.strip())
        except Exception:
            continue

        for obj in walk_json(data):
            obj_type = obj.get("@type")

            if isinstance(obj_type, list):
                is_product = "Product" in obj_type
            else:
                is_product = obj_type == "Product"

            if is_product:
                products.append(obj)

    return products


def image_from_jsonld(
    data: Dict[str, Any],
) -> Optional[str]:
    image = data.get("image")

    if isinstance(image, list):
        image = image[0] if image else None

    if isinstance(image, dict):
        image = (
            image.get("url")
            or image.get("contentUrl")
        )

    if not image:
        return None

    return clean(image)


def brand_from_jsonld(
    data: Dict[str, Any],
) -> str:
    brand = data.get("brand")

    if isinstance(brand, dict):
        brand = brand.get("name")

    return clean(brand)


def price_from_jsonld(
    data: Dict[str, Any],
) -> Optional[float]:
    offers = data.get("offers")

    if isinstance(offers, dict):
        offers = [offers]

    if not isinstance(offers, list):
        return None

    candidates = []

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        for key in (
            "price",
            "lowPrice",
            "highPrice",
        ):
            value = offer.get(key)

            if value is not None:
                parsed = parse_price(value)

                if parsed is not None:
                    candidates.append(parsed)

    return candidates[0] if candidates else None


def selected_size(
    soup: BeautifulSoup,
    data: Dict[str, Any],
    name: str,
) -> Optional[float]:
    direct = extract_size(name)

    if direct is not None:
        return direct

    selectors = (
        'input[type="radio"][checked]',
        'input[type="radio"][aria-checked="true"]',
        'input[checked][name*="size" i]',
        'option[selected]',
        '[aria-selected="true"]',
    )

    for selector in selectors:
        for node in soup.select(selector):
            chunks = [
                node.get("value", ""),
                node.get("aria-label", ""),
                node.get("data-value", ""),
                node.get("data-size", ""),
                node.get_text(" ", strip=True),
            ]

            parent = node.parent

            if parent:
                chunks.append(
                    parent.get_text(
                        " ",
                        strip=True,
                    )
                )

            if parent and parent.parent:
                chunks.append(
                    parent.parent.get_text(
                        " ",
                        strip=True,
                    )
                )

            value = extract_size(
                " ".join(chunks)
            )

            if value is not None:
                return value

    return extract_size(
        clean(data.get("name"))
    )


def clean_product_name(value: Any) -> str:
    text = clean(value)

    if not text:
        return ""

    text = re.sub(
        r"\b\d[.,]\d\s*\(\s*\d+\s*\)",
        " ",
        text,
    )

    text = PRICE_RE.sub(" ", text)

    text = re.sub(
        r"\b(?:avec le code|with code)\b.*$",
        " ",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"\b(?:shoppingdays|cadeaux? offerts?|livraison offerte)\b.*$",
        " ",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip(" -|:;,.[]()")

    return text[:240]


def product_item(
    url: str,
    html: str,
    query: str,
) -> Optional[Dict[str, Any]]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    json_products = parse_jsonld(soup)

    h1 = soup.find("h1")

    h1_name = (
        clean_product_name(
            h1.get_text(
                " ",
                strip=True,
            )
        )
        if h1
        else ""
    )

    data: Dict[str, Any] = {}

    for candidate in json_products:
        candidate_name = clean_product_name(
            candidate.get("name")
        )

        if candidate_name and query_matches_name(
            candidate_name,
            query,
        ):
            data = candidate
            break

    json_name = clean_product_name(
        data.get("name")
    )

    name = h1_name or json_name

    if not name:
        name = json_name

    if not name:
        return None

    if not query_matches_name(
        name,
        query,
    ):
        if json_name and query_matches_name(
            json_name,
            query,
        ):
            name = json_name
        else:
            return None

    if looks_like_non_perfume(name):
        return None

    page_text = soup.get_text(
        " ",
        strip=True,
    )

    if not requested_size_ok(
        f"{name} {page_text}",
        query,
    ):
        return None

    price = price_from_jsonld(data)

    if price is None:
        prices = extract_prices(page_text)

        if prices:
            price = prices[0]

    availability = availability_from_jsonld(
        data
    )

    if availability == "unknown":
        availability = availability_from_text(
            page_text
        )

    brand = brand_from_jsonld(data)

    if not brand:
        try:
            parts = [
                p
                for p in urlparse(url).path.split("/")
                if p
            ]

            if parts:
                brand = (
                    parts[0]
                    .replace("-", " ")
                    .title()
                )
        except Exception:
            pass

    sku = clean(
        data.get("sku")
        or ""
    ) or None

    gtin = clean(
        data.get("gtin13")
        or data.get("gtin")
        or ""
    ) or None

    mpn = clean(
        data.get("mpn")
        or ""
    ) or None

    image = image_from_jsonld(data)

    if not image:
        meta_image = soup.select_one(
            'meta[property="og:image"], '
            'meta[name="twitter:image"]'
        )

        if meta_image:
            image = clean(
                meta_image.get("content")
                or ""
            )

    if image:
        image = urljoin(
            url,
            image,
        )

    size = selected_size(
        soup,
        data,
        name,
    )

    concentration = extract_concentration(
        name
    )

    gender = extract_gender(name)

    product_url = (
        normalise_url(url)
        or url
    )

    price_string = ""

    if price is not None:
        price_string = (
            f"{price:.2f}".replace(".", ",")
            + " €"
        )

    return {
        "store": STORE,

        "source": {
            "source_name": name,
            "source_brand": brand,
            "url": product_url,
            "image": image,
        },

        "identity": {
            "gtin": (
                {
                    "value": gtin,
                    "source": "jsonld",
                }
                if gtin
                else None
            ),
            "mpn": (
                {
                    "value": mpn,
                    "source": "jsonld",
                }
                if mpn
                else None
            ),
            "sku": (
                {
                    "value": sku,
                    "source": "jsonld",
                }
                if sku
                else None
            ),
            "store_product_id": (
                {
                    "value": sku,
                    "source": "notino_sku",
                }
                if sku
                else None
            ),
        },

        "attributes": {
            "size_ml": (
                {
                    "value": size,
                    "source": (
                        "selected_variant_or_product_name"
                    ),
                }
                if size is not None
                else None
            ),
            "concentration": (
                {
                    "value": concentration,
                    "source": "product_name",
                }
                if concentration
                else None
            ),
            "gender": (
                {
                    "value": gender,
                    "source": "product_name",
                }
                if gender
                else {
                    "value": "unknown",
                    "source": "not_explicit",
                }
            ),
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
            "product_source": (
                "jsonld_or_page"
            ),
        },

        "raw_data": {
            "jsonld": data,
        },

        "name": name,
        "price": price_string,
        "url": product_url,
        "available": (
            availability == "in_stock"
        ),
    }


def extract_search_card_data(
    soup: BeautifulSoup,
    query: str,
) -> List[Dict[str, Any]]:
    """
    Extract product candidates directly from the
    rendered search page.

    This is intentionally generic. We look for any
    anchor containing a genuine /p-<id>/ URL and use
    its surrounding card text as metadata.
    """

    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = anchor.get("href")

        url = normalise_url(href)

        if not url:
            continue

        if not PRODUCT_RE.search(url):
            continue

        if url in seen:
            continue

        seen.add(url)

        card = anchor

        for _ in range(5):
            if not card.parent:
                break

            parent = card.parent

            text = clean(
                parent.get_text(
                    " ",
                    strip=True,
                )
            )

            if len(text) >= 20:
                card = parent

            else:
                break

        text = clean(
            card.get_text(
                " ",
                strip=True,
            )
        )

        if not text:
            text = clean(
                anchor.get_text(
                    " ",
                    strip=True,
                )
            )

        href_id = product_id(url)

        title = clean_product_name(
            anchor.get_text(
                " ",
                strip=True,
            )
        )

        if not title:
            title_node = card.select_one(
                "h1, h2, h3, h4, "
                "[class*='title' i], "
                "[class*='name' i]"
            )

            if title_node:
                title = clean_product_name(
                    title_node.get_text(
                        " ",
                        strip=True,
                    )
                )

        if not title:
            title = clean_product_name(text)

        if not title:
            continue

        if not query_matches_name(
            title,
            query,
        ):
            # The complete card can contain the actual
            # title even if the anchor text is abbreviated.
            if not query_matches_name(
                text,
                query,
            ):
                continue

        price = None

        prices = extract_prices(text)

        if prices:
            price = prices[0]

        size = extract_size(text)

        candidates.append(
            {
                "url": url,
                "name": title,
                "price": price,
                "size_ml": size,
                "availability": availability_from_text(
                    text
                ),
                "context": text[:1200],
                "product_id": href_id,
            }
        )

        if len(candidates) >= MAX_CANDIDATES:
            break

    return candidates


def candidate_to_item(
    candidate: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    """
    Produce a result from search-card information when
    the product page cannot be fetched.

    The result remains intentionally conservative.
    """

    name = clean_product_name(
        candidate.get("name")
    )

    if not name:
        return None

    if not query_matches_name(
        name,
        query,
    ):
        return None

    if looks_like_non_perfume(name):
        return None

    price = candidate.get("price")

    if isinstance(price, str):
        price = parse_price(price)

    size = candidate.get("size_ml")

    availability = candidate.get(
        "availability"
    ) or "unknown"

    url = normalise_url(
        candidate.get("url")
    )

    if not url:
        return None

    brand = ""

    try:
        parts = [
            p
            for p in urlparse(url).path.split("/")
            if p
        ]

        if parts:
            brand = (
                parts[0]
                .replace("-", " ")
                .title()
            )
    except Exception:
        pass

    concentration = extract_concentration(
        name
    )

    gender = extract_gender(name)

    price_string = ""

    if price is not None:
        price_string = (
            f"{float(price):.2f}".replace(".", ",")
            + " €"
        )

    return {
        "store": STORE,

        "source": {
            "source_name": name,
            "source_brand": brand,
            "url": url,
            "image": None,
        },

        "identity": {
            "gtin": None,
            "mpn": None,
            "sku": (
                {
                    "value": candidate.get(
                        "product_id"
                    ),
                    "source": "url",
                }
                if candidate.get("product_id")
                else None
            ),
            "store_product_id": (
                {
                    "value": candidate.get(
                        "product_id"
                    ),
                    "source": "notino_url",
                }
                if candidate.get("product_id")
                else None
            ),
        },

        "attributes": {
            "size_ml": (
                {
                    "value": size,
                    "source": "search_card",
                }
                if size is not None
                else None
            ),
            "concentration": (
                {
                    "value": concentration,
                    "source": "product_name",
                }
                if concentration
                else None
            ),
            "gender": (
                {
                    "value": gender,
                    "source": "product_name",
                }
                if gender
                else {
                    "value": "unknown",
                    "source": "not_explicit",
                }
            ),
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
            "source_page": url,
            "product_source": "search_card",
        },

        "raw_data": {
            "search_card": candidate,
        },

        "name": name,
        "price": price_string,
        "url": url,
        "available": availability == "in_stock",
    }


def browser_executable_candidates() -> List[str]:
    candidates: List[str] = []

    env_path = os.getenv(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE",
        "",
    ).strip()

    if env_path:
        candidates.append(env_path)

    for command in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):
        path = shutil.which(command)

        if path:
            candidates.append(path)

    common_paths = (
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    )

    candidates.extend(common_paths)

    result = []

    for path in candidates:
        if path and path not in result:
            if os.path.exists(path):
                result.append(path)

    return result


def launch_browser(playwright):
    """
    Prefer Playwright's managed Chromium.

    If Render's environment has a system Chromium, use it
    only as a fallback.
    """

    launch_kwargs = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    }

    try:
        return playwright.chromium.launch(
            **launch_kwargs
        )
    except Exception as first_error:
        LOGGER.warning(
            "Managed Chromium launch failed: %s",
            first_error,
        )

    for executable in browser_executable_candidates():
        try:
            return playwright.chromium.launch(
                executable_path=executable,
                **launch_kwargs,
            )
        except Exception as exc:
            LOGGER.warning(
                "Chromium fallback failed at %s: %s",
                executable,
                exc,
            )

    raise RuntimeError(
        "Unable to launch Chromium. "
        "Playwright managed browser and system "
        "Chromium were unavailable."
    )


def browser_context(browser):
    return browser.new_context(
        locale="fr-FR",
        timezone_id="Europe/Paris",
        viewport={
            "width": 1440,
            "height": 1000,
        },
        user_agent=HEADERS["User-Agent"],
        extra_http_headers={
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
        },
    )


def prepare_page(page) -> None:
    try:
        page.add_init_script(
            """
            Object.defineProperty(
                navigator,
                'webdriver',
                {
                    get: () => undefined
                }
            );
            """
        )
    except Exception:
        pass

    try:
        page.set_default_timeout(
            BROWSER_TIMEOUT_MS
        )
    except Exception:
        pass


def browser_discover(
    query: str,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Render the Notino search page in a real Chromium
    browser and return generic product candidates.
    """

    if not BROWSER_ENABLED:
        return [], "browser_disabled"

    if sync_playwright is None:
        return [], "playwright_not_installed"

    search_url = SEARCH_URL.format(
        query=quote_plus(query)
    )

    with sync_playwright() as playwright:
        browser = None

        try:
            browser = launch_browser(
                playwright
            )

            context = browser_context(
                browser
            )

            page = context.new_page()

            prepare_page(page)

            try:
                response = page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=BROWSER_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                response = None

            status = None

            if response is not None:
                try:
                    status = response.status
                except Exception:
                    status = None

            # Give the client-side result list a short window
            # to populate. We intentionally don't wait for networkidle.
            try:
                page.wait_for_timeout(1800)
            except Exception:
                pass

            html = page.content()

            if not html or len(html) < 500:
                # One reload can recover transient navigation
                # failures without creating a long queue.
                try:
                    page.reload(
                        wait_until="domcontentloaded",
                        timeout=BROWSER_TIMEOUT_MS,
                    )
                    page.wait_for_timeout(1200)
                    html = page.content()
                except Exception:
                    pass

            candidates = extract_search_card_data(
                BeautifulSoup(
                    html or "",
                    "html.parser",
                ),
                query,
            )

            # If the DOM parser did not find candidates, inspect
            # hrefs directly from the browser DOM.
            if not candidates:
                try:
                    links = page.locator(
                        'a[href*="/p-"]'
                    ).evaluate_all(
                        """
                        els => els.map(a => ({
                            href: a.href,
                            text: a.innerText || "",
                            parent: a.parentElement
                                ? a.parentElement.innerText || ""
                                : ""
                        }))
                        """
                    )

                    seen = set()

                    for item in links:
                        href = normalise_url(
                            item.get("href")
                        )

                        if not href:
                            continue

                        if href in seen:
                            continue

                        if not PRODUCT_RE.search(
                            href
                        ):
                            continue

                        seen.add(href)

                        context_text = clean(
                            item.get("parent")
                            or item.get("text")
                            or ""
                        )

                        title = clean_product_name(
                            item.get("text")
                            or ""
                        )

                        if not title:
                            title = clean_product_name(
                                context_text
                            )

                        if not title:
                            continue

                        if not query_matches_name(
                            title,
                            query,
                        ) and not query_matches_name(
                            context_text,
                            query,
                        ):
                            continue

                        prices = extract_prices(
                            context_text
                        )

                        candidates.append(
                            {
                                "url": href,
                                "name": title,
                                "price": (
                                    prices[0]
                                    if prices
                                    else None
                                ),
                                "size_ml": extract_size(
                                    context_text
                                ),
                                "availability": (
                                    availability_from_text(
                                        context_text
                                    )
                                ),
                                "context": (
                                    context_text[:1200]
                                ),
                                "product_id": product_id(
                                    href
                                ),
                            }
                        )

                        if len(candidates) >= MAX_CANDIDATES:
                            break

                except Exception as exc:
                    LOGGER.debug(
                        "Browser DOM extraction failed: %s",
                        exc,
                    )

            try:
                context.close()
            except Exception:
                pass

            if candidates:
                return candidates, None

            if status and status >= 400:
                return [], (
                    f"notino_search_http_{status}"
                )

            return [], "no_product_candidates"

        except Exception as exc:
            LOGGER.warning(
                "Notino browser discovery failed: %s",
                exc,
            )
            return [], (
                f"{type(exc).__name__}: {exc}"
            )

        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


def browser_fetch_product(
    url: str,
) -> Optional[str]:
    if sync_playwright is None:
        return None

    with sync_playwright() as playwright:
        browser = None

        try:
            browser = launch_browser(
                playwright
            )

            context = browser_context(
                browser
            )

            page = context.new_page()

            prepare_page(page)

            try:
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=PRODUCT_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                pass

            try:
                page.wait_for_timeout(900)
            except Exception:
                pass

            html = page.content()

            try:
                context.close()
            except Exception:
                pass

            return html or None

        except Exception as exc:
            LOGGER.warning(
                "Notino browser product retrieval failed: %s",
                exc,
            )
            return None

        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


def http_fetch_product(
    session: requests.Session,
    url: str,
) -> Optional[str]:
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code >= 400:
            return None

        return response.text or None

    except requests.RequestException:
        return None


def fetch_and_parse_product(
    candidate: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    url = normalise_url(
        candidate.get("url")
    )

    if not url:
        return None

    html = browser_fetch_product(url)

    if html:
        item = product_item(
            url,
            html,
            query,
        )

        if item:
            return item

    return candidate_to_item(
        candidate,
        query,
    )


def _search_http_fallback(
    query: str,
) -> List[Dict[str, Any]]:
    """
    Last-resort HTTP path.

    This is intentionally not the primary path because
    Render has historically received HTTP 403 from Notino.
    """

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        search_url = SEARCH_URL.format(
            query=quote_plus(query)
        )

        try:
            response = session.get(
                search_url,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            return []

        if response.status_code >= 400:
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        candidates = extract_search_card_data(
            soup,
            query,
        )

        if not candidates:
            return []

        results: List[Dict[str, Any]] = []

        for candidate in candidates:
            html = http_fetch_product(
                session,
                candidate["url"],
            )

            if html:
                item = product_item(
                    candidate["url"],
                    html,
                    query,
                )

                if item:
                    results.append(item)
                    continue

            fallback = candidate_to_item(
                candidate,
                query,
            )

            if fallback:
                results.append(fallback)

        return results

    finally:
        session.close()


def dedupe_results(
    results: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    seen = set()

    for item in results:
        if not isinstance(item, dict):
            continue

        url = clean(
            item.get("url")
            or item.get("source", {}).get("url")
            or ""
        ).lower()

        sku_obj = (
            item.get("identity", {})
            .get("sku")
        )

        sku = ""

        if isinstance(sku_obj, dict):
            sku = clean(
                sku_obj.get("value")
                or ""
            ).lower()

        key = (
            url,
            sku,
        )

        if key in seen:
            continue

        seen.add(key)
        output.append(item)

    return output


def sort_results(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    def key(item: Dict[str, Any]):
        available = bool(
            item.get("available")
        )

        price = item.get("offer", {}).get(
            "price"
        )

        if not isinstance(price, (int, float)):
            price = 999999.0

        return (
            0 if available else 1,
            price,
            clean(item.get("name")).lower(),
        )

    return sorted(
        results,
        key=key,
    )


def search_stream(
    query: str,
):
    """
    Main streaming entry point used by ScentHunter.

    Discovery happens once. Product pages are then fetched
    independently so the first valid Notino result can be
    yielded immediately.
    """

    query = clean(query)

    if not query:
        return

    candidates, browser_error = browser_discover(
        query
    )

    if not candidates:
        LOGGER.warning(
            "Notino browser discovery returned no "
            "candidates: %s",
            browser_error,
        )

        # Do not immediately launch another expensive
        # browser cycle. Only use HTTP as a last resort.
        fallback_results = _search_http_fallback(
            query
        )

        for item in sort_results(
            dedupe_results(fallback_results)
        )[:MAX_RESULTS]:
            yield item

        return

    # Keep the most relevant candidates first.
    candidates = candidates[
        :MAX_CANDIDATES
    ]

    emitted = set()

    # Small parallelism keeps product requests independent
    # while avoiding an unnecessary browser storm.
    with ThreadPoolExecutor(
        max_workers=min(
            3,
            max(1, len(candidates)),
        )
    ) as executor:

        futures = {
            executor.submit(
                fetch_and_parse_product,
                candidate,
                query,
            ): candidate
            for candidate in candidates
        }

        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception as exc:
                LOGGER.warning(
                    "Notino candidate processing failed: %s",
                    exc,
                )
                continue

            if not item:
                continue

            url = clean(
                item.get("url")
                or ""
            ).lower()

            sku_obj = (
                item.get("identity", {})
                .get("sku")
            )

            sku = ""

            if isinstance(sku_obj, dict):
                sku = clean(
                    sku_obj.get("value")
                    or ""
                ).lower()

            key = (
                url,
                sku,
            )

            if key in emitted:
                continue

            emitted.add(key)

            yield item

            if len(emitted) >= MAX_RESULTS:
                break


def search(
    query: str,
) -> List[Dict[str, Any]]:
    return list(
        search_stream(query)
    )


def scrape(
    query: str,
) -> List[Dict[str, Any]]:
    return search(query)


def diagnose(
    query: str,
) -> Dict[str, Any]:
    query = clean(query)

    candidates, error = browser_discover(
        query
    )

    results = []

    for candidate in candidates:
        item = fetch_and_parse_product(
            candidate,
            query,
        )

        if item:
            results.append(item)

    return {
        "query": query,
        "browser_enabled": BROWSER_ENABLED,
        "candidate_count": len(candidates),
        "result_count": len(results),
        "error": error,
        "candidates": candidates,
        "results": results,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "query",
        nargs="+",
    )

    args = parser.parse_args()

    for query in args.query:
        output = search(query)

        print(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2,
            )
        )
