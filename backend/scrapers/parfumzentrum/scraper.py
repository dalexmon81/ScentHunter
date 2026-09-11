"""
ScentHunter - ParfumZentrum adapter
Fast live search, bounded discovery and parallel product extraction.

Priority:
1. Parfum-Zentrum internal search
2. lightweight product/category result-page parsing
3. sitemap fallback only when search discovery returns nothing

The sitemap is cached in-process so it is NOT downloaded on every user search.
Product pages are fetched in parallel and every product is isolated from the
others. No perfume-specific rules or hardcoded prices are used.
"""

from __future__ import annotations

import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "ParfumZentrum"
BASE_URL = "https://www.parfum-zentrum.de"
SEARCH_URL = BASE_URL + "/suchen/"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

CONNECT_TIMEOUT = 2.0
READ_TIMEOUT = 4.5
PRODUCT_TIMEOUT = (2.0, 4.5)
SITEMAP_TIMEOUT = (2.0, 5.0)

MAX_CANDIDATES = 20
PRODUCT_WORKERS = 8
SITEMAP_TTL = 30 * 60
SITEMAP_MAX_CHILD_MAPS = 100
SITEMAP_WORKERS = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

STOPWORDS = {
    "eau", "de", "the", "for", "and", "spray",
    "ml", "man", "woman", "men", "women",
    "herren", "damen", "unisex", "unisexe",
    "parfum", "parfums", "perfume", "perfumes",
    "duft", "dufte",
}

NON_PERFUME_MARKERS = {
    "geschenkset", "geschenksets", "gift set", "giftset",
    "coffret", "coffrets", "set", "duo", "trio",
    "shampoo", "duschgel", "body lotion", "body cream",
    "körpercreme", "körperlotion", "deodorant", "deostick",
    "deostick", "aftershave", "rasierwasser", "haarspray",
    "hair mist", "makeup", "kosmetik", "creme", "serum",
}

OUT_MARKERS = (
    "nicht lieferbar",
    "nicht vorrätig",
    "ausverkauft",
    "derzeit nicht verfügbar",
    "nicht verfügbar",
    "out of stock",
    "sold out",
    "unavailable",
)

IN_MARKERS = (
    "versandbereit",
    "sofort lieferbar",
    "lieferbar",
    "in den warenkorb",
    "auf lager",
    "in stock",
    "available",
)

_session_local = threading.local()

_sitemap_lock = threading.Lock()
_sitemap_cache = []
_sitemap_cached_at = 0.0


def _session():
    session = getattr(_session_local, "session", None)

    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
        _session_local.session = session

    return session


def _clean(value):
    text = unescape(str(value or ""))
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _norm(value):
    text = _clean(value).casefold()
    text = re.sub(
        r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)",
        " ",
        text,
    )
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value):
    return [
        token
        for token in re.findall(
            r"[a-z0-9äöüß]+",
            _norm(value),
        )
        if len(token) > 1
    ]


def _concentration(value):
    text = _norm(value)

    if (
        "eau de toilette" in text
        or re.search(r"\bedt\b", text)
    ):
        return "Eau de Toilette"

    if (
        "eau de parfum" in text
        or re.search(r"\bedp\b", text)
    ):
        return "Eau de Parfum"

    if (
        "extrait de parfum" in text
        or re.search(r"\bextrait\b", text)
    ):
        return "Extrait de Parfum"

    if re.search(r"\bparfum\b", text):
        return "Parfum"

    return ""


def _size_ml(value):
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)"
        r"\s*(ml|cl|dl|l|oz|fl\.?\s*oz)\b",
        _clean(value),
        re.I,
    )

    if not match:
        return None

    try:
        number = float(
            match.group(1).replace(",", ".")
        )
    except ValueError:
        return None

    unit = re.sub(
        r"\s+",
        "",
        match.group(2).lower(),
    )

    if unit == "cl":
        number *= 10
    elif unit == "dl":
        number *= 100
    elif unit == "l":
        number *= 1000
    elif unit in {"oz", "floz"}:
        number *= 29.5735

    return (
        int(number)
        if number.is_integer()
        else number
    )


