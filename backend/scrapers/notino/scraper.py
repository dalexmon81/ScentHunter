from __future__ import annotations

import difflib
import html as html_lib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, unquote, urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
SITEMAP_URL = BASE_URL + "/sitemap.xml"
READER_BASE = "https://r.jina.ai/"

TIMEOUT = 20
READER_TIMEOUT = 12
READER_MAX_WORKERS = 8
PRODUCT_MAX_WORKERS = 8

SCRAPER_VERSION = "notino-FR-generic-discovery-2026-08-26-v28-product-local-stock"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

READER_HEADERS = {
    "User-Agent": "ScentHunter/1.0",
    "Accept": "text/plain,text/markdown,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}

PRODUCT_RE = re.compile(r"/p-\d+(?:/|$)", re.I)

PRODUCT_URL_RE = re.compile(
    r'https?://(?:www\.)?notino\.fr/[^\s)\]>" ]+',
    re.I,
)

READER_ABSOLUTE_PRODUCT_RE = re.compile(
    r"(?:https?:)?(?://|//)(?:www\.)*notino\.fr/[^\s<>)\]\"']+",
    re.I,
)

READER_RELATIVE_PRODUCT_RE = re.compile(
    r"/(?:[a-z0-9][^\s<>)\]\"']*/)+[^\s<>)\]\"']+",
    re.I,
)

PRICE_RE = re.compile(
    r"(?:€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€)",
    re.I,
)

RATING_RE = re.compile(r"\b\d[.,]\d\s*\(\s*\d+\s*\)", re.I)

CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl-",
    "challenge-platform",
    "checking your browser",
    "verify you are human",
    "enable javascript and cookies",
    "vérification de sécurité en cours",
)

IN_STOCK_MARKERS = (
    "en stock",
    "ajouter au panier",
    "add to cart",
)

OUT_STOCK_MARKERS = (
    "en rupture de stock",
    "rupture de stock",
    "actuellement indisponible",
    "produit indisponible",
    "momenteel niet op voorraad",
    "niet op voorraad",
    "tijdelijk niet op voorraad",
    "tijdelijk niet beschikbaar",
    "niet beschikbaar",
    "uitverkocht",
    "niet leverbaar",
)

NON_PERFUME_MARKERS = {
    "gift set",
    "set regalo",
    "set",
    "discovery set",
    "fragrance set",
    "perfume set",
    "parfum set",
    "coffret",
    "bundle",
    "pack",
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
    "cosmetici",
}

SIZE_RE = re.compile(
    r"\b(\d{1,4}(?:[.,]\d{1,2})?)\s*"
    r"(ml|cl|dl|l|oz|fl\s*oz|g|kg)\b",
    re.I,
)


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def _product_norm(value: Any) -> str:
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _has_non_perfume_marker(value: Any) -> bool:
    tokens = set(_product_norm(value).split())
    return any(
        set(_product_norm(marker).split()).issubset(tokens)
        for marker in NON_PERFUME_MARKERS
        if _product_norm(marker)
    )


def _has_non_perfume_marker_in_product(
    name: Any,
    url: Any = "",
    title: Any = "",
) -> bool:
    for value in (name, title):
        if _has_non_perfume_marker(value):
            return True

    try:
        path = unquote(urlparse(str(url or "")).path)
    except Exception:
        path = str(url or "")

    return _has_non_perfume_marker(path)


def _clean(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return re.sub(r"([a-zà-ÿ])([A-ZÀ-Ÿ])", r"\1 \2", text)


def _tokens(value: Any) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", _clean(value).lower())
        if len(token) > 1
    ]


def _query_tokens(value: Any) -> List[str]:
    text = _clean(value)
    text = SIZE_RE.sub(" ", text)
    return _tokens(text)


def _fuzzy_query_match(
    name: Any,
    query: Any,
) -> Tuple[bool, Dict[str, bool], int]:
    """Generic product/query matching used throughout discovery and detail parsing.

    Prefer exact token matches. For tokens not present verbatim, compare against
    the individual candidate token rather than against the longest token in the
    whole product name. This avoids rejecting valid product variants when the
    site normalises, abbreviates, or slightly changes one part of the name.
    """
    name_tokens = set(_query_tokens(name))
    query_tokens = _query_tokens(query)

    if not query_tokens or not name_tokens:
        return False, {}, 0

    hits: Dict[str, bool] = {}
    fuzzy_hits = 0

    for token in query_tokens:
        if token in name_tokens:
            hits[token] = True
            continue

        best = max(
            (
                difflib.SequenceMatcher(None, token, candidate).ratio()
                for candidate in name_tokens
            ),
            default=0.0,
        )
        best_candidate = max(
            name_tokens,
            key=lambda candidate: difflib.SequenceMatcher(
                None, token, candidate
            ).ratio(),
            default="",
        )
        hit = (
            best >= 0.80
            and abs(len(token) - len(best_candidate)) <= 2
        )
        hits[token] = hit
        fuzzy_hits += int(hit)

    return all(hits.values()), hits, fuzzy_hits


def _requested_sizes(value: Any) -> List[Tuple[str, str]]:
    sizes: List[Tuple[str, str]] = []

    for match in SIZE_RE.finditer(_clean(value)):
        number = match.group(1).replace(",", ".")
        unit = re.sub(r"\s+", "", match.group(2).lower())
        sizes.append((number, unit))

    return sizes


def _size_matches(text: Any, size: Tuple[str, str]) -> bool:
    number, unit = size

    number_pattern = re.escape(number).replace(r"\.", r"[.,]")
    unit_pattern = re.escape(unit).replace("floz", r"fl\s*oz")

    pattern = re.compile(
        rf"\b{number_pattern}\s*{unit_pattern}\b",
        re.I,
    )

    return bool(pattern.search(_clean(text)))


def _contains_requested_size(text: Any, query: Any) -> bool:
    requested = _requested_sizes(query)

    if not requested:
        return True

    return any(_size_matches(text, size) for size in requested)


def _matches(text: Any, query: Any) -> bool:
    text = _clean(text).lower()
    tokens = _query_tokens(query)
    return bool(tokens) and all(token in text for token in tokens)


def _format_price(value: Any) -> str:
    match = re.search(
        r"(\d{1,4}(?:[.,]\d{1,2})?)",
        _clean(value),
    )

    if not match:
        return ""

    try:
        number = float(match.group(1).replace(",", "."))
    except ValueError:
        return ""

    return f"{number:.2f}".replace(".", ",") + "€" if number > 0 else ""


def _extract_price(text: Any) -> str:
    matches = list(PRICE_RE.finditer(_clean(text)))

    if not matches:
        return ""

    match = matches[-1]
    return _format_price(match.group(1) or match.group(2))


def _extract_product_price(text: Any) -> str:
    content = _clean(text)

    if not content:
        return ""

    current_matches = list(
        re.finditer(
            r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€",
            content,
            flags=re.I,
        )
    )

    for current in reversed(current_matches):
        after = content[current.end():current.end() + 30].lower()
        if not re.match(r"\s*/\s*100\s*(?:ml|g)", after):
            return _format_price(current.group(1))

    sized_prices = re.findall(
        r"\b\d{1,4}(?:[.,]\d{1,2})?\s*"
        r"(?:ml|cl|dl|l|oz|fl\s*oz|g|kg)\s+"
        r"(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€",
        content,
        flags=re.I,
    )

    if sized_prices:
        return _format_price(sized_prices[-1])

    price_before_size = re.findall(
        r"(?:€\s*)?(\d{1,4}[.,]\d{2})\s*€?\s+"
        r"\d{1,4}(?:[.,]\d{1,2})?\s*"
        r"(?:ml|cl|dl|l|oz|fl\s*oz|g|kg)\b",
        content,
        flags=re.I,
    )

    if price_before_size:
        return _format_price(price_before_size[-1])

    valid: List[str] = []

    for match in PRICE_RE.finditer(content):
        tail = content[match.end():match.end() + 30].lower()

        if re.match(r"\s*/\s*100\s*(?:ml|g)", tail):
            continue

        valid.append(match.group(1) or match.group(2))

    if valid:
        return _format_price(valid[-1])

    return ""


def availability_value(value: Any) -> Optional[bool]:
    """Normalize a Notino availability value to True/False/None.

    True  = in stock / available
    False = explicitly out of stock / unavailable
    None  = neutral, preorder, backorder, limited or unknown
    """
    if isinstance(value, bool):
        return value

    if value is None:
        return None

    low = _clean(str(value)).lower()

    if not low:
        return None

    out_markers = (
        "outofstock",
        "out of stock",
        "soldout",
        "sold out",
        "discontinued",
        "rupture de stock",
        "en rupture",
        "actuellement indisponible",
        "produit indisponible",
        "indisponible",
        "non disponible",
        "pas en stock",
        "épuisé",
        "epuise",
    )

    in_markers = (
        "instock",
        "in stock",
        "en stock",
        "ajouter au panier",
        "add to cart",
    )

    neutral_markers = (
        "limitedavailability",
        "limited availability",
        "preorder",
        "pre-order",
        "backorder",
        "back-order",
    )

    if any(marker in low for marker in out_markers):
        return False

    if any(marker in low for marker in neutral_markers):
        return None

    if any(marker in low for marker in in_markers):
        return True

    return None


def notino_stock_is_verified(value: Any) -> bool:
    normalized = availability_value(value)

    print(
        "NOTINO stock:",
        repr(value),
        type(value).__name__,
        "=>",
        normalized,
    )

    return normalized is True


def _structured_offer_stock_status(
    text: str,
    product_name: str = "",
    product_url: str = "",
) -> Optional[bool]:
    """Return True=in stock, False=out of stock, None=unknown.

    Only Product JSON-LD that identifies the same product as the requested
    page is considered. This prevents a related/recommended product embedded
    elsewhere in the page from supplying its price or stock state.
    """
    raw = html_lib.unescape(str(text or ""))
    if not raw.strip():
        return None

    target_name = _product_norm(product_name)
    target_url = str(product_url or "").lower().rstrip("/")
    target_slug = (
        _product_norm(_name_from_product_url(product_url))
        if product_url
        else ""
    )

    def identity_matches(item: Dict[str, Any]) -> bool:
        item_name = _product_norm(item.get("name"))
        item_url = str(
            item.get("url") or item.get("@id") or ""
        ).lower().rstrip("/")
        item_slug = (
            _product_norm(_name_from_product_url(item_url))
            if item_url else ""
        )

        if target_url and item_url and item_url == target_url:
            return True
        if target_slug and item_slug and (
            item_slug == target_slug
            or target_slug in item_slug
            or item_slug in target_slug
        ):
            return True
        if target_name and item_name and (
            item_name == target_name
            or target_name in item_name
            or item_name in target_name
        ):
            return True
        return False

    def walk(data: Any) -> Optional[bool]:
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            item_type = item.get("@type", "")
            types = item_type if isinstance(item_type, list) else [item_type]

            if any(str(value).lower() == "product" for value in types):
                if identity_matches(item):
                    offers = item.get("offers")
                    if isinstance(offers, dict):
                        offers = [offers]
                    if isinstance(offers, list):
                        statuses = [
                            availability_value(offer.get("availability"))
                            for offer in offers
                            if isinstance(offer, dict)
                        ]
                        statuses = [value for value in statuses if value is not None]
                        if statuses:
                            # An explicit out-of-stock offer must win over any
                            # simultaneous in-stock/legacy offer for the same
                            # product. This is generic and prevents stale or
                            # parallel JSON-LD offers from marking an unavailable
                            # product as available.
                            if any(value is True for value in statuses):
                                return True
                            if any(value is False for value in statuses):
                                return False

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
        return None

    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
        r"(.*?)</script>",
        raw,
        flags=re.I | re.S,
    )

    for block in blocks:
        try:
            data = json.loads(block)
        except (TypeError, ValueError):
            continue
        result = walk(data)
        if result is not None:
            return result

    return None