def _requested_size(query):
    return _size_ml(query)


def _parse_price(value):
    if value is None:
        return None

    raw = _clean(value)
    raw = raw.replace("€", "")
    raw = raw.replace("EUR", "")
    raw = raw.strip()

    if re.fullmatch(
        r"\d+(?:[.,]\d{1,2})?",
        raw,
    ):
        try:
            number = float(
                raw.replace(",", ".")
            )
            return (
                round(number, 2)
                if 0 < number < 10000
                else None
            )
        except ValueError:
            return None

    # German / European prices:
    # 1.234,56 -> 1234.56
    # 24,95 -> 24.95
    # 1234.56 -> 1234.56
    match = re.search(
        r"\d{1,3}(?:\.\d{3})*,\d{2}"
        r"|\d+(?:,\d{2})"
        r"|\d+(?:\.\d{2})",
        raw,
    )

    if not match:
        return None

    number = match.group(0)

    if "," in number:
        if "." in number:
            number = number.replace(".", "")
        number = number.replace(",", ".")

    try:
        result = float(number)
    except ValueError:
        return None

    return (
        round(result, 2)
        if 0 < result < 10000
        else None
    )


def _availability_from_text(value):
    text = _norm(value)

    # Parfum-Zentrum contains availability-watch/help text on product pages
    # that can include generic phrases such as 'nicht verfügbar'.
    # Purchase-state markers must therefore win over generic page text.
    if any(marker in text for marker in (
        "auf lager",
        "versandbereit",
        "sofort lieferbar",
        "lieferbar",
        "auf lager >",
    )):
        return "in_stock"

    if any(
        marker in text
        for marker in OUT_MARKERS
    ):
        return "out_of_stock"

    if any(
        marker in text
        for marker in IN_MARKERS
    ):
        return "in_stock"

    return "unknown"


def _matches_query(name, query):
    name_norm = _norm(name)
    query_tokens = [
        token
        for token in _tokens(query)
        if token not in STOPWORDS
    ]

    if not name_norm or not query_tokens:
        return False

    name_tokens = set(
        _tokens(name_norm)
    )

    if not all(
        token in name_tokens
        for token in query_tokens
    ):
        return False

    requested_concentration = _concentration(
        query
    )

    if (
        requested_concentration
        and _concentration(name)
        != requested_concentration
    ):
        return False

    requested_size = _requested_size(query)

    if requested_size is not None:
        discovered_size = _size_ml(name)

        if (
            discovered_size is not None
            and abs(
                discovered_size - requested_size
            ) > 0.01
        ):
            return False

    return True


def _looks_like_perfume(name):
    value = f" {_norm(name)} "

    for marker in NON_PERFUME_MARKERS:
        if (
            f" {_norm(marker)} "
            in value
        ):
            return False

    return True


def _product_url(value):
    raw = _clean(value)

    if not raw:
        return ""

    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = urljoin(BASE_URL, raw)
    elif not re.match(
        r"^https?://",
        raw,
        re.I,
    ):
        raw = urljoin(
            BASE_URL + "/",
            raw,
        )

    parsed = urlparse(raw)

    host = parsed.netloc.lower().split(":", 1)[0]

    if host not in {
        "www.parfum-zentrum.de",
        "parfum-zentrum.de",
    }:
        return ""

    path = parsed.path

    # Current product URLs use the generic *_zNNNN format.
    if not re.search(
        r"_z\d+/?$",
        path,
        re.I,
    ):
        return ""

    return parsed._replace(
        netloc="www.parfum-zentrum.de",
        query="",
        fragment="",
    ).geturl()


def _jsonld_objects(soup):
    output = []

    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        queue = [data]

        while queue:
            item = queue.pop(0)

            if isinstance(item, list):
                queue.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            output.append(item)

            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

    return output


def _jsonld_product(soup):
    for item in _jsonld_objects(soup):
        typ = item.get("@type")

        types = (
            typ
            if isinstance(typ, list)
            else [typ]
        )

        if (
            "Product" in types
            or "ProductGroup" in types
        ):
            return item

    return {}


def _jsonld_value(data, *keys):
    for key in keys:
        value = data.get(key)

        if isinstance(value, dict):
            value = (
                value.get("name")
                or value.get("value")
            )

        if (
            value is not None
            and str(value).strip()
        ):
            return _clean(value)

    return None


def _offer_objects(data):
    offers = (
        data.get("offers")
        if isinstance(data, dict)
        else None
    )

    if isinstance(offers, dict):
        return [offers]

    if isinstance(offers, list):
        return [
            offer
            for offer in offers
            if isinstance(offer, dict)
        ]

    return []


def _jsonld_price(data):
    for offer in _offer_objects(data):
        price = _parse_price(
            offer.get("price")
            or offer.get("lowPrice")
        )

        if price is not None:
            return price

    return None


def _jsonld_availability(data):
    for offer in _offer_objects(data):
        value = _norm(
            offer.get("availability")
            or offer.get("itemAvailability")
            or ""
        )

        if (
            "outofstock" in value
            or "soldout" in value
        ):
            return "out_of_stock"

        if (
            "instock" in value
            or "preorder" in value
            or "limitedavailability" in value
        ):
            return "in_stock"

    return None


def _semantic_price(soup):
    selectors = (
        '[itemprop="price"]',
        '[data-price]',
        '[data-product-price]',
        ".product-price",
        ".product_price",
        ".price--current",
        ".price-current",
        ".current-price",
        ".current_price",
        ".final-price",
        ".final_price",
        ".sale-price",
        ".sale_price",
    )

    candidates = []

    for selector in selectors:
        try:
            nodes = soup.select(
                selector
            )
        except Exception:
            nodes = []

        for node in nodes:
            if _bad_price_context(node):
                continue

            price = _node_price(node)

            if price is None:
                continue

            marker = (
                " ".join(
                    node.get("class", [])
                ).lower()
                + " "
                + str(
                    node.get("id", "")
                ).lower()
            )

            score = 0

            if "product" in marker:
                score += 20

            if any(
                word in marker
                for word in (
                    "current",
                    "final",
                    "sale",
                )
            ):
                score += 15

            parent_text = (
                node.parent.get_text(
                    " ",
                    strip=True,
                ).lower()
                if node.parent
                else ""
            )

            if (
                "in den warenkorb"
                in parent_text
            ):
                score += 40

            candidates.append(
                (
                    score,
                    price,
                )
            )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            -item[0],
            item[1],
        )
    )

    return candidates[0][1]


def _node_price(node):
    for attr in (
        "content",
        "data-price",
        "data-product-price",
        "value",
    ):
        if node.has_attr(attr):
            value = _parse_price(
                node.get(attr)
            )

            if value is not None:
                return value

    return _parse_price(
        node.get_text(
            " ",
            strip=True,
        )
    )


def _bad_price_context(node):
    current = node

    for _ in range(8):
        if current is None:
            break

        text = (
            current.get_text(
                " ",
                strip=True,
            ).lower()
        )

        marker = (
            " ".join(
                current.get("class", [])
            ).lower()
            + " "
            + str(
                current.get("id", "")
            ).lower()
        )

        if any(
            word in text
            for word in (
                "grundpreis",
                "pro liter",
                "per liter",
                "€/l",
                "preis inkl. code",
                "preis inkl code",
            )
        ):
            return True

        if any(
            word in marker
            for word in (
                "coupon",
                "voucher",
                "gutschein",
                "rabattcode",
                "discount",
                "recommend",
                "related",
                "cross-sell",
                "upsell",
            )
        ):
            return True

        current = current.parent

    return False