def _stock_status(
    text: str,
    product_name: str = "",
    product_url: str = "",
) -> Optional[bool]:
    raw = html_lib.unescape(str(text or ""))

    if not raw.strip():
        return None

    # First trust structured availability only when it belongs to the exact
    # requested product. Never scan the whole page for an out-of-stock marker:
    # Notino pages contain recommendation, bundle and footer content that can
    # mention another unavailable product.
    structured = _structured_offer_stock_status(
        raw,
        product_name,
        product_url,
    )

    if structured is not None:
        return structured

    status_text = raw
    if "<" in raw and ">" in raw:
        try:
            status_text = BeautifulSoup(
                raw,
                "html.parser",
            ).get_text("\n", strip=True)
        except Exception:
            status_text = raw

    lines = [
        _clean(line)
        for line in status_text.splitlines()
        if _clean(line)
    ]

    name_tokens = set(_query_tokens(product_name))
    status_hits: List[Tuple[int, int, bool]] = []

    for index, line in enumerate(lines):
        if len(line) > 320:
            continue

        low = line.lower()
        out_markers_found = [
            marker
            for marker in OUT_STOCK_MARKERS
            if marker in low
        ]
        in_markers_found = [
            marker
            for marker in IN_STOCK_MARKERS
            if marker in low
        ]

        # "pas en stock" contains the generic in-stock marker "en stock".
        # Treat explicit negative availability as out of stock first.
        if "pas en stock" in low or "non disponible" in low:
            out_markers_found.append("pas en stock" if "pas en stock" in low else "non disponible")
            in_markers_found = []

        if not (out_markers_found or in_markers_found):
            continue

        # Keep the status evidence tightly local to the product. A wider
        # window can accidentally associate a recommendation's stock label
        # with the requested product.
        window = " ".join(
            lines[max(0, index - 1):min(len(lines), index + 2)]
        )
        window_tokens = set(_query_tokens(window))

        relevance = 0

        if name_tokens:
            matched_name_tokens = sum(
                1
                for token in name_tokens
                if token in window_tokens
            )

            if matched_name_tokens >= min(3, len(name_tokens)):
                relevance = 4
            elif matched_name_tokens >= min(2, len(name_tokens)):
                relevance = 3
            elif matched_name_tokens >= 1 and len(name_tokens) <= 2:
                relevance = 2

        nearby = " ".join(
            lines[max(0, index - 2):index + 1]
        ).lower()

        if re.search(
            r"(?:prix actuel|\b\d{1,4}[.,]\d{2}\s*€)",
            nearby,
            re.I,
        ):
            relevance = max(
                relevance,
                2 if name_tokens else 1,
            )

        # Normalize the actual marker, not the whole line. A full line can
        # contain several products, positive and negative phrases, or unrelated
        # text; passing the whole line to availability_value() can therefore
        # create a false positive/negative. Negative evidence has priority.
        if out_markers_found:
            matched_marker = out_markers_found[0]
        else:
            matched_marker = in_markers_found[0]

        status_value = availability_value(matched_marker)

        if status_value is None:
            continue

        if relevance:
            status_hits.append(
                (relevance, -index, status_value)
            )

    if status_hits:
        if any(hit[2] is False for hit in status_hits):
            return False
        if any(hit[2] is True for hit in status_hits):
            return True

    return None


def _stock_status_diagnostic(
    text: str,
    product_name: str = "",
    product_url: str = "",
) -> Dict[str, Any]:
    """Return detailed stock evidence without changing normal acceptance logic."""
    raw = html_lib.unescape(str(text or ""))

    evidence: Dict[str, Any] = {
        "product_name": product_name or "",
        "product_url": product_url or "",
        "structured_stock": None,
        "stock_status": None,
        "status_hits": [],
        "selected_hit": None,
        "rejection_reason": None,
    }

    if not raw.strip():
        evidence["rejection_reason"] = "empty_stock_input"
        return evidence

    structured = _structured_offer_stock_status(
        raw,
        product_name,
        product_url,
    )
    evidence["structured_stock"] = structured

    if structured is not None:
        evidence["stock_status"] = structured
        evidence["rejection_reason"] = (
            "structured_out_of_stock"
            if structured is False
            else "structured_in_stock"
        )
        return evidence

    status_text = raw
    if "<" in raw and ">" in raw:
        try:
            status_text = BeautifulSoup(
                raw,
                "html.parser",
            ).get_text("\n", strip=True)
        except Exception:
            status_text = raw

    lines = [
        _clean(line)
        for line in status_text.splitlines()
        if _clean(line)
    ]

    name_tokens = set(_query_tokens(product_name))
    hits: List[Tuple[int, int, bool]] = []

    for index, line in enumerate(lines):
        if len(line) > 320:
            continue

        low = line.lower()
        out_markers_found = [
            marker
            for marker in OUT_STOCK_MARKERS
            if marker in low
        ]
        in_markers_found = [
            marker
            for marker in IN_STOCK_MARKERS
            if marker in low
        ]

        if "pas en stock" in low or "non disponible" in low:
            out_markers_found.append(
                "pas en stock" if "pas en stock" in low else "non disponible"
            )
            in_markers_found = []

        if not (out_markers_found or in_markers_found):
            continue

        window = " ".join(
            lines[max(0, index - 1):min(len(lines), index + 2)]
        )
        window_tokens = set(_query_tokens(window))

        relevance = 0
        if name_tokens:
            matched_name_tokens = sum(
                1
                for token in name_tokens
                if token in window_tokens
            )

            if matched_name_tokens >= min(3, len(name_tokens)):
                relevance = 4
            elif matched_name_tokens >= min(2, len(name_tokens)):
                relevance = 3
            elif matched_name_tokens >= 1 and len(name_tokens) <= 2:
                relevance = 2

        nearby = " ".join(
            lines[max(0, index - 2):index + 1]
        ).lower()

        if re.search(
            r"(?:prix actuel|\b\d{1,4}[.,]\d{2}\s*€)",
            nearby,
            re.I,
        ):
            relevance = max(
                relevance,
                2 if name_tokens else 1,
            )

        marker = (
            out_markers_found[0]
            if out_markers_found
            else in_markers_found[0]
        )
        status_value = availability_value(marker)

        if status_value is None or not relevance:
            continue

        hit = {
            "line_index": index,
            "line": line,
            "marker": marker,
            "status": status_value,
            "relevance": relevance,
            "product_name": product_name or "",
            "product_url": product_url or "",
        }
        evidence["status_hits"].append(hit)
        hits.append((relevance, -index, status_value))

    if hits:
        hits.sort(reverse=True)
        selected = hits[0]
        evidence["stock_status"] = selected[2]
        selected_index = next(
            (
                i
                for i, item in enumerate(evidence["status_hits"])
                if item["relevance"] == selected[0]
                and -item["line_index"] == selected[1]
                and item["status"] is selected[2]
            ),
            None,
        )
        if selected_index is not None:
            evidence["selected_hit"] = evidence["status_hits"][selected_index]
        evidence["rejection_reason"] = (
            "matched_out_of_stock_evidence"
            if selected[2] is False
            else "matched_in_stock_evidence"
        )
    else:
        evidence["rejection_reason"] = "stock_not_verified"

    return evidence



def _stock_debug_details(
    raw_text: str,
    product_name: str = "",
    product_url: str = "",
) -> dict:
    text = _clean(raw_text)
    low = text.lower()

    out_markers = (
        "outofstock",
        "out of stock",
        "soldout",
        "sold out",
        "discontinued",
        "rupture de stock",
        "en rupture",
        "actuellement indisponible",
        "produit indisponible",
        "indisponible",
        "non disponible",
        "pas en stock",
        "épuisé",
        "epuise",
    )

    in_markers = (
        "instock",
        "in stock",
        "en stock",
        "disponible",
        "available",
        "ajouter au panier",
        "add to cart",
    )

    found_out = [marker for marker in out_markers if marker in low]
    found_in = [marker for marker in in_markers if marker in low]

    status = _stock_status(
        text,
        product_name,
        product_url,
    )

    return {
        "stock": status,
        "stock_type": type(status).__name__,
        "out_markers_found": found_out,
        "in_markers_found": found_in,
        "text_length": len(text),
        "product_name": product_name,
        "product_url": product_url,
        "text_excerpt": text[:3000],
    }

def _is_excluded_notino_path(path: str) -> bool:
    low = (path or "").rstrip("/").lower()

    return any(
        low.startswith(prefix)
        for prefix in (
            "/search",
            "/avis/",
            "/erfahrungen/",
            "/magazine/",
            "/blog/",
            "/panier",
            "/cart",
            "/login",
            "/compte",
            "/account",
        )
    )


def _looks_like_product_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.netloc.lower() not in {"www.notino.fr", "notino.fr"}:
        return False

    path = parsed.path.rstrip("/")

    if _is_excluded_notino_path(path):
        return False

    segments = [part for part in path.split("/") if part]

    return len(segments) >= 2


def _normalise_reader_url(raw: Any) -> Optional[str]:
    value = html_lib.unescape(str(raw or "")).strip()
    value = value.replace("\\/", "/").replace("\\u002F", "/")
    value = unquote(value).strip(' <>"\'()[]{}.,;')

    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = urljoin(BASE_URL, value)

    try:
        parsed = urlparse(value)
    except Exception:
        return None

    if parsed.netloc.lower() not in {"www.notino.fr", "notino.fr"}:
        return None

    path = parsed.path

    while (
        path.lower().startswith("/www.notino.fr/")
        or path.lower().startswith("/notino.fr/")
    ):
        path = "/" + path.split("/", 2)[2]

    normalised = (
        f"https://{parsed.netloc.lower()}{path.rstrip('/')}"
    )

    return (
        normalised
        if _looks_like_product_url(normalised)
        else None
    )