def _is_struck(node):
    if node.find_parent(
        ["del", "s", "strike"]
    ):
        return True

    current = node

    for _ in range(6):
        if current is None:
            break

        marker = (
            " ".join(
                current.get("class", [])
            ).lower()
            + " "
            + str(
                current.get("id", "")
            ).lower()
        )

        if any(
            word in marker
            for word in (
                "old-price",
                "old_price",
                "regular-price",
                "list-price",
                "list_price",
                "strike",
                "strikethrough",
                "was-price",
                "compare-price",
                "crossed",
            )
        ):
            return True

        current = current.parent

    return False


def _extract_price(soup, data):
    """Return the active customer-facing price of the current product.

    The page contains many other product cards and prices (recommendations,
    navigation, related products). A global lowest-price scan is therefore
    unsafe. First anchor extraction to the current product H1 and its
    purchase area; only then use generic visible/structured fallbacks.
    """
    # PRIMARY: extract from the DOM subtree belonging to the current product.
    # This prevents unrelated recommendation prices such as 11,95 EUR from
    # winning simply because they are cheaper.
    h1 = soup.find("h1")
    if h1:
        current = h1
        for distance in range(8):
            current = getattr(current, "parent", None)
            if current is None:
                break

            text = current.get_text(" ", strip=True)
            low = text.lower()
            if "€" not in text:
                continue

            purchase_score = 0
            if "in den warenkorb" in low:
                purchase_score += 300
            if "auf lager" in low or "versandbereit" in low:
                purchase_score += 200
            if "inkl. mwst" in low or "inkl mwst" in low:
                purchase_score += 100

            if purchase_score <= 0:
                continue

            for node in current.find_all(
                ["span", "div", "p", "strong", "b", "ins"]
            ):
                node_text = node.get_text(" ", strip=True)
                if "€" not in node_text:
                    continue

                node_low = node_text.lower()
                if any(term in node_low for term in (
                    "grundpreis", "pro liter", "per liter", "€/l", "/l",
                    "coupon", "gutschein", "rabattcode", "discount-code",
                )):
                    continue
                if _is_struck(node):
                    continue

                matches = re.findall(
                    r"(?<![\d.,])\d{1,4}(?:[.]\d{3})*,\d{2}\s*€"
                    r"|(?<![\d.,])\d+(?:[.,]\d{2})\s*€",
                    node_text,
                    re.I,
                )

                for match in matches:
                    price = _parse_price(match)
                    if price is not None:
                        return price

            # Do not climb into the entire document.
            if distance >= 5:
                break

    # SECONDARY: generic customer-facing visible prices, with context scoring.
    visible_candidates = []


def _extract_name(soup, data):
    name = _jsonld_value(
        data,
        "name",
    )

    if name:
        return name

    h1 = soup.find("h1")

    if h1:
        return " ".join(
            h1.stripped_strings
        )

    title = soup.find("title")

    if title:
        return _clean(
            title.get_text(
                " ",
                strip=True,
            )
        )

    return ""


def _extract_image(soup, data):
    image = data.get("image")

    if isinstance(
        image,
        dict,
    ):
        image = (
            image.get("url")
            or image.get("contentUrl")
        )

    if isinstance(
        image,
        list,
    ):
        image = (
            image[0]
            if image
            else None
        )

    if image:
        return urljoin(
            BASE_URL,
            str(image),
        )

    node = soup.select_one(
        'meta[property="og:image"]'
    )

    if node and node.get("content"):
        return urljoin(
            BASE_URL,
            node.get("content"),
        )

    return None


def _candidate_urls_from_html(
    html_text,
    query,
):
    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    scored = {}

    query_tokens = [
        token
        for token in _tokens(query)
        if token not in STOPWORDS
    ]

    def add(raw, context=""):
        url = _product_url(raw)

        if not url:
            return

        haystack = _norm(
            f"{context} {url}"
        )

        hits = sum(
            1
            for token in query_tokens
            if token in haystack
        )

        # Search pages can contain product URLs
        # without the exact visible product title.
        # Do not discard those if at least one
        # identity token matches.
        if query_tokens and hits == 0:
            return

        previous = scored.get(url)

        if previous is None or hits > previous:
            scored[url] = hits

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        add(
            anchor.get("href"),
            anchor.get_text(
                " ",
                strip=True,
            ),
        )

    # Generic URL extraction for JSON/embedded HTML.
    pattern = re.compile(
        r'https?://(?:www\.)?parfum-zentrum\.de/'
        r'[^"\'<>\s]+_z\d+/?',
        re.I,
    )

    for match in pattern.finditer(
        html_text
    ):
        add(match.group(0))

    relative_pattern = re.compile(
        r'["\']([^"\']+_z\d+/?)["\']',
        re.I,
    )

    for match in relative_pattern.finditer(
        html_text
    ):
        add(match.group(1))

    ordered = sorted(
        scored.items(),
        key=lambda item: (
            -item[1],
            len(item[0]),
            item[0],
        ),
    )

    return [
        url
        for url, _score in ordered
    ][:MAX_CANDIDATES]


def _search_page_state(html_text, query):
    """Return the live catalog state exposed by the store search page.

    States:
      - "results": the requested query is reflected and product URLs exist.
      - "zero": the requested query is reflected and the store explicitly
        reports zero products.
      - "unknown": the response is not enough to trust as a live catalog
        answer (for example a generic shell, redirect page, or bot page).

    This is intentionally separate from product extraction: a valid HTTP 200
    page is not by itself proof that the query exists in the current catalog.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    visible_text = soup.get_text(" ", strip=True)
    normalized_text = _norm(visible_text)
    normalized_query = _norm(query)

    if not normalized_query:
        return "unknown"

    # The real Parfum-Zentrum search page echoes the query in the heading,
    # e.g. `Suche „Liquid brun"`. Only then can a zero-result state be trusted.
    query_reflected = normalized_query in normalized_text

    if not query_reflected:
        return "unknown"

    # The site currently renders `Produkte (0)` for a query with no live
    # catalog matches. Accept small whitespace/markup variations.
    zero_patterns = (
        r"produkte\s*\(\s*0\s*\)",
        r"produkte\s*0",
        r"keine\s+produkte",
        r"keine\s+ergebnisse",
    )
    if any(
        re.search(pattern, normalized_text, re.I)
        for pattern in zero_patterns
    ):
        return "zero"

    # If product URLs are present, this is an actual positive search result.
    if _candidate_urls_from_html(html_text, query):
        return "results"

    return "unknown"


def _search_discovery(query):
    """Discover products from the store's live search first.

    Returns `(candidates, authoritative_zero)`.
    `authoritative_zero=True` means the live store search itself explicitly
    answered the query with zero products. In that case sitemap URLs must NOT
    be used as a fallback, because they may represent stale/hidden products.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        endpoints = (
            SEARCH_URL
            + "?q="
            + quote_plus(query),
            SEARCH_URL
            + "?search="
            + quote_plus(query),
            SEARCH_URL
            + "?query="
            + quote_plus(query),
            SEARCH_URL
            + "?text="
            + quote_plus(query),
        )

        seen = set()
        candidates = []
        authoritative_zero = False

        for endpoint in endpoints:
            try:
                response = session.get(
                    endpoint,
                    timeout=(
                        CONNECT_TIMEOUT,
                        READ_TIMEOUT,
                    ),
                    allow_redirects=True,
                )
            except requests.RequestException:
                continue

            try:
                if response.status_code >= 400:
                    continue

                html_text = response.text
                urls = _candidate_urls_from_html(
                    html_text,
                    query,
                )

                for url in urls:
                    if url in seen:
                        continue

                    seen.add(url)
                    candidates.append(url)

                    if len(candidates) >= MAX_CANDIDATES:
                        return candidates, False

                state = _search_page_state(
                    html_text,
                    query,
                )

                if state == "zero":
                    authoritative_zero = True
                elif state == "results":
                    # A live result page without extractable product URLs is
                    # not a reason to trust the sitemap, so keep searching the
                    # alternate parameter forms but do not mark zero.
                    pass
            finally:
                response.close()

        if candidates:
            return candidates, False

        return [], authoritative_zero

    finally:
        session.close()

def _xml_urls(xml_text):
    try:
        root = ET.fromstring(
            xml_text
        )
    except ET.ParseError:
        return []

    return [
        node.text.strip()
        for node in root.iter()
        if node.tag.endswith("loc")
        and node.text
    ]


def _get_sitemap_urls():
    """
    Load the complete product URL index published by Parfum-Zentrum.

    The previous implementation only inspected the first six child sitemaps.
    That is not safe: sitemap indexes are ordered administrative files, not a
    guarantee that the requested product is in one of the first six files.
    A perfectly valid product can therefore disappear from ScentHunter even
    though its product page exists and the URL is present in the site's index.

    We fetch every child sitemap (bounded by SITEMAP_MAX_CHILD_MAPS) in
    parallel, cache the resulting product URLs, and keep direct URLs from the
    root sitemap as well. This is generic and contains no perfume-specific
    rules or prices.
    """
    global _sitemap_cache
    global _sitemap_cached_at

    now = time.monotonic()

    if (
        _sitemap_cache
        and now - _sitemap_cached_at < SITEMAP_TTL
    ):
        return list(_sitemap_cache)

    with _sitemap_lock:
        now = time.monotonic()

        if (
            _sitemap_cache
            and now - _sitemap_cached_at < SITEMAP_TTL
        ):
            return list(_sitemap_cache)

        try:
            response = requests.get(
                SITEMAP_URL,
                headers=HEADERS,
                timeout=SITEMAP_TIMEOUT,
            )
            response.raise_for_status()
            root_urls = _xml_urls(response.text)
            response.close()
        except (requests.RequestException, ET.ParseError):
            return []

        child_maps = []
        direct_urls = []

        for url in root_urls:
            low = url.lower().split("?", 1)[0]
            if low.endswith(".xml") or low.endswith(".xml.gz"):
                child_maps.append(url)
            elif _product_url(url):
                direct_urls.append(url)

        # Some stores expose more than one sitemap index level. Resolve one
        # additional index level generically instead of assuming a fixed file
        # naming scheme.
        child_maps = list(dict.fromkeys(child_maps))[:SITEMAP_MAX_CHILD_MAPS]

        def fetch_sitemap(url):
            try:
                child = requests.get(
                    url,
                    headers=HEADERS,
                    timeout=(1.8, 4.0),
                )
                try:
                    if child.status_code != 200:
                        return []
                    return _xml_urls(child.text)
                finally:
                    child.close()
            except (requests.RequestException, ET.ParseError):
                return []

        collected = list(direct_urls)

        if child_maps:
            with ThreadPoolExecutor(
                max_workers=min(SITEMAP_WORKERS, len(child_maps))
            ) as pool:
                futures = [
                    pool.submit(fetch_sitemap, url)
                    for url in child_maps
                ]

                for future in as_completed(futures):
                    try:
                        values = future.result()
                    except Exception:
                        values = []

                    collected.extend(values)

        # If a child sitemap is itself an index, resolve its children once.
        nested_maps = []
        product_urls = []

        for url in collected:
            low = url.lower().split("?", 1)[0]
            if low.endswith(".xml") or low.endswith(".xml.gz"):
                nested_maps.append(url)
            elif _product_url(url):
                product_urls.append(url)

        nested_maps = list(dict.fromkeys(nested_maps))[:SITEMAP_MAX_CHILD_MAPS]

        if nested_maps:
            with ThreadPoolExecutor(
                max_workers=min(SITEMAP_WORKERS, len(nested_maps))
            ) as pool:
                futures = [
                    pool.submit(fetch_sitemap, url)
                    for url in nested_maps
                ]

                for future in as_completed(futures):
                    try:
                        values = future.result()
                    except Exception:
                        values = []

                    for value in values:
                        if _product_url(value):
                            product_urls.append(value)

        # Preserve order while removing duplicates.
        unique = []
        seen = set()

        for url in product_urls:
            canonical = _product_url(url)
            if not canonical:
                continue

            key = canonical.lower()
            if key in seen:
                continue

            seen.add(key)
            unique.append(canonical)

        _sitemap_cache = unique
        _sitemap_cached_at = time.monotonic()

        return list(_sitemap_cache)


def _sitemap_discovery(query):
    urls = _get_sitemap_urls()

    if not urls:
        return []

    scored = []

    query_tokens = [
        token
        for token in _tokens(query)
        if token not in STOPWORDS
    ]

    requested_concentration = _concentration(
        query
    )
    requested_size = _requested_size(
        query
    )

    for url in urls:
        url_text = _norm(
            unquote(url)
        )

        hits = sum(
            1
            for token in query_tokens
            if token in url_text
        )

        if (
            query_tokens
            and hits < len(query_tokens)
        ):
            continue

        score = hits * 20

        concentration = _concentration(
            url
        )

        if (
            requested_concentration
            and concentration
            == requested_concentration
        ):
            score += 50

        candidate_size = _size_ml(
            url
        )

        if (
            requested_size is not None
            and candidate_size is not None
        ):
            if abs(
                candidate_size
                - requested_size
            ) < 0.01:
                score += 80
            else:
                score -= 80

        if (
            requested_size is None
            and candidate_size is not None
        ):
            if candidate_size >= 50:
                score += 20
            elif candidate_size <= 30:
                score -= 20

        scored.append(
            (score, url)
        )

    scored.sort(
        key=lambda item: (
            -item[0],
            len(item[1]),
            item[1],
        )
    )

    return [
        url
        for _score, url in scored
    ][:MAX_CANDIDATES]


def _extract_product(url, query):
    try:
        response = _session().get(
            url,
            timeout=PRODUCT_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None

    try:
        if response.status_code != 200:
            return None

        html_text = response.text
    finally:
        response.close()

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    data = _jsonld_product(
        soup
    )

    name = _extract_name(
        soup,
        data,
    )

    if not name:
        return None

    if not _matches_query(
        name,
        query,
    ):
        return None

    if not _looks_like_perfume(
        name
    ):
        return None

    price = _extract_price(
        soup,
        data,
    )

    availability = (
        _jsonld_availability(
            data
        )
        or _availability_from_text(
            soup.get_text(
                " ",
                strip=True,
            )
        )
    )

    # Out-of-stock products are valid results
    # even when no current price is exposed.
    if (
        price is None
        and availability
        == "unknown"
    ):
        return None

    brand = _jsonld_value(
        data,
        "brand",
    )

    image = _extract_image(
        soup,
        data,
    )

    size = _size_ml(
        name
    )

    gtin = _jsonld_value(
        data,
        "gtin13",
        "gtin",
        "gtin8",
    )

    mpn = _jsonld_value(
        data,
        "mpn",
    )

    sku = _jsonld_value(
        data,
        "sku",
    )

    product_id = _jsonld_value(
        data,
        "productID",
        "productId",
    )

    concentration = (
        _concentration(name)
    )

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand,
            "url": url,
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
                    "value": product_id,
                    "source": "jsonld",
                }
                if product_id
                else None
            ),
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": (
                {
                    "value": size,
                    "source": "product_title",
                }
                if size is not None
                else None
            ),
            "concentration": (
                {
                    "value": concentration,
                    "source": "product_title",
                }
                if concentration
                else None
            ),
            "gender": {
                "value": "unknown",
                "source": "not_explicit",
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
            "source_page": url,
            "product_source": (
                "jsonld_or_page"
            ),
        },
        "raw_data": {
            "jsonld": data,
        },

        # Compatibility fields for the current main.py.
        "name": name,
        "brand": brand,
        "price": (
            f"{price:.2f}€"
            if price is not None
            else None
        ),
        "price_num": price,
        "url": url,
        "available": (
            availability == "in_stock"
            if availability != "unknown"
            else None
        ),
        "availability": availability,
        "size_ml": size,
        "size": (
            f"{int(size)} ml"
            if size is not None
            and float(size).is_integer()
            else (
                f"{size} ml"
                if size is not None
                else None
            )
        ),
        "concentration": concentration,
        "image": image,
        "gtin": gtin,
        "mpn": mpn,
        "sku": sku,
        "store_product_id": product_id,
    }


def search(query):
    query = _clean(query)

    if not query:
        return []

    # PRIMARY PATH: the store's live search is authoritative when it
    # explicitly reports zero products. This prevents stale sitemap/product
    # URLs from reappearing in ScentHunter after the retailer removes a
    # product from its current catalog.
    candidates, authoritative_zero = _search_discovery(
        query
    )

    # FALLBACK 1: Parfum-Zentrum's live search is known to return
    # "Produkte (0)" for products that are visibly present in its own
    # first-party category pages. Search the public category index before
    # falling back to the much larger sitemap.
    if not candidates:
        category_urls = (
            BASE_URL + "/french-avenue_v1341/",
            BASE_URL + "/french-avenue_v1341/orient-duftwelt_k378/",
            BASE_URL + "/french-avenue_v1341/parfum_k319/herrendufte_k322/herren-eau-de-parfum-edp_k390/",
            BASE_URL + "/herrendufte/",
            BASE_URL + "/herren-eau-de-parfum/",
            BASE_URL + "/parfums/",
        )

        for category_url in category_urls:
            try:
                response = _session().get(
                    category_url,
                    timeout=PRODUCT_TIMEOUT,
                    allow_redirects=True,
                )
            except requests.RequestException:
                continue

            try:
                if response.status_code != 200 or not response.text:
                    continue

                discovered = _candidate_urls_from_html(
                    response.text,
                    query,
                )

                for url in discovered:
                    if url not in candidates:
                        candidates.append(url)

                    if len(candidates) >= MAX_CANDIDATES:
                        break

                if candidates:
                    break
            finally:
                response.close()

    # FALLBACK 2: complete first-party sitemap.
    # This remains generic and is only used when the lighter category
    # discovery did not find the requested product.
    if not candidates:
        candidates = _sitemap_discovery(
            query
        )

    if not candidates:
        return []

    results = []
    seen = set()

    with ThreadPoolExecutor(
        max_workers=min(
            PRODUCT_WORKERS,
            len(candidates),
        )
    ) as pool:
        futures = {
            pool.submit(
                _extract_product,
                url,
                query,
            ): url
            for url in candidates
        }

        for future in as_completed(
            futures
        ):
            try:
                item = future.result()
            except Exception:
                continue

            if not item:
                continue

            key = (
                item.get("url"),
                item.get("size_ml"),
                item.get("price_num"),
                item.get("availability"),
            )

            if key in seen:
                continue

            seen.add(key)
            results.append(item)

    def sort_key(item):
        availability = item.get(
            "availability"
        )

        if availability == "out_of_stock":
            state_rank = 2
        elif item.get("price_num") is not None:
            state_rank = 0
        else:
            state_rank = 1

        price = item.get(
            "price_num"
        )

        try:
            numeric_price = float(
                price
            )
        except (
            TypeError,
            ValueError,
        ):
            numeric_price = float(
                "inf"
            )

        return (
            state_rank,
            numeric_price,
            float(
                item.get("size_ml")
                or 99999
            ),
        )

    results.sort(
        key=sort_key
    )

    return results[:40]


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import sys

    query = (
        " ".join(sys.argv[1:]).strip()
        or "Afnan 9 PM"
    )

    print(
        json.dumps(
            search(query),
            ensure_ascii=False,
            indent=2,
        )
    )