def _search_urls(query: str) -> List[str]:
    q = quote_plus(query)

    return [
        f"{SEARCH_URL}?exps={q}",
        f"{BASE_URL}/search?query={q}",
    ]


def _request(
    session: requests.Session,
    url: str,
) -> requests.Response:
    response = session.get(
        url,
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


def _reader_request(
    session: requests.Session,
    url: str,
) -> requests.Response:
    response = session.get(
        READER_BASE + url,
        headers=READER_HEADERS,
        timeout=READER_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


def _is_challenge(text: str) -> bool:
    low = _clean(text).lower()
    return any(
        marker in low
        for marker in CHALLENGE_MARKERS
    )


def _clean_name(text: str) -> str:
    value = RATING_RE.sub(" ", _clean(text))
    value = PRICE_RE.sub(" ", value)

    value = re.sub(
        r"^(?:promo|nouveau|discount|cadeaux? offerts|livraison offerte)\s+",
        "",
        value,
        flags=re.I,
    )

    words = value.split()

    if len(words) >= 4 and len(words) % 2 == 0:
        half = len(words) // 2

        if words[:half] == words[half:]:
            value = " ".join(words[:half])

    return _clean(value)


def _card_text(link: Any) -> str:
    node = link
    best = _clean(link.get_text(" ", strip=True))

    for _ in range(10):
        node = getattr(node, "parent", None)

        if node is None:
            break

        text = _clean(
            node.get_text(" ", strip=True)
        )

        if len(text) > len(best):
            best = text

        if (
            40 <= len(text) <= 1200
            and _extract_price(text)
        ):
            return text

    return best


def _make_candidate(
    url: str,
    anchor: str,
    card: str,
    query: str,
    source: str,
) -> Optional[Dict[str, Any]]:
    url = _clean(url).split("?")[0]

    if not _looks_like_product_url(url):
        return None

    anchor = _clean(anchor)
    card = _clean(card)

    anchor_name = _clean_name(anchor)
    card_name = _clean_name(card)
    url_name = _name_from_product_url(url)
    url_brand = _brand_from_product_url(url)
    url_identity = _clean_name(
        f"{url_brand} {url_name}" if url_brand else url_name
    )

    # Notino does not always put the product name in the clickable anchor.
    # Some result cards expose only generic labels such as "Voir le produit"
    # while the actual product identity is present in the URL slug.  Use the
    # URL as a generic identity fallback instead of discarding the candidate.
    name = anchor_name or card_name or url_identity

    candidates_for_identity = [
        value
        for value in (anchor_name, card_name, url_identity)
        if value
    ]

    if not candidates_for_identity:
        return None

    matched = False
    hits: Dict[str, bool] = {}
    fuzzy_hits = 0
    best_identity = name
    best_identity_score = -1

    for identity_name in candidates_for_identity:
        identity_matched, identity_hits, identity_fuzzy_hits = (
            _fuzzy_query_match(identity_name, query)
        )
        identity_score = (
            sum(identity_hits.values()) * 5
            + identity_fuzzy_hits * 2
            + (5 if identity_matched else 0)
        )

        if identity_score > best_identity_score:
            best_identity_score = identity_score
            best_identity = identity_name
            matched = identity_matched
            hits = identity_hits
            fuzzy_hits = identity_fuzzy_hits

        if identity_matched:
            # Prefer an actual product identity over a generic UI label.
            name = identity_name
            matched = True
            hits = identity_hits
            fuzzy_hits = identity_fuzzy_hits
            break

    if not matched:
        # A URL slug is a valid generic discovery signal, but only when it
        # independently identifies the requested product.
        if url_identity and _url_identity_matches_query(url, query):
            name = url_identity
            matched, hits, fuzzy_hits = _fuzzy_query_match(
                name, query
            )
        else:
            return None

    if _has_non_perfume_marker_in_product(
        name,
        url,
        anchor,
    ):
        return None

    query_tokens = _query_tokens(query)

    if not query_tokens:
        return None

    score = (
        sum(hits.values()) * 5
        + fuzzy_hits * 2
    )

    if matched:
        score += 5

    url_name = _name_from_product_url(url)
    url_matched, _, url_fuzzy_hits = _fuzzy_query_match(
        url_name,
        query,
    )

    if url_matched:
        score += 12
    elif url_name:
        score += url_fuzzy_hits * 2

    search_context = f"{anchor} {card}"
    requested_sizes = _requested_sizes(query)

    if requested_sizes:
        if any(
            _size_matches(search_context, size)
            for size in requested_sizes
        ):
            score += 6
        else:
            score -= 1

    if (
        _extract_price(anchor)
        or _extract_price(card)
    ):
        score += 1

    return {
        "url": url,
        "anchor_text": anchor or name,
        "card_text": card or anchor,
        "name": name,
        "score": score,
        "token_hits": hits,
        "contains_all_query_tokens": matched,
        "requested_size": bool(requested_sizes),
        "size_match_in_search_context": (
            any(
                _size_matches(search_context, size)
                for size in requested_sizes
            )
            if requested_sizes
            else True
        ),
        "source": source,
    }


def extract_candidates_from_html(
    html: str,
    query: str,
) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(
        html or "",
        "html.parser",
    )

    found: Dict[str, Dict[str, Any]] = {}

    for link in soup.find_all(
        "a",
        href=True,
    ):
        url = (
            urljoin(
                BASE_URL,
                _clean(link.get("href")),
            )
            .split("?")[0]
        )

        if not _looks_like_product_url(url):
            continue

        candidate = _make_candidate(
            url,
            _clean(
                link.get_text(
                    " ",
                    strip=True,
                )
            ),
            _card_text(link),
            query,
            "direct-search",
        )

        if candidate and (
            candidate["url"] not in found
            or candidate["score"]
            > found[candidate["url"]]["score"]
        ):
            found[candidate["url"]] = candidate

    return sorted(
        found.values(),
        key=lambda item: (
            not item["contains_all_query_tokens"],
            -item["score"],
            item["url"],
        ),
    )


def _reader_name_from_context(
    context: str,
    query: str,
) -> str:
    raw = (
        html_lib.unescape(context or "")
        .replace("\\/", "/")
    )

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in str(raw).splitlines()
        if line.strip()
    ]

    headings: List[Tuple[int, str]] = []

    for line in lines:
        match = re.match(
            r"^(###|##)\s*(.+)$",
            line,
        )

        if not match:
            continue

        headings.append(
            (
                3 if match.group(1) == "###" else 2,
                _clean_name(
                    match.group(2)
                ).strip(" <>[]()"),
            )
        )

    if not headings:
        return ""

    level, title = headings[-1]

    if not title:
        return ""

    if level == 3:
        for prev_level, brand in reversed(headings[:-1]):
            if prev_level == 3:
                break

            if prev_level == 2 and brand:
                query_tokens = _query_tokens(query)
                brand_tokens = _query_tokens(brand)

                brand_relevant = any(
                    bt in query_tokens
                    or any(
                        difflib.SequenceMatcher(
                            None,
                            bt,
                            qt,
                        ).ratio() >= 0.80
                        and abs(len(bt) - len(qt)) <= 2
                        for qt in query_tokens
                    )
                    for bt in brand_tokens
                )

                combined = _clean_name(
                    f"{brand} {title}"
                )

                if (
                    brand_relevant
                    and _fuzzy_query_match(
                        combined,
                        query,
                    )[0]
                ):
                    return combined

                return (
                    title
                    if _fuzzy_query_match(
                        title,
                        query,
                    )[0]
                    else ""
                )

    return (
        title
        if _fuzzy_query_match(
            title,
            query,
        )[0]
        else ""
    )


def _name_from_product_url(url: str) -> str:
    try:
        path = unquote(
            urlparse(url).path
        ).strip("/")
    except Exception:
        return ""

    parts = [
        part
        for part in path.split("/")
        if part
    ]

    if len(parts) < 2:
        return ""

    slug = (
        parts[-2]
        if parts[-1].startswith("p-")
        else parts[-1]
    )

    slug = re.sub(
        r"-\d{5,}$",
        "",
        slug,
    )

    slug = re.sub(
        r"[-_]+",
        " ",
        slug,
    )

    return _clean_name(slug)


def _url_identity_matches_query(url: str, query: str) -> bool:
    """Validate a product candidate using its URL identity generically."""
    slug = _name_from_product_url(url)
    brand = _brand_from_product_url(url)

    identities = [slug, f"{brand} {slug}".strip()]

    for identity in identities:
        if identity and _fuzzy_query_match(identity, query)[0]:
            return True

    return False


def _brand_from_product_url(url: str) -> str:
    try:
        path = unquote(
            urlparse(url).path
        ).strip("/")
    except Exception:
        return ""

    parts = [
        part
        for part in path.split("/")
        if part
    ]

    return (
        _clean_name(
            parts[0].replace("-", " ")
        )
        if len(parts) >= 2
        else ""
    )


def _display_product_name(
    name: Any,
    url: str = "",
    brand_hint: str = "",
) -> str:
    raw_name = _clean_name(
        str(name or "")
    )

    if not raw_name:
        return ""

    brand = _clean_name(brand_hint)

    if not brand:
        brand = _brand_from_product_url(url)
        brand = (
            brand.title()
            if brand
            else ""
        )

    if not brand:
        return raw_name

    brand = re.sub(
        r"\s*[-–—:]\s*$",
        "",
        brand,
    ).strip()

    if not brand:
        return raw_name

    raw_name = re.sub(
        r"^\s*([^:]+?)\s*[-–—:]\s*",
        r"\1 - ",
        raw_name,
    )

    prefix = re.compile(
        r"^"
        + re.escape(brand)
        + r"(?:\s*[-–—:]\s*|\s+)",
        re.I,
    )

    variant = prefix.sub(
        "",
        raw_name,
        count=1,
    ).strip()

    if (
        not variant
        or variant.casefold()
        == brand.casefold()
    ):
        return brand

    return f"{brand} - {variant}"


def _reader_candidates(
    text: str,
    query: str,
) -> List[Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}

    raw = (
        html_lib.unescape(text or "")
        .replace("\\/", "/")
    )

    lines = [
        line.strip()
        for line in raw.splitlines()
        if line.strip()
    ]

    markdown = re.compile(
        r"\[([^\]]+)\]\(([^)]+)\)",
        re.I,
    )

    for index, line in enumerate(lines):
        for match in markdown.finditer(line):
            anchor = _clean(
                match.group(1)
            )

            url = _normalise_reader_url(
                match.group(2)
            )

            if not url:
                continue

            name = _clean_name(anchor)

            query_tokens = _query_tokens(query)
            name_tokens = set(
                _query_tokens(name)
            )

            needs_heading = (
                not query_tokens
                or not all(
                    token in name_tokens
                    for token in query_tokens
                )
            )

            if needs_heading:
                heading_context = "\n".join(
                    lines[max(0, index - 80):index + 1]
                )

                heading_name = _reader_name_from_context(
                    heading_context,
                    query,
                )

                if heading_name:
                    name = heading_name

            slug_name = _name_from_product_url(url)

            if slug_name and (
                not name
                or not _fuzzy_query_match(
                    name,
                    query,
                )[0]
                or _has_non_perfume_marker(name)
            ):
                name = slug_name

            brand = _brand_from_product_url(url)

            if brand:
                query_tokens = _query_tokens(query)
                brand_tokens = _query_tokens(brand)

                brand_relevant = any(
                    bt in query_tokens
                    or any(
                        difflib.SequenceMatcher(
                            None,
                            bt,
                            qt,
                        ).ratio() >= 0.80
                        and abs(len(bt) - len(qt)) <= 2
                        for qt in query_tokens
                    )
                    for bt in brand_tokens
                )

                branded_name = _clean_name(
                    f"{brand} {slug_name or name}"
                )

                if (
                    brand_relevant
                    and _fuzzy_query_match(
                        branded_name,
                        query,
                    )[0]
                ):
                    name = branded_name

            if (
                not name
                or not _fuzzy_query_match(
                    name,
                    query,
                )[0]
            ):
                continue

            if _has_non_perfume_marker_in_product(
                name,
                url,
                anchor,
            ):
                continue

            candidate = _make_candidate(
                url,
                name,
                anchor or name,
                query,
                "reader-markdown",
            )

            if candidate:
                old_candidate = found.get(url)

                if (
                    old_candidate is None
                    or candidate["score"]
                    > old_candidate["score"]
                ):
                    found[url] = candidate

    def nearby_price_context(
        line_index: int,
        url: str,
    ) -> str:
        slug_tokens = set(
            _query_tokens(
                _name_from_product_url(url)
            )
        )

        query_tokens = set(
            _query_tokens(query)
        )

        best: Optional[
            Tuple[int, int, str]
        ] = None

        start = max(
            0,
            line_index - 5,
        )
        end = min(
            len(lines),
            line_index + 6,
        )

        for candidate_index in range(
            start,
            end,
        ):
            candidate_line = _clean(
                lines[candidate_index]
            )

            if (
                not candidate_line
                or not _extract_price(
                    candidate_line
                )
            ):
                continue

            tokens = set(
                _query_tokens(
                    candidate_line
                )
            )

            slug_hits = sum(
                1
                for token in slug_tokens
                if token in tokens
            )

            query_hits = sum(
                1
                for token in query_tokens
                if token in tokens
            )

            if slug_hits == 0 and query_hits == 0:
                continue

            distance = abs(
                candidate_index - line_index
            )

            score = (
                slug_hits * 10
                + query_hits * 5
                - distance
            )

            candidate = (
                score,
                -distance,
                candidate_line,
            )

            if (
                best is None
                or candidate[:2] > best[:2]
            ):
                best = candidate

        return best[2] if best else ""

    for pattern in (
        PRODUCT_URL_RE,
        READER_ABSOLUTE_PRODUCT_RE,
        READER_RELATIVE_PRODUCT_RE,
    ):
        for match in pattern.finditer(raw):
            url = _normalise_reader_url(
                match.group(0)
            )

            if not url:
                continue

            slug_name = _name_from_product_url(url)

            if not slug_name:
                continue

            name = slug_name
            brand = _brand_from_product_url(url)
            branded_name = (
                _clean_name(
                    f"{brand} {slug_name}"
                )
                if brand
                else ""
            )

            query_tokens = _query_tokens(query)
            brand_tokens = _query_tokens(brand)

            brand_relevant = (
                bool(brand_tokens)
                and any(
                    bt in query_tokens
                    or any(
                        difflib.SequenceMatcher(
                            None,
                            bt,
                            qt,
                        ).ratio() >= 0.80
                        and abs(len(bt) - len(qt)) <= 2
                        for qt in query_tokens
                    )
                    for bt in brand_tokens
                )
            )

            if (
                branded_name
                and brand_relevant
                and _fuzzy_query_match(
                    branded_name,
                    query,
                )[0]
            ):
                name = branded_name

            if _has_non_perfume_marker_in_product(
                name,
                url,
            ):
                continue

            if not _fuzzy_query_match(
                name,
                query,
            )[0]:
                continue

            line_index = 0

            for candidate_index, candidate_line in enumerate(lines):
                if match.group(0) in candidate_line:
                    line_index = candidate_index
                    break

            card_context = nearby_price_context(
                line_index,
                url,
            )

            candidate = _make_candidate(
                url,
                name,
                card_context or name,
                query,
                "reader-url",
            )

            if candidate:
                old_candidate = found.get(url)

                if (
                    old_candidate is None
                    or candidate["score"]
                    > old_candidate["score"]
                ):
                    found[url] = candidate

    return sorted(
        found.values(),
        key=lambda item: (
            not bool(
                item.get(
                    "contains_all_query_tokens"
                )
            ),
            -int(
                item.get("score") or 0
            ),
            item["url"],
        ),
    )


def _candidate_lookup_rank(
    candidate: Dict[str, Any],
    query: str,
) -> Tuple[int, int, int, int, str]:
    url = candidate.get("url", "")
    url_name = _name_from_product_url(url)

    query_name = _clean(query)

    url_norm = _product_norm(url_name)
    query_norm = _product_norm(query_name)

    url_matched, _, url_fuzzy_hits = (
        _fuzzy_query_match(
            url_name,
            query,
        )
    )

    if url_norm == query_norm and query_norm:
        identity_rank = 3
    elif (
        query_norm
        and url_norm.startswith(
            query_norm + " "
        )
    ):
        identity_rank = 2
    elif url_matched:
        identity_rank = 1
    else:
        identity_rank = 0

    return (
        identity_rank,
        1 if bool(
            candidate.get(
                "contains_all_query_tokens"
            )
        ) else 0,
        int(
            candidate.get("score") or 0
        ) + (url_fuzzy_hits * 2),
        1 if url_norm else 0,
        url,
    )


def _candidate_product_identity(
    candidate: Dict[str, Any],
) -> str:
    url = str(
        candidate.get("url") or ""
    )

    brand = _product_norm(
        _brand_from_product_url(url)
    )

    product = _product_norm(
        _name_from_product_url(url)
    )

    if brand or product:
        return f"{brand}|{product}"

    return _product_norm(url)


def _rank_candidates_for_product_lookup(
    candidates: List[Dict[str, Any]],
    limit: int = 8,
    query: str = "",
) -> List[Dict[str, Any]]:
    if not candidates:
        return []

    best_by_identity: Dict[
        str,
        Dict[str, Any],
    ] = {}

    best_rank: Dict[
        str,
        Tuple[int, int, int, int, str],
    ] = {}

    for candidate in candidates:
        identity = _candidate_product_identity(
            candidate
        )

        rank = _candidate_lookup_rank(
            candidate,
            query,
        )

        previous_rank = best_rank.get(
            identity
        )

        if (
            previous_rank is None
            or rank > previous_rank
        ):
            best_by_identity[identity] = candidate
            best_rank[identity] = rank

    ordered = sorted(
        best_by_identity.values(),
        key=lambda item: _candidate_lookup_rank(
            item,
            query,
        ),
        reverse=True,
    )

    return ordered[:limit]


def _parse_sitemap_xml(
    text: str,
) -> Tuple[str, List[str]]:
    try:
        root = ET.fromstring(
            text or ""
        )
    except ET.ParseError:
        return "", []

    root_type = root.tag.rsplit(
        "}",
        1,
    )[-1].lower()

    locs: List[str] = []

    for element in root.iter():
        if (
            element.tag.rsplit(
                "}",
                1,
            )[-1].lower()
            == "loc"
            and element.text
        ):
            locs.append(
                html_lib.unescape(
                    element.text.strip()
                )
            )

    return root_type, locs


def _sitemap_product_urls(
    text: str,
) -> List[str]:
    root_type, locs = _parse_sitemap_xml(
        text
    )

    urls: List[str] = []
    seen = set()

    if root_type == "urlset":
        for value in locs:
            url = _normalise_reader_url(
                value
            )

            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        return urls

    raw = (
        html_lib.unescape(
            str(text or "")
        ).replace("\\/", "/")
    )

    for match in re.finditer(
        r"<loc>\s*(.*?)\s*</loc>",
        raw,
        flags=re.I | re.S,
    ):
        url = _normalise_reader_url(
            match.group(1).strip()
        )

        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


def _sitemap_child_urls(
    text: str,
) -> List[str]:
    root_type, locs = _parse_sitemap_xml(
        text
    )

    if root_type == "sitemapindex":
        return list(
            dict.fromkeys(
                url
                for url in locs
                if url.lower().endswith(".xml")
            )
        )

    raw = (
        html_lib.unescape(
            str(text or "")
        ).replace("\\/", "/")
    )

    output: List[str] = []

    for match in re.finditer(
        r"<loc>\s*(.*?)\s*</loc>",
        raw,
        flags=re.I | re.S,
    ):
        value = match.group(1).strip()

        if (
            value.lower().endswith(".xml")
            and value not in output
        ):
            output.append(value)

    return output


def _candidate_from_sitemap_url(
    url: str,
    query: str,
) -> Optional[Dict[str, Any]]:
    slug_name = _name_from_product_url(url)

    if not slug_name:
        return None

    brand = _brand_from_product_url(url)
    name = slug_name

    branded_name = (
        _clean_name(
            f"{brand} {slug_name}"
        )
        if brand
        else ""
    )

    query_tokens = _query_tokens(query)
    brand_tokens = _query_tokens(brand)

    brand_relevant = (
        bool(brand_tokens)
        and any(
            bt in query_tokens
            or any(
                difflib.SequenceMatcher(
                    None,
                    bt,
                    qt,
                ).ratio() >= 0.80
                and abs(len(bt) - len(qt)) <= 2
                for qt in query_tokens
            )
            for bt in brand_tokens
        )
    )

    if branded_name and brand_relevant:
        name = branded_name

    if _has_non_perfume_marker_in_product(
        name,
        url,
    ):
        return None

    matched, hits, fuzzy_hits = _fuzzy_query_match(
        name,
        query,
    )

    if not matched:
        return None

    score = (
        sum(hits.values()) * 5
        + fuzzy_hits * 2
        + 5
    )

    return {
        "url": url,
        "anchor_text": name,
        "card_text": name,
        "name": name,
        "score": score,
        "token_hits": hits,
        "contains_all_query_tokens": True,
        "requested_size": bool(
            _requested_sizes(query)
        ),
        "size_match_in_search_context": (
            _contains_requested_size(
                name,
                query,
            )
        ),
        "source": "sitemap",
    }


def _sitemap_fetch(
    source_url: str,
) -> Dict[str, Any]:
    session = _new_session()

    try:
        try:
            response = _request(
                session,
                source_url,
            )

            return {
                "url": source_url,
                "status": response.status_code,
                "html": response.text or "",
                "source": "sitemap",
                "error": None,
            }
        except requests.RequestException as direct_error:
            try:
                reader = _reader_request(
                    session,
                    source_url,
                )

                return {
                    "url": source_url,
                    "status": getattr(
                        getattr(
                            direct_error,
                            "response",
                            None,
                        ),
                        "status_code",
                        None,
                    ),
                    "html": reader.text or "",
                    "source": "sitemap-reader",
                    "error": (
                        f"{type(direct_error).__name__}: "
                        f"{direct_error}"
                    ),
                }
            except requests.RequestException as reader_error:
                return {
                    "url": source_url,
                    "status": None,
                    "html": "",
                    "source": "sitemap-reader",
                    "error": (
                        f"{type(reader_error).__name__}: "
                        f"{reader_error}"
                    ),
                }
    finally:
        session.close()


def _sitemap_discovery(
    query: str,
    session: requests.Session,
    max_child_sitemaps: int = 200,
) -> Tuple[
    List[Dict[str, Any]],
    Dict[str, Any],
]:
    pages: List[Dict[str, Any]] = []
    candidates: Dict[str, Dict[str, Any]] = {}

    def consume(
        text: str,
    ) -> None:
        for url in _sitemap_product_urls(
            text
        ):
            candidate = _candidate_from_sitemap_url(
                url,
                query,
            )

            if not candidate:
                continue

            old = candidates.get(url)

            if (
                old is None
                or candidate["score"]
                > old["score"]
            ):
                candidates[url] = candidate

    try:
        root = _sitemap_fetch(
            SITEMAP_URL
        )

        root_text = root.get("html", "")
        consume(root_text)

        pages.append(
            {
                "url": SITEMAP_URL,
                "status": root.get("status"),
                "html_length": len(root_text),
                "source": root.get("source"),
                **(
                    {"error": root["error"]}
                    if root.get("error")
                    else {}
                ),
            }
        )

        child_urls = _sitemap_child_urls(
            root_text
        )[:max_child_sitemaps]

        if child_urls:
            with ThreadPoolExecutor(
                max_workers=min(
                    READER_MAX_WORKERS,
                    len(child_urls),
                )
            ) as executor:
                futures = {
                    executor.submit(
                        _sitemap_fetch,
                        child_url,
                    ): child_url
                    for child_url in child_urls
                }

                child_results: List[
                    Dict[str, Any]
                ] = []

                for future in as_completed(
                    futures
                ):
                    child_results.append(
                        future.result()
                    )

            for item in sorted(
                child_results,
                key=lambda result: (
                    child_urls.index(
                        result["url"]
                    )
                    if result["url"] in child_urls
                    else len(child_urls)
                ),
            ):
                child_text = item.get(
                    "html",
                    "",
                )

                before = len(candidates)

                consume(child_text)

                pages.append(
                    {
                        "url": item["url"],
                        "status": item.get(
                            "status"
                        ),
                        "html_length": len(
                            child_text
                        ),
                        "candidate_count": (
                            len(candidates)
                            - before
                        ),
                        "source": item.get(
                            "source"
                        ),
                        **(
                            {"error": item["error"]}
                            if item.get("error")
                            else {}
                        ),
                    }
                )

    except Exception as exc:
        pages.append(
            {
                "url": SITEMAP_URL,
                "status": None,
                "error": (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                "source": "sitemap",
            }
        )

    return (
        sorted(
            candidates.values(),
            key=lambda item: (
                -item["score"],
                item["url"],
            ),
        ),
        pages,
    )


def _reader_variants(
    query: str,
) -> List[str]:
    query = _clean(query)
    tokens = _query_tokens(query)

    variants: List[str] = []

    for value in (
        query,
        " ".join(reversed(tokens)),
        *tokens,
    ):
        value = _clean(value)

        if value and value not in variants:
            variants.append(value)

    return variants


def _reader_fetch(
    source_url: str,
    variant: str,
) -> Dict[str, Any]:
    session = _new_session()

    try:
        try:
            response = _reader_request(
                session,
                source_url,
            )

            return {
                "source_url": source_url,
                "variant": variant,
                "response_text": response.text or "",
                "status": response.status_code,
                "error": None,
            }
        except requests.RequestException as exc:
            return {
                "source_url": source_url,
                "variant": variant,
                "response_text": "",
                "status": getattr(
                    getattr(
                        exc,
                        "response",
                        None,
                    ),
                    "status_code",
                    None,
                ),
                "error": (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            }
    finally:
        session.close()


def _merge_reader_result(
    item: Dict[str, Any],
    query: str,
    candidates: Dict[str, Dict[str, Any]],
    pages: List[Dict[str, Any]],
) -> None:
    source_url = item["source_url"]
    variant = item["variant"]
    text = item.get(
        "response_text"
    ) or ""

    found = (
        _reader_candidates(
            text,
            query,
        )
        if text
        else []
    )

    for candidate in found:
        old = candidates.get(
            candidate["url"]
        )

        if (
            old is None
            or candidate["score"]
            > old["score"]
        ):
            candidates[
                candidate["url"]
            ] = candidate

    page = {
        "url": source_url,
        "query": variant,
        "reader_url": READER_BASE + source_url,
        "status": item.get("status"),
        "html_length": len(text),
        "candidate_count": len(found),
        "reader": True,
    }

    if item.get("error"):
        page["error"] = item["error"]

    pages.append(page)


def _reader_discovery(
    query: str,
    session: requests.Session,
) -> Tuple[
    List[Dict[str, Any]],
    Dict[str, Any],
]:
    """
    Same discovery channels as the previous version, but all independent
    network calls are executed concurrently. No product-specific URLs,
    names, seeds, or matching rules are introduced.
    """
    query = _clean(query)

    variants = _reader_variants(query)

    candidates: Dict[
        str,
        Dict[str, Any],
    ] = {}

    pages: List[Dict[str, Any]] = []

    search_jobs = [
        (source_url, variant)
        for variant in variants
        for source_url in _search_urls(
            variant
        )
    ]

    if search_jobs:
        with ThreadPoolExecutor(
            max_workers=min(
                READER_MAX_WORKERS,
                len(search_jobs),
            )
        ) as executor:
            futures = [
                executor.submit(
                    _reader_fetch,
                    source_url,
                    variant,
                )
                for source_url, variant in search_jobs
            ]

            reader_results = [
                future.result()
                for future in as_completed(futures)
            ]

        order_map = {
            (
                source_url,
                variant,
            ): index
            for index, (
                source_url,
                variant,
            ) in enumerate(search_jobs)
        }

        reader_results.sort(
            key=lambda item: order_map.get(
                (
                    item["source_url"],
                    item["variant"],
                ),
                len(search_jobs),
            )
        )

        for item in reader_results:
            _merge_reader_result(
                item,
                query,
                candidates,
                pages,
            )

    strong = sorted(
        candidates.values(),
        key=lambda item: (
            not bool(
                item.get(
                    "contains_all_query_tokens"
                )
            ),
            -int(
                item.get("score") or 0
            ),
        ),
    )[:8]

    brand_urls: List[str] = []

    for candidate in strong:
        brand = _brand_from_product_url(
            candidate["url"]
        )

        if not brand:
            continue

        brand_slug = re.sub(
            r"\s+",
            "-",
            brand.lower(),
        )

        brand_url = (
            f"{BASE_URL}/{brand_slug}/"
        )

        if brand_url not in brand_urls:
            brand_urls.append(
                brand_url
            )

    brand_jobs = [
        (
            brand_url,
            (
                "brand:"
                + brand_url.rsplit(
                    "/",
                    2,
                )[-2]
            ),
        )
        for brand_url in brand_urls
    ]

    if brand_jobs:
        with ThreadPoolExecutor(
            max_workers=min(
                READER_MAX_WORKERS,
                len(brand_jobs),
            )
        ) as executor:
            futures = [
                executor.submit(
                    _reader_fetch,
                    source_url,
                    variant,
                )
                for source_url, variant in brand_jobs
            ]

            brand_results = [
                future.result()
                for future in as_completed(futures)
            ]

        order_map = {
            pair: index
            for index, pair in enumerate(
                brand_jobs
            )
        }

        brand_results.sort(
            key=lambda item: order_map.get(
                (
                    item["source_url"],
                    item["variant"],
                ),
                len(brand_jobs),
            )
        )

        for item in brand_results:
            _merge_reader_result(
                item,
                query,
                candidates,
                pages,
            )

    strong = sorted(
        candidates.values(),
        key=lambda item: (
            not bool(
                item.get(
                    "contains_all_query_tokens"
                )
            ),
            -int(
                item.get("score") or 0
            ),
        ),
    )[:8]

    branded_jobs: List[
        Tuple[str, str]
    ] = []

    for candidate in strong:
        brand = _brand_from_product_url(
            candidate["url"]
        )

        if not brand:
            continue

        branded_queries = [
            f"{brand} {query}",
            f"{query} {brand}",
        ]

        for branded_query in branded_queries:
            for search_url in _search_urls(
                branded_query
            ):
                job = (
                    search_url,
                    branded_query,
                )

                if job not in branded_jobs:
                    branded_jobs.append(
                        job
                    )

    if branded_jobs:
        with ThreadPoolExecutor(
            max_workers=min(
                READER_MAX_WORKERS,
                len(branded_jobs),
            )
        ) as executor:
            futures = [
                executor.submit(
                    _reader_fetch,
                    source_url,
                    variant,
                )
                for source_url, variant in branded_jobs
            ]

            branded_results = [
                future.result()
                for future in as_completed(futures)
            ]

        order_map = {
            pair: index
            for index, pair in enumerate(
                branded_jobs
            )
        }

        branded_results.sort(
            key=lambda item: order_map.get(
                (
                    item["source_url"],
                    item["variant"],
                ),
                len(branded_jobs),
            )
        )

        for item in branded_results:
            _merge_reader_result(
                item,
                query,
                candidates,
                pages,
            )

    exact_count = sum(
        1
        for item in candidates.values()
        if item.get(
            "contains_all_query_tokens"
        )
    )

    sitemap_pages: List[
        Dict[str, Any]
    ] = []

    if exact_count < 5:
        sitemap_candidates, sitemap_pages = (
            _sitemap_discovery(
                query,
                session,
                max_child_sitemaps=200,
            )
        )

        for candidate in sitemap_candidates:
            old = candidates.get(
                candidate["url"]
            )

            if (
                old is None
                or candidate["score"]
                > old["score"]
            ):
                candidates[
                    candidate["url"]
                ] = candidate

    pages.extend(
        sitemap_pages
    )

    ordered = sorted(
        candidates.values(),
        key=lambda item: (
            not bool(
                item.get(
                    "contains_all_query_tokens"
                )
            ),
            -int(
                item.get("score") or 0
            ),
            item["url"],
        ),
    )

    return (
        ordered,
        {
            "query": query,
            "discovery_queries": variants,
            "search_urls": _search_urls(
                query
            ),
            "pages": pages,
            "raw_product_urls": len(ordered),
            "candidate_urls": len(ordered),
            "raw_query_token_hits": [
                item
                for item in ordered
                if item[
                    "contains_all_query_tokens"
                ]
            ],
            "fallback": (
                "jina-reader+sitemap-concurrent"
            ),
        },
    )


def _search_http_candidates(
    query: str,
    session: Optional[
        requests.Session
    ] = None,
) -> Tuple[
    List[Dict[str, Any]],
    Dict[str, Any],
]:
    own = session is None

    if own:
        session = _new_session()

    candidates: Dict[
        str,
        Dict[str, Any],
    ] = {}

    pages: List[
        Dict[str, Any]
    ] = []

    try:
        for url in _search_urls(query):
            try:
                response = _request(
                    session,
                    url,
                )
            except requests.RequestException as exc:
                pages.append(
                    {
                        "url": url,
                        "status": getattr(
                            getattr(
                                exc,
                                "response",
                                None,
                            ),
                            "status_code",
                            None,
                        ),
                        "error": (
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        ),
                    }
                )
                continue

            found = extract_candidates_from_html(
                response.text,
                query,
            )

            for candidate in found:
                old = candidates.get(
                    candidate["url"]
                )

                if (
                    old is None
                    or candidate["score"]
                    > old["score"]
                ):
                    candidates[
                        candidate["url"]
                    ] = candidate

            pages.append(
                {
                    "url": url,
                    "final_url": response.url,
                    "status": response.status_code,
                    "html_length": len(
                        response.text or ""
                    ),
                    "candidate_count": len(found),
                    "cloudflare": _is_challenge(
                        response.text
                    ),
                    "source": "direct",
                }
            )

            # Keep both generic Notino search endpoints in the discovery pool.
            # One endpoint can expose a different subset/order of product cards.

        # IMPORTANT: a successful HTTP response is not a successful
        # discovery. Notino can answer with HTTP 200 while the parser
        # extracts zero product candidates. In that case the fallback
        # must run based on the actual candidate list, not on a
        # request_failed flag.
        #
        # Fallback order:
        #   1. direct HTTP search
        #   2. Jina/reader discovery
        #   3. sitemap discovery
        #
        # This remains completely generic: no product-specific names,
        # URLs, seeds, or exceptions are introduced.
        report: Dict[str, Any] = {
            "query": query,
            "direct_pages": pages,
            "direct_candidate_count": len(candidates),
            "fallback_triggered": False,
            "fallback_reason": None,
        }

        if not candidates:
            report["fallback_triggered"] = True
            report["fallback_reason"] = "zero_http_candidates"

            reader_candidates, reader_report = (
                _reader_discovery(
                    query,
                    session,
                )
            )

            for candidate in reader_candidates:
                old = candidates.get(
                    candidate["url"]
                )

                if (
                    old is None
                    or candidate["score"]
                    > old["score"]
                ):
                    candidates[
                        candidate["url"]
                    ] = candidate

            report["reader_discovery"] = reader_report
            report["reader_candidate_count"] = len(
                reader_candidates
            )

        if not candidates:
            report["fallback_reason"] = (
                "zero_http_and_reader_candidates"
            )

            sitemap_candidates, sitemap_pages = (
                _sitemap_discovery(
                    query,
                    session,
                    max_child_sitemaps=200,
                )
            )

            for candidate in sitemap_candidates:
                old = candidates.get(
                    candidate["url"]
                )

                if (
                    old is None
                    or candidate["score"]
                    > old["score"]
                ):
                    candidates[
                        candidate["url"]
                    ] = candidate

            report["sitemap_pages"] = sitemap_pages
            report["sitemap_candidate_count"] = len(
                sitemap_candidates
            )

        ordered = sorted(
            candidates.values(),
            key=lambda item: (
                not item[
                    "contains_all_query_tokens"
                ],
                -item["score"],
                item["url"],
            ),
        )

        report["merged_candidate_count"] = len(
            ordered
        )

        report["fallback"] = (
            "jina-reader+sitemap-if-empty"
        )

        return ordered, report

    finally:
        if own and session is not None:
            session.close()


def _json_ld_products(
    soup: BeautifulSoup,
) -> Iterable[Dict[str, Any]]:
    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        try:
            data = json.loads(
                script.string
                or script.get_text()
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

        stack = (
            data
            if isinstance(data, list)
            else [data]
        )

        while stack:
            item = stack.pop()

            if isinstance(item, list):
                stack.extend(item)

            elif isinstance(item, dict):
                if isinstance(
                    item.get("@graph"),
                    list,
                ):
                    stack.extend(
                        item["@graph"]
                    )

                types = item.get(
                    "@type",
                    [],
                )
                types = (
                    types
                    if isinstance(types, list)
                    else [types]
                )

                if "Product" in types:
                    yield item


def _offer_data(
    offers: Any,
) -> Tuple[str, str]:
    if isinstance(offers, dict):
        offers = [offers]

    if not isinstance(offers, list):
        return "", ""

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        availability = _clean(
            offer.get(
                "availability"
            )
        ).lower()

        if any(
            x in availability
            for x in (
                "outofstock",
                "soldout",
                "discontinued",
            )
        ):
            continue

        price = (
            _format_price(
                offer.get("price")
            )
            or _format_price(
                offer.get("lowPrice")
            )
        )

        if price:
            return price, availability

    return "", ""


def _requested_size_is_valid(
    text: str,
    query: str,
) -> bool:
    requested = _requested_sizes(query)

    if not requested:
        return True

    explicit_sizes = SIZE_RE.findall(
        _clean(text)
    )

    if not explicit_sizes:
        return True

    return any(
        _size_matches(
            text,
            size,
        )
        for size in requested
    )


def _extract_reader_product_name(
    text: str,
    candidate: Dict[str, Any],
    query: str,
) -> str:
    raw = (
        html_lib.unescape(
            str(text or "")
        )
        .replace("\\/", "/")
    )

    candidate_url = candidate.get(
        "url",
        "",
    )

    slug_name = _name_from_product_url(
        candidate_url
    )
    brand = _brand_from_product_url(
        candidate_url
    )

    if slug_name:
        url_name = _clean_name(
            f"{brand} {slug_name}"
            if brand
            else slug_name
        )

        if (
            url_name
            and _fuzzy_query_match(
                url_name,
                query,
            )[0]
            and not _has_non_perfume_marker_in_product(
                url_name,
                candidate_url,
            )
        ):
            return url_name

    lines: List[str] = []

    for raw_line in raw.splitlines():
        line = _clean(
            re.sub(
                r"^#{1,6}\s*",
                "",
                raw_line,
            )
        )

        if not line:
            continue

        if re.match(
            r"^(title|description|image|url|canonical|meta)\s*:",
            line,
            re.I,
        ):
            continue

        lines.append(line)

    for line in lines[:180]:
        if len(line) > 220:
            continue

        if PRICE_RE.search(line):
            continue

        cleaned = _clean_name(line)

        if (
            cleaned
            and _fuzzy_query_match(
                cleaned,
                query,
            )[0]
            and not _has_non_perfume_marker_in_product(
                cleaned,
                candidate_url,
            )
        ):
            return cleaned

    for value in (
        candidate.get("name"),
        candidate.get("anchor_text"),
        candidate.get("card_text"),
    ):
        cleaned = _clean_name(
            value or ""
        )

        if (
            cleaned
            and not cleaned.lower().startswith(
                "title:"
            )
            and _fuzzy_query_match(
                cleaned,
                query,
            )[0]
            and not _has_non_perfume_marker_in_product(
                cleaned,
                candidate_url,
            )
        ):
            return cleaned

    return ""


def _reader_product(
    text: str,
    candidate: Dict[str, Any],
    query: str,
    diagnostics: Optional[List[Dict[str, Any]]] = None,
    reader_status: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    raw = (
        html_lib.unescape(
            str(text or "")
        )
        .replace("\\/", "/")
    )

    content = _clean(raw)

    candidate_url = candidate.get(
        "url",
        "",
    )

    def record_rejection(
        reason: str,
        name_value: str = "",
        final_url: str = "",
        price_value: Any = "",
        stock_value: Any = None,
    ) -> None:
        if diagnostics is None:
            return

        debug = {
            "candidate_url": candidate_url,
            "candidate_name": name_value or candidate.get("name", ""),
            "final_url": final_url or candidate_url,
            "reader_status": reader_status,
            "reader_fallback": True,
            "reader_html_length": len(content or ""),
            "price": price_value,
            "stock": stock_value,
            "stock_type": type(stock_value).__name__,
            "stock_debug": _stock_debug_details(
                content,
                name_value or candidate.get("name", ""),
                final_url or candidate_url,
            ),
            "rejected_reason": reason,
        }
        diagnostics.append(debug)

    if not content:
        record_rejection("reader_content_empty")
        return None

    identity_text = (
        content
        + " "
        + candidate_url
        + " "
        + str(
            candidate.get("name")
            or ""
        )
    )

    if not _fuzzy_query_match(
        identity_text,
        query,
    )[0]:
        record_rejection("query_identity_mismatch")
        return None

    if not _requested_size_is_valid(
        content
        + " "
        + str(
            candidate.get("card_text")
            or ""
        ),
        query,
    ):
        record_rejection("requested_size_invalid")
        return None

    name = _extract_reader_product_name(
        raw,
        candidate,
        query,
    )

    if not name:
        record_rejection("product_name_missing")
        return None

    if _has_non_perfume_marker_in_product(
        name,
        candidate_url,
    ):
        record_rejection("non_perfume_product", name_value=name)
        return None

    if not _fuzzy_query_match(
        name,
        query,
    )[0]:
        record_rejection("product_name_query_mismatch", name_value=name)
        return None

    if not _url_identity_matches_query(
        candidate_url,
        query,
    ):
        record_rejection("url_identity_mismatch", name_value=name)
        return None

    # The resolved product name is authoritative. The discovery URL may point
    # to a redirected or unrelated product and must not override it.

    price = ""

    for price_match in re.finditer(
        r'"(?:price|lowPrice)"\s*:\s*"?(?:'
        r"(\d{1,4}[.,]\d{2})"
        r')',
        raw,
        flags=re.I,
    ):
        possible = _format_price(
            price_match.group(1)
        )

        if possible:
            price = possible
            break

    if not price:
        current_matches = re.findall(
            r"prix\s+actuel\s+(?:de\s+)?"
            r"(\d{1,4}[.,]\d{2})\s*€",
            content,
            flags=re.I,
        )

        if current_matches:
            price = _format_price(
                current_matches[-1]
            )

    if not price:
        price = _extract_product_price(
            content
        )

    if not price:
        lines = [
            _clean(line)
            for line in raw.splitlines()
            if _clean(line)
        ]

        patterns = (
            re.compile(
                r"prix\s+actuel.*?"
                r"(\d{1,4}[.,]\d{2})\s*€",
                re.I,
            ),
            re.compile(
                r"(\d{1,4}[.,]\d{2})\s*€"
                r"(?!\s*/\s*100)",
                re.I,
            ),
            re.compile(
                r"€\s*(\d{1,4}[.,]\d{2})"
                r"(?!\s*/\s*100)",
                re.I,
            ),
        )

        for line in lines:
            if len(line) > 500:
                continue

            for pattern in patterns:
                match = pattern.search(
                    line
                )

                if match:
                    price = _format_price(
                        match.group(1)
                    )

                    if price:
                        break

            if price:
                break

    if not price:
        price = (
            _extract_product_price(
                candidate.get(
                    "anchor_text",
                    "",
                )
            )
            or _extract_product_price(
                candidate.get(
                    "card_text",
                    "",
                )
            )
            or _extract_price(
                candidate.get(
                    "anchor_text",
                    "",
                )
            )
            or _extract_price(
                candidate.get(
                    "card_text",
                    "",
                )
            )
        )

    stock = _stock_status(
        content,
        name,
        candidate_url,
    )

    if not price:
        record_rejection(
            "price_missing",
            name_value=name,
            price_value=price,
            stock_value=stock,
        )
        return None

    if stock is not True:
        record_rejection(
            "stock_not_true",
            name_value=name,
            price_value=price,
            stock_value=stock,
        )
        return None

    return {
        "store": STORE,
        "name": _display_product_name(
            name,
            candidate_url,
        ),
        "price": price,
        "url": candidate_url,
    }


def _card_result(
    candidate: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    anchor = _clean(
        candidate.get(
            "anchor_text"
        )
        or ""
    )

    card = _clean(
        candidate.get(
            "card_text"
        )
        or ""
    )

    url = candidate.get("url", "")

    anchor_name = _clean_name(anchor)
    url_name = _name_from_product_url(url)
    url_brand = _brand_from_product_url(url)
    url_identity = _clean_name(
        f"{url_brand} {url_name}" if url_brand else url_name
    )

    name = anchor_name

    if not name or not _fuzzy_query_match(name, query)[0]:
        name = url_identity

    if not name:
        return None

    if _has_non_perfume_marker_in_product(
        name,
        url,
        anchor,
    ):
        return None

    matched, _, _ = _fuzzy_query_match(
        name,
        query,
    )

    if not matched:
        return None

    # A card is accepted only when the actual product URL also identifies
    # the requested product family. The visible card text alone is not enough
    # because recommendation blocks can contain another product name.
    if not _url_identity_matches_query(
        url,
        query,
    ):
        return None

    context = (
        f"{anchor} {card}"
    )

    if not _requested_size_is_valid(
        context,
        query,
    ):
        return None

    price = (
        _extract_price(anchor)
        or _extract_price(card)
    )

    if not price:
        return None

    # Discovery/card fallback must also respect availability. Product pages
    # are often blocked by Notino (403) or by the reader (429), so the search
    # card can be the only reliable source left. Never return a product whose
    # own card explicitly says it is out of stock. This is intentionally
    # generic and applies to every Notino product.
    stock = _stock_status(
        f"{anchor} {card}",
        name,
        url,
    )

    if not notino_stock_is_verified(stock):
        return None

    return {
        "store": STORE,
        "name": _display_product_name(
            name,
            candidate.get(
                "url",
                "",
            ),
        ),
        "price": price,
        "url": candidate["url"],
    }


def _product_details(
    session: requests.Session,
    candidate: Dict[str, Any],
    query: str,
    diagnostics: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    url = candidate["url"]

    try:
        response = _request(
            session,
            url,
        )
    except requests.RequestException:
        try:
            reader_response = _reader_request(
                session,
                url,
            )

            return (
                _reader_product(
                    reader_response.text,
                    candidate,
                    query,
                    diagnostics=diagnostics,
                    reader_status=reader_response.status_code,
                )
                or _card_result(
                    candidate,
                    query,
                )
            )
        except requests.RequestException:
            return _card_result(
                candidate,
                query,
            )

    final_url = response.url.split("?")[0]

    if _has_non_perfume_marker_in_product(
        candidate.get(
            "name",
            "",
        ),
        final_url,
    ):
        return None

    if (
        _is_challenge(response.text)
        or not _looks_like_product_url(
            final_url
        )
    ):
        try:
            reader_response = _reader_request(
                session,
                url,
            )

            return (
                _reader_product(
                    reader_response.text,
                    candidate,
                    query,
                    diagnostics=diagnostics,
                    reader_status=reader_response.status_code,
                )
                or _card_result(
                    candidate,
                    query,
                )
            )
        except requests.RequestException:
            return _card_result(
                candidate,
                query,
            )

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    page_text = _clean(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    if not _requested_size_is_valid(
        page_text,
        query,
    ):
        return None

    name = ""
    price = ""
    brand = ""

    for product in _json_ld_products(
        soup
    ):
        product_name = _clean(
            product.get("name")
        )

        brand_value = product.get(
            "brand"
        )

        brand_value = (
            _clean(
                brand_value.get(
                    "name"
                )
            )
            if isinstance(
                brand_value,
                dict,
            )
            else _clean(
                brand_value
            )
        )

        product_identity = f"{brand_value} {product_name}"
        identity_matches = (
            _matches(product_identity, query)
            or _fuzzy_query_match(product_identity, query)[0]
        )

        if identity_matches:
            price, _ = _offer_data(
                product.get(
                    "offers"
                )
            )

            if product_name and price:
                name = product_name
                brand = brand_value
                break

    if not name:
        h1 = soup.find("h1")

        if h1 and (
            _matches(
                h1.get_text(
                    " ",
                    strip=True,
                ),
                query,
            )
            or _fuzzy_query_match(
                h1.get_text(" ", strip=True),
                query,
            )[0]
        ):
            name = _clean(
                h1.get_text(
                    " ",
                    strip=True,
                )
            )

    if not name:
        title = soup.find("title")

        if title:
            candidate_name = _clean(
                title.get_text(
                    " ",
                    strip=True,
                )
            ).split("|")[0]

            if (
                _matches(candidate_name, query)
                or _fuzzy_query_match(candidate_name, query)[0]
            ):
                name = candidate_name

    if not name:
        return _card_result(
            candidate,
            query,
        )

    page_title = (
        _clean(
            soup.title.get_text(
                " ",
                strip=True,
            )
        )
        if soup.title
        else ""
    )

    if _has_non_perfume_marker_in_product(
        name,
        final_url,
        page_title,
    ):
        return None

    if not price:
        match = re.search(
            r"prix\s+actuel\s+"
            r"(\d{1,4}[.,]\d{2})\s*€",
            page_text,
            re.I,
        )

        if match:
            price = _format_price(
                match.group(1)
            )

    if not price:
        match = re.search(
            r"en\s+stock\s*[|:]?\s*"
            r"(\d{1,4}[.,]\d{2})\s*€",
            page_text,
            re.I,
        )

        if match:
            price = _format_price(
                match.group(1)
            )

    if not price:
        price = _extract_product_price(
            page_text
        )

    if not price:
        price = (
            _extract_product_price(
                candidate.get(
                    "anchor_text",
                    "",
                )
            )
            or _extract_product_price(
                candidate.get(
                    "card_text",
                    "",
                )
            )
        )

    if not price:
        return None

    stock = _stock_status(
        response.text,
        name,
        final_url,
    )

    if not notino_stock_is_verified(stock):
        return None

    return {
        "store": STORE,
        "name": _display_product_name(
            name,
            final_url,
            brand,
        ),
        "price": price,
        "url": final_url,
    }


def _product_detail_job(
    candidate: Dict[str, Any],
    query: str,
) -> Dict[str, Any]:
    session = _new_session()
    diagnostics: List[Dict[str, Any]] = []

    try:
        try:
            result = _product_details(
                session,
                candidate,
                query,
                diagnostics=diagnostics,
            )

            return {
                "candidate": candidate,
                "result": result,
                "diagnostics": diagnostics,
                "error": None,
            }
        except Exception as exc:
            return {
                "candidate": candidate,
                "result": None,
                "diagnostics": diagnostics,
                "error": (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            }
    finally:
        session.close()


def _parallel_product_details(
    candidates: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    if not candidates:
        return []

    with ThreadPoolExecutor(
        max_workers=min(
            PRODUCT_MAX_WORKERS,
            len(candidates),
        )
    ) as executor:
        futures = {
            executor.submit(
                _product_detail_job,
                candidate,
                query,
            ): index
            for index, candidate in enumerate(
                candidates
            )
        }

        completed: Dict[
            int,
            Dict[str, Any],
        ] = {}

        for future in as_completed(
            futures
        ):
            completed[
                futures[future]
            ] = future.result()

    return [
        completed[index]
        for index in range(
            len(candidates)
        )
    ]


def search(
    query: str,
) -> List[Dict[str, Any]]:
    query = _clean(query)

    if not query:
        return []

    session = _new_session()

    try:
        all_candidates, discovery = _search_http_candidates(
            query,
            session=session,
        )

        # Final caller-level fallback: a successful HTTP discovery can still
        # produce an empty candidate list. Keep the fallback decision tied to
        # the actual candidate list, never to request status alone. This is a
        # generic second chance and introduces no product-specific logic.
        if not all_candidates:
            reader_candidates, reader_report = _reader_discovery(
                query,
                session,
            )
            all_candidates = reader_candidates
            discovery["caller_reader_fallback"] = reader_report
            discovery["caller_reader_fallback_triggered"] = True

        if not all_candidates:
            sitemap_candidates, sitemap_pages = _sitemap_discovery(
                query,
                session,
                max_child_sitemaps=200,
            )
            all_candidates = sitemap_candidates
            discovery["caller_sitemap_fallback"] = sitemap_pages
            discovery["caller_sitemap_fallback_triggered"] = True

        ranked = _rank_candidates_for_product_lookup(
            all_candidates,
            limit=20,
            query=query,
        )

        products = _parallel_product_details(
            ranked,
            query,
        )

        results: List[
            Dict[str, Any]
        ] = []

        seen = set()

        for item in products:
            result = item.get(
                "result"
            )

            if not result:
                continue

            key = (
                result.get("url", "")
                + "|"
                + _clean(
                    result.get(
                        "name"
                    )
                )
            ).lower()

            if key in seen:
                continue

            seen.add(key)
            results.append(result)

            if len(results) >= 20:
                break

        return results

    finally:
        session.close()


def scrape(
    query: str,
) -> List[Dict[str, Any]]:
    return search(query)


def debug_search(
    query: str,
) -> Dict[str, Any]:
    query = _clean(query)

    if not query:
        return {
            "ok": False,
            "store": STORE.lower(),
            "query": "",
            "error": "empty_query",
        }

    session = _new_session()

    try:
        candidates, discovery = _search_http_candidates(
            query,
            session=session,
        )

        # The contract-audit path uses debug_search() as its raw discovery
        # entry point. A successful HTTP response with zero extracted
        # candidates must therefore trigger the same generic fallback chain
        # here as the production search() caller. Do not key this on
        # request_failed/status alone: Notino can return HTTP 200 + zero
        # candidates.
        if not candidates:
            reader_candidates, reader_report = _reader_discovery(
                query,
                session,
            )
            candidates = reader_candidates
            discovery["debug_reader_fallback"] = reader_report
            discovery["debug_reader_fallback_triggered"] = True

        if not candidates:
            sitemap_candidates, sitemap_pages = _sitemap_discovery(
                query,
                session,
                max_child_sitemaps=200,
            )
            candidates = sitemap_candidates
            discovery["debug_sitemap_fallback"] = sitemap_pages
            discovery["debug_sitemap_fallback_triggered"] = True

        ranked = _rank_candidates_for_product_lookup(
            candidates,
            limit=20,
            query=query,
        )

        products = _parallel_product_details(
            ranked,
            query,
        )

        valid = [
            item["result"]
            for item in products
            if item.get("result")
        ]

        return {
            "ok": bool(valid),
            "store": STORE.lower(),
            "query": query,
            "scraper_version": SCRAPER_VERSION,
            "candidate_count": len(
                candidates
            ),
            "ranked_candidate_count": len(
                ranked
            ),
            "result_count": len(valid),
            "candidates": candidates[:50],
            "products": products,
            "discovery": discovery,
        }

    finally:
        session.close()


def _diagnose_product_job(
    candidate: Dict[str, Any],
    query: str,
) -> Dict[str, Any]:
    """Diagnostic-only product check; production acceptance logic is untouched."""
    session = _new_session()
    diagnostic: Dict[str, Any] = {
        "candidate": candidate,
        "query": query,
        "url": candidate.get("url", ""),
        "variant_name": candidate.get("name", ""),
        "decision": "not_evaluated",
    }

    try:
        url = candidate.get("url", "")

        try:
            response = _request(session, url)
        except requests.RequestException as exc:
            diagnostic["request_error"] = f"{type(exc).__name__}: {exc}"
            try:
                reader = _reader_request(session, url)
            except requests.RequestException as reader_exc:
                diagnostic["reader_error"] = f"{type(reader_exc).__name__}: {reader_exc}"
                diagnostic["decision"] = "rejected_no_page_and_no_reader"
                diagnostic["rejection_reason"] = "product_page_unavailable"
                return diagnostic

            reader_text = reader.text or ""
            reader_name = _extract_reader_product_name(
                reader_text,
                candidate,
                query,
            )
            diagnostic["path"] = "reader_fallback"
            diagnostic["http_status"] = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )
            diagnostic["reader_status"] = reader.status_code
            diagnostic["variant_name"] = reader_name or candidate.get("name", "")
            diagnostic["stock"] = _stock_status_diagnostic(
                reader_text,
                diagnostic["variant_name"],
                url,
            )
            diagnostic["decision"] = (
                "accepted_by_reader"
                if _reader_product(reader_text, candidate, query)
                else "rejected_by_reader_pipeline"
            )
            diagnostic["rejection_reason"] = (
                None
                if diagnostic["decision"] == "accepted_by_reader"
                else diagnostic["stock"].get("rejection_reason")
                or "reader_pipeline_rejected"
            )
            return diagnostic

        final_url = response.url.split("?")[0]
        diagnostic["http_status"] = response.status_code
        diagnostic["final_url"] = final_url
        diagnostic["path"] = "normal_product_page"
        diagnostic["challenge"] = _is_challenge(response.text)

        if diagnostic["challenge"] or not _looks_like_product_url(final_url):
            diagnostic["path"] = "reader_after_challenge_or_bad_product_url"
            try:
                reader = _reader_request(session, url)
            except requests.RequestException as exc:
                diagnostic["reader_error"] = f"{type(exc).__name__}: {exc}"
                diagnostic["decision"] = "rejected_reader_request_failed"
                diagnostic["rejection_reason"] = "reader_request_failed"
                return diagnostic

            reader_text = reader.text or ""
            reader_name = _extract_reader_product_name(
                reader_text,
                candidate,
                query,
            )
            diagnostic["variant_name"] = reader_name or candidate.get("name", "")
            diagnostic["reader_status"] = reader.status_code
            diagnostic["stock"] = _stock_status_diagnostic(
                reader_text,
                diagnostic["variant_name"],
                url,
            )
            reader_result = _reader_product(reader_text, candidate, query)
            diagnostic["decision"] = (
                "accepted_by_reader" if reader_result else "rejected_by_reader_pipeline"
            )
            diagnostic["rejection_reason"] = (
                None if reader_result else diagnostic["stock"].get("rejection_reason")
                or "reader_pipeline_rejected"
            )
            return diagnostic

        soup = BeautifulSoup(response.text, "html.parser")
        page_text = _clean(soup.get_text(" ", strip=True))

        name = ""
        brand = ""
        price = ""

        for product in _json_ld_products(soup):
            product_name = _clean(product.get("name"))
            brand_value = product.get("brand")
            brand_value = (
                _clean(brand_value.get("name"))
                if isinstance(brand_value, dict)
                else _clean(brand_value)
            )
            if _matches(f"{brand_value} {product_name}", query):
                possible_price, _ = _offer_data(product.get("offers"))
                if product_name:
                    name = product_name
                    brand = brand_value
                    price = possible_price
                    break

        if not name:
            h1 = soup.find("h1")
            if h1:
                h1_text = _clean(h1.get_text(" ", strip=True))
                if _matches(h1_text, query):
                    name = h1_text

        if not name and soup.title:
            candidate_name = _clean(soup.title.get_text(" ", strip=True)).split("|")[0]
            if _matches(candidate_name, query):
                name = candidate_name

        diagnostic["variant_name"] = name or candidate.get("name", "")
        diagnostic["brand"] = brand
        diagnostic["page_size_valid"] = _requested_size_is_valid(page_text, query)

        if not price:
            price = _extract_product_price(page_text)
        if not price:
            price = (
                _extract_product_price(candidate.get("anchor_text", ""))
                or _extract_product_price(candidate.get("card_text", ""))
            )
        diagnostic["price"] = price

        diagnostic["stock"] = _stock_status_diagnostic(
            response.text,
            diagnostic["variant_name"],
            final_url,
        )

        if not name:
            diagnostic["decision"] = "rejected_no_product_name"
            diagnostic["rejection_reason"] = "product_name_not_found"
        elif not diagnostic["page_size_valid"]:
            diagnostic["decision"] = "rejected_requested_size"
            diagnostic["rejection_reason"] = "requested_size_mismatch"
        elif not _fuzzy_query_match(name, query)[0]:
            diagnostic["decision"] = "rejected_name_mismatch"
            diagnostic["rejection_reason"] = "product_name_query_mismatch"
        elif diagnostic["stock"]["stock_status"] is False:
            diagnostic["decision"] = "rejected_out_of_stock"
            diagnostic["rejection_reason"] = diagnostic["stock"].get("rejection_reason")
        elif diagnostic["stock"]["stock_status"] is None:
            diagnostic["decision"] = "rejected_stock_not_verified"
            diagnostic["rejection_reason"] = "stock_not_verified"
        elif not price:
            diagnostic["decision"] = "rejected_no_price"
            diagnostic["rejection_reason"] = "price_not_found"
        else:
            diagnostic["decision"] = "would_be_accepted"
            diagnostic["rejection_reason"] = None

        return diagnostic

    except Exception as exc:
        diagnostic["decision"] = "diagnostic_exception"
        diagnostic["rejection_reason"] = f"{type(exc).__name__}: {exc}"
        return diagnostic
    finally:
        session.close()


def diagnose(
    query: str,
) -> Dict[str, Any]:
    query = _clean(query)

    if not query:
        return {
            "diagnostic": True,
            "scraper_version": SCRAPER_VERSION,
            "query": query,
            "error": "empty_query",
        }

    session = _new_session()

    try:
        candidates, discovery = _search_http_candidates(
            query,
            session=session,
        )

        candidates_for_product_pages = (
            _rank_candidates_for_product_lookup(
                candidates,
                limit=20,
                query=query,
            )
        )

        discovery[
            "product_page_candidate_limit"
        ] = 20

        discovery[
            "candidate_urls_before_product_page_limit"
        ] = len(candidates)

        if candidates_for_product_pages:
            with ThreadPoolExecutor(
                max_workers=min(
                    PRODUCT_MAX_WORKERS,
                    len(
                        candidates_for_product_pages
                    ),
                )
            ) as executor:
                futures = [
                    executor.submit(
                        _diagnose_product_job,
                        candidate,
                        query,
                    )
                    for candidate
                    in candidates_for_product_pages
                ]

                product_page_results = [
                    future.result()
                    for future in as_completed(
                        futures
                    )
                ]

            order_map = {
                item["url"]: index
                for index, item
                in enumerate(
                    candidates_for_product_pages
                )
            }

            product_page_results.sort(
                key=lambda item: order_map.get(
                    item["url"],
                    len(
                        candidates_for_product_pages
                    ),
                )
            )
        else:
            product_page_results = []

        return {
            "diagnostic": True,
            "scraper_version": SCRAPER_VERSION,
            "query": query,
            "search_url": _search_urls(
                query
            )[0],
            "discovery": discovery,
            "candidate_count": len(candidates),
            "candidates": candidates[:25],
            "product_pages": product_page_results,
        }

    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument(
        "--diagnose",
        action="store_true",
    )
    args = parser.parse_args()

    output = (
        diagnose(args.query)
        if args.diagnose
        else search(args.query)
    )

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )
