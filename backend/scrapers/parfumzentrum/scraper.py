"""ScentHunter - ParfumZentrum scraper.

Generic store adapter.

Responsibilities:
- discover product URLs from the live ParfumZentrum catalog/search;
- fetch real product pages;
- extract retailer commercial data;
- preserve technical failures;
- never decide canonical product identity.

No perfume-specific URL, SKU, price, family, variant or product fallback
is contained in this file.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "ParfumZentrum"
BASE_URL = "https://www.parfum-zentrum.de"
SEARCH_URL = BASE_URL + "/suchen/"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 7.0
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

MAX_CANDIDATES = 60
MAX_RESULTS = 60
PRODUCT_WORKERS = 8
SITEMAP_WORKERS = 12
SITEMAP_MAX_CHILD_MAPS = 100
SITEMAP_TTL = 30 * 60

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
    "ml", "cl", "man", "woman", "men", "women",
    "herren", "damen", "unisex", "unisexe",
    "parfum", "parfums", "perfume", "perfumes",
    "duft", "dufte",
}

NON_PRODUCT_MARKERS = {
    "geschenkset", "geschenksets", "gift set", "giftset",
    "coffret", "coffrets", "duo", "trio",
    "shampoo", "duschgel", "body lotion", "body cream",
    "körpercreme", "körperlotion", "deodorant", "deostick",
    "aftershave", "rasierwasser", "haarspray", "hair mist",
    "makeup", "kosmetik", "creme", "serum",
}


class StoreRequestError(RuntimeError):
    def __init__(
        self,
        status,
        message,
        url=None,
        http_status=None,
    ):
        super().__init__(message)
        self.status = status
        self.url = url
        self.http_status = http_status


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
    text = re.sub(
        r"[^a-z0-9äöüß]+",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value):
    return re.findall(
        r"[a-z0-9äöüß]+",
        _norm(value),
    )


def _query_tokens(query):
    return [
        token
        for token in _tokens(query)
        if token not in STOPWORDS
        and len(token) > 1
    ]


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


def _parse_price(value):
    if value is None:
        return None

    if isinstance(
        value,
        (int, float),
    ) and not isinstance(value, bool):
        number = float(value)
        return (
            round(number, 2)
            if 0 < number < 10000
            else None
        )

    raw = _clean(value)
    raw = raw.replace("€", "")
    raw = raw.replace("EUR", "")
    raw = raw.strip()

    match = re.search(
        r"\d{1,3}(?:\.\d{3})*,\d{2}"
        r"|\d+(?:[.,]\d{2})",
        raw,
    )

    if not match:
        return None

    number = match.group(0)

    if "," in number:
        if "." in number:
            number = number.replace(".", "")
        number = number.replace(",", ".")
    else:
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


def _price_text(value):
    number = _parse_price(value)
    if number is None:
        return None
    return f"{number:.2f}".replace(".", ",") + " €"


def _availability(value):
    text = _norm(value)

    if any(
        marker in text
        for marker in (
            "out of stock",
            "sold out",
            "unavailable",
            "nicht lieferbar",
            "nicht vorrätig",
            "ausverkauft",
            "nicht verfügbar",
        )
    ):
        return "out_of_stock"

    if any(
        marker in text
        for marker in (
            "in stock",
            "available",
            "auf lager",
            "versandbereit",
            "sofort lieferbar",
            "lieferbar",
            "in den warenkorb",
        )
    ):
        return "in_stock"

    return "unknown"


def _request(session, url, params=None):
    for attempt in range(2):
        try:
            response = session.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.Timeout as exc:
            if attempt == 0:
                time.sleep(0.25)
                continue
            raise StoreRequestError(
                "timeout",
                "ParfumZentrum request timed out",
                url=url,
            ) from exc
        except requests.ConnectionError as exc:
            if attempt == 0:
                time.sleep(0.25)
                continue
            raise StoreRequestError(
                "unavailable",
                "ParfumZentrum connection failed",
                url=url,
            ) from exc
        except requests.RequestException as exc:
            if attempt == 0:
                time.sleep(0.25)
                continue
            raise StoreRequestError(
                "error",
                f"ParfumZentrum request failed: {type(exc).__name__}",
                url=url,
            ) from exc

        status = response.status_code

        if 200 <= status < 300:
            return response

        if status in (401, 403):
            raise StoreRequestError(
                "blocked",
                f"ParfumZentrum returned HTTP {status}",
                url=url,
                http_status=status,
            )

        if status == 429:
            if attempt == 0:
                time.sleep(0.6)
                continue
            raise StoreRequestError(
                "blocked",
                "ParfumZentrum rate-limited the request",
                url=url,
                http_status=status,
            )

        if status >= 500:
            if attempt == 0:
                time.sleep(0.35)
                continue
            raise StoreRequestError(
                "unavailable",
                f"ParfumZentrum returned HTTP {status}",
                url=url,
                http_status=status,
            )

        if 400 <= status < 500:
            raise StoreRequestError(
                "error",
                f"ParfumZentrum returned HTTP {status}",
                url=url,
                http_status=status,
            )

        raise StoreRequestError(
            "error",
            f"Unexpected ParfumZentrum HTTP status {status}",
            url=url,
            http_status=status,
        )

    raise StoreRequestError(
        "error",
        "ParfumZentrum request exhausted retries",
        url=url,
    )


def _product_url(raw):
    raw = _clean(raw)

    if not raw:
        return ""

    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = urljoin(BASE_URL, raw)
    elif not re.match(r"^https?://", raw, re.I):
        raw = urljoin(BASE_URL + "/", raw)

    parsed = urlparse(raw)
    host = parsed.netloc.lower().split(":", 1)[0]

    if host not in {
        "www.parfum-zentrum.de",
        "parfum-zentrum.de",
    }:
        return ""

    if not re.search(
        r"_z\d+/?$",
        parsed.path,
        re.I,
    ):
        return ""

    return parsed._replace(
        netloc="www.parfum-zentrum.de",
        query="",
        fragment="",
    ).geturl()


def _matches_query(name, query):
    wanted = _query_tokens(query)
    if not wanted:
        return False

    haystack = set(_tokens(name))

    if not all(
        token in haystack
        for token in wanted
    ):
        return False

    requested_concentration = _concentration(query)
    if requested_concentration:
        actual_concentration = _concentration(name)
        if (
            actual_concentration
            and actual_concentration
            != requested_concentration
        ):
            return False

    requested_size = _size_ml(query)
    actual_size = _size_ml(name)

    if (
        requested_size is not None
        and actual_size is not None
        and abs(actual_size - requested_size) > 0.01
    ):
        return False

    return True


def _looks_like_product(name):
    text = f" {_norm(name)} "

    for marker in NON_PRODUCT_MARKERS:
        if f" {_norm(marker)} " in text:
            return False

    return True


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
        item_type = item.get("@type")
        types = (
            item_type
            if isinstance(item_type, list)
            else [item_type]
        )

        if (
            "Product" in types
            or "ProductGroup" in types
        ):
            return item

    return {}


def _jsonld_value(data, *keys):
    if not isinstance(data, dict):
        return None

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
            item
            for item in offers
            if isinstance(item, dict)
        ]

    return []


def _jsonld_price(data):
    for offer in _offer_objects(data):
        number = _parse_price(
            offer.get("price")
            or offer.get("lowPrice")
        )
        if number is not None:
            return number

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
            value in marker
            for value in (
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


def _bad_price_context(node):
    current = node

    for _ in range(8):
        if current is None:
            break

        text = _norm(
            current.get_text(
                " ",
                strip=True,
            )
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
            value in text
            for value in (
                "grundpreis",
                "pro liter",
                "per liter",
                "preis inkl code",
                "coupon",
                "gutschein",
                "rabattcode",
            )
        ):
            return True

        if any(
            value in marker
            for value in (
                "coupon",
                "voucher",
                "gutschein",
                "discount",
                "related",
                "cross-sell",
                "upsell",
            )
        ):
            return True

        current = current.parent

    return False


def _node_price(node):
    for attr in (
        "content",
        "data-price",
        "data-product-price",
        "value",
    ):
        if node.has_attr(attr):
            number = _parse_price(
                node.get(attr)
            )
            if number is not None:
                return number

    return _parse_price(
        node.get_text(
            " ",
            strip=True,
        )
    )


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
        for node in soup.select(selector):
            if _bad_price_context(node):
                continue

            number = _node_price(node)
            if number is None:
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
                value in marker
                for value in (
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

            if "in den warenkorb" in parent_text:
                score += 40

            candidates.append(
                (score, number)
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


def _extract_price(soup, data):
    number = _jsonld_price(data)

    if number is not None:
        return number

    h1 = soup.find("h1")

    if h1:
        current = h1

        for distance in range(8):
            current = getattr(
                current,
                "parent",
                None,
            )

            if current is None:
                break

            text = current.get_text(
                " ",
                strip=True,
            )
            low = _norm(text)

            if "€" not in text:
                continue

            score = 0

            if "in den warenkorb" in low:
                score += 300

            if (
                "auf lager" in low
                or "versandbereit" in low
            ):
                score += 200

            if (
                "inkl mwst" in low
                or "inkl. mwst" in low
            ):
                score += 100

            if score <= 0:
                continue

            local = []

            for node in current.find_all(
                [
                    "span",
                    "div",
                    "p",
                    "strong",
                    "b",
                    "ins",
                ]
            ):
                node_text = node.get_text(
                    " ",
                    strip=True,
                )

                if "€" not in node_text:
                    continue

                if _is_struck(node):
                    continue

                if _bad_price_context(node):
                    continue

                value = _parse_price(node_text)
                if value is not None:
                    local.append(value)

            if local:
                return min(local)

            if distance >= 5:
                break

    return _semantic_price(soup)


def _extract_name(soup, data):
    name = _jsonld_value(
        data,
        "name",
    )

    if name:
        return name

    h1 = soup.find("h1")
    if h1:
        return _clean(
            h1.get_text(
                " ",
                strip=True,
            )
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

    if isinstance(image, dict):
        image = (
            image.get("url")
            or image.get("contentUrl")
        )

    if isinstance(image, list):
        image = image[0] if image else None

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
        html_text or "",
        "html.parser",
    )

    scored = {}
    wanted = _query_tokens(query)

    def add(raw_url, context=""):
        url = _product_url(raw_url)
        if not url:
            return

        haystack = _norm(
            f"{context} {url}"
        )

        hits = sum(
            1
            for token in wanted
            if token in haystack
        )

        if wanted and hits == 0:
            return

        old = scored.get(url)

        if old is None or hits > old:
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

    absolute_pattern = re.compile(
        r'https?://(?:www\.)?'
        r'parfum-zentrum\.de/'
        r'[^"\'<>\s]+_z\d+/?',
        re.I,
    )

    for match in absolute_pattern.finditer(
        html_text or ""
    ):
        add(match.group(0))

    relative_pattern = re.compile(
        r'["\']([^"\']+_z\d+/?)[\'"]',
        re.I,
    )

    for match in relative_pattern.finditer(
        html_text or ""
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


def _search_page_state(
    html_text,
    query,
):
    soup = BeautifulSoup(
        html_text or "",
        "html.parser",
    )

    visible = _norm(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    query_normalized = _norm(query)

    if not query_normalized:
        return "unknown"

    if query_normalized not in visible:
        return "unknown"

    if any(
        re.search(
            pattern,
            visible,
            re.I,
        )
        for pattern in (
            r"produkte\s*\(\s*0\s*\)",
            r"produkte\s*0",
            r"keine\s+produkte",
            r"keine\s+ergebnisse",
        )
    ):
        return "zero"

    if _candidate_urls_from_html(
        html_text,
        query,
    ):
        return "results"

    return "unknown"


def _search_discovery(
    session,
    query,
):
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

    candidates = []
    seen = set()
    failures = []
    verified_zero = False

    for endpoint in endpoints:
        try:
            response = _request(
                session,
                endpoint,
            )
        except StoreRequestError as exc:
            failures.append(
                {
                    "status": exc.status,
                    "url": exc.url,
                    "http_status": exc.http_status,
                    "message": str(exc),
                }
            )
            continue

        try:
            html = response.text or ""

            for url in _candidate_urls_from_html(
                html,
                query,
            ):
                if url in seen:
                    continue

                seen.add(url)
                candidates.append(url)

                if len(candidates) >= MAX_CANDIDATES:
                    break

            state = _search_page_state(
                html,
                query,
            )

            if state == "zero":
                verified_zero = True

        finally:
            response.close()

        if len(candidates) >= MAX_CANDIDATES:
            break

    if candidates:
        return candidates, {
            "status": (
                "success"
                if not failures
                else "partial"
            ),
            "verified": True,
            "discovery": "live_search",
            "candidate_count": len(candidates),
            "failures": failures,
        }

    if verified_zero and not failures:
        return [], {
            "status": "success",
            "verified": True,
            "discovery": "verified_empty",
            "candidate_count": 0,
            "failures": [],
        }

    return [], {
        "status": (
            failures[0]["status"]
            if failures
            else "success"
        ),
        "verified": False if failures else True,
        "discovery": (
            "search_unverified"
            if failures
            else "verified_empty"
        ),
        "candidate_count": 0,
        "failures": failures,
    }


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


def _load_sitemap():
    """
    Load the complete first-party product URL index.

    Cache is process-local and expires periodically. A failed refresh never
    converts an existing valid cache into an empty catalog.
    """

    try:
        response = requests.get(
            SITEMAP_URL,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        root_urls = _xml_urls(
            response.text
        )
        response.close()
    except (
        requests.RequestException,
        ET.ParseError,
    ) as exc:
        raise StoreRequestError(
            "unavailable",
            "ParfumZentrum sitemap unavailable",
            url=SITEMAP_URL,
        ) from exc

    child_maps = []
    direct_products = []

    for url in root_urls:
        low = url.lower().split("?", 1)[0]

        if (
            low.endswith(".xml")
            or low.endswith(".xml.gz")
        ):
            child_maps.append(url)
        elif _product_url(url):
            direct_products.append(url)

    child_maps = list(
        dict.fromkeys(child_maps)
    )[:SITEMAP_MAX_CHILD_MAPS]

    def fetch_child(url):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )

            try:
                if response.status_code != 200:
                    return []

                return _xml_urls(
                    response.text
                )
            finally:
                response.close()

        except (
            requests.RequestException,
            ET.ParseError,
        ):
            return []

    collected = list(direct_products)

    if child_maps:
        with ThreadPoolExecutor(
            max_workers=min(
                SITEMAP_WORKERS,
                len(child_maps),
            )
        ) as pool:
            futures = [
                pool.submit(
                    fetch_child,
                    url,
                )
                for url in child_maps
            ]

            for future in as_completed(
                futures
            ):
                try:
                    collected.extend(
                        future.result()
                    )
                except Exception:
                    continue

    nested_maps = []
    product_urls = []

    for url in collected:
        low = url.lower().split("?", 1)[0]

        if (
            low.endswith(".xml")
            or low.endswith(".xml.gz")
        ):
            nested_maps.append(url)
        elif _product_url(url):
            product_urls.append(url)

    nested_maps = list(
        dict.fromkeys(nested_maps)
    )[:SITEMAP_MAX_CHILD_MAPS]

    if nested_maps:
        with ThreadPoolExecutor(
            max_workers=min(
                SITEMAP_WORKERS,
                len(nested_maps),
            )
        ) as pool:
            futures = [
                pool.submit(
                    fetch_child,
                    url,
                )
                for url in nested_maps
            ]

            for future in as_completed(
                futures
            ):
                try:
                    values = future.result()
                except Exception:
                    continue

                for value in values:
                    if _product_url(value):
                        product_urls.append(value)

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

    return unique


def _sitemap_discovery(
    query,
):
    urls = _load_sitemap()
    wanted = _query_tokens(query)

    if not wanted:
        return []

    scored = []

    for url in urls:
        haystack = _norm(
            url
        )

        hits = sum(
            1
            for token in wanted
            if token in haystack
        )

        if hits < len(wanted):
            continue

        score = hits * 20

        requested_size = _size_ml(query)
        candidate_size = _size_ml(url)

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

        requested_concentration = _concentration(
            query
        )

        if (
            requested_concentration
            and _concentration(url)
            == requested_concentration
        ):
            score += 50

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


def _extract_product(
    url,
    query,
):
    session = requests.Session()

    try:
        try:
            response = _request(
                session,
                url,
            )
        except StoreRequestError as exc:
            return [], {
                "status": exc.status,
                "url": exc.url,
                "http_status": exc.http_status,
                "error": str(exc),
            }

        try:
            html = response.text or ""
        finally:
            response.close()

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        data = _jsonld_product(soup)
        name = _extract_name(
            soup,
            data,
        )

        if not name:
            return [], {
                "status": "partial",
                "url": url,
                "reason": "missing_product_name",
            }

        if not _matches_query(
            name,
            query,
        ):
            return [], {
                "status": "partial",
                "url": url,
                "reason": "product_did_not_match_query",
            }

        if not _looks_like_product(name):
            return [], {
                "status": "partial",
                "url": url,
                "reason": "non_product_item",
            }

        price = _extract_price(
            soup,
            data,
        )

        state = (
            _jsonld_availability(data)
            or _availability(
                soup.get_text(
                    " ",
                    strip=True,
                )
            )
        )

        if (
            price is None
            and state == "unknown"
        ):
            return [], {
                "status": "partial",
                "url": url,
                "reason": "missing_offer_data",
            }

        brand = _jsonld_value(
            data,
            "brand",
        )

        image = _extract_image(
            soup,
            data,
        )

        size = _size_ml(name)
        concentration = _concentration(name)

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

        row = {
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
                "availability": state,
            },
            "provenance": {
                "source_page": url,
                "product_source": "jsonld_or_page",
            },
            "raw_data": {
                "jsonld": data,
            },

            # Compatibility fields for current backend code.
            "name": name,
            "brand": brand,
            "price": (
                _price_text(price)
                if price is not None
                else None
            ),
            "price_num": price,
            "url": url,
            "available": (
                True
                if state == "in_stock"
                else (
                    False
                    if state == "out_of_stock"
                    else None
                )
            ),
            "availability": state,
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
            "image_url": image,
            "gtin": gtin,
            "mpn": mpn,
            "sku": sku,
            "store_product_id": product_id,
        }

        return [row], {
            "status": "success",
            "url": url,
        }

    except Exception as exc:
        return [], {
            "status": "error",
            "url": url,
            "error": (
                f"{type(exc).__name__}: {exc}"
            ),
        }
    finally:
        session.close()


def parse_product(
    url,
    query,
):
    rows, _meta = _extract_product(
        _product_url(url),
        _clean(query),
    )
    return rows


def _search_stream_generator(query):
    """
    Standard ScentHunter scraper contract.

    verified=True with an empty result means discovery was actually verified.
    verified=False means the store could not be safely classified as empty.
    """

    query = _clean(query)

    if not query:
        yield {
            "status": "success",
            "verified": True,
            "results": [],
            "error": None,
            "details": {
                "reason": "empty_query",
            },
        }
        return

    started = time.perf_counter()
    session = requests.Session()

    try:
        candidates, discovery = _search_discovery(
            session,
            query,
        )
    finally:
        session.close()

    # If live search did not produce candidates and did not explicitly verify
    # an empty catalog, use the generic sitemap as discovery fallback.
    if (
        not candidates
        and not (
            discovery.get("verified")
            and discovery.get("discovery")
            == "verified_empty"
        )
    ):
        try:
            sitemap_candidates = _sitemap_discovery(
                query
            )
        except StoreRequestError as exc:
            sitemap_candidates = []
            discovery.setdefault(
                "failures",
                [],
            ).append(
                {
                    "status": exc.status,
                    "url": exc.url,
                    "http_status": exc.http_status,
                    "message": str(exc),
                }
            )

        if sitemap_candidates:
            candidates = sitemap_candidates
            discovery = {
                **discovery,
                "status": "partial",
                "verified": True,
                "discovery": "sitemap_catalog",
                "candidate_count": len(
                    candidates
                ),
            }

    if not candidates:
        verified = bool(
            discovery.get("verified")
        )

        yield {
            "status": discovery.get(
                "status",
                "success",
            ),
            "verified": verified,
            "results": [],
            "error": (
                None
                if verified
                else discovery.get(
                    "failures"
                )
            ),
            "details": {
                "stage": "discovery",
                "candidate_count": 0,
                "discovery": discovery.get(
                    "discovery"
                ),
                "elapsed": round(
                    time.perf_counter()
                    - started,
                    3,
                ),
            },
        }
        return

    results = []
    errors = []

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
            url = futures[future]

            try:
                rows, meta = future.result()
            except Exception as exc:
                rows = []
                meta = {
                    "status": "error",
                    "url": url,
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }

            results.extend(rows)

            if meta.get("status") not in {
                "success",
                "partial",
            }:
                errors.append(meta)

    seen = set()
    deduped = []

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
        key=lambda item: (
            2
            if item.get("availability")
            == "out_of_stock"
            else 0,
            (
                item.get("price_num")
                if item.get("price_num")
                is not None
                else 999999
            ),
            (
                item.get("size_ml")
                if item.get("size_ml")
                is not None
                else 999999
            ),
        )
    )

    deduped = deduped[:MAX_RESULTS]

    if deduped and errors:
        status = "partial"
        verified = True
    elif deduped:
        status = "success"
        verified = True
    elif errors:
        status = "partial"
        verified = False
    else:
        status = "success"
        verified = True

    yield {
        "status": status,
        "verified": verified,
        "results": deduped,
        "error": errors or None,
        "details": {
            "stage": "product_fetch",
            "candidate_count": len(
                candidates
            ),
            "result_count": len(
                deduped
            ),
            "error_count": len(errors),
            "elapsed": round(
                time.perf_counter()
                - started,
                3,
            ),
            "discovery": discovery,
        },
    }



def search_stream(query, emit=None):
    """Native ScentHunter callback contract.

    The store implementation below remains the authoritative discovery/fetch
    logic. This adapter only bridges its report-generator form to the common
    callback contract used by main.py.
    """
    report = None
    for value in _search_stream_generator(query):
        report = value
        if isinstance(value, dict) and callable(emit):
            for row in value.get("results") or []:
                if isinstance(row, dict):
                    emit(row)

    if report is None:
        return {
            "status": "error",
            "verified": False,
            "results": [],
            "error": "empty_stream",
            "details": {},
        }

    return report

def search(query):
    report = search_stream(query)
    return report.get(
        "results",
        [],
    )


def scrape(query):
    return search(query)


def diagnose(query):
    query = _clean(query)
    session = requests.Session()

    try:
        candidates, discovery = _search_discovery(
            session,
            query,
        )

        if not candidates:
            try:
                candidates = _sitemap_discovery(
                    query
                )
            except StoreRequestError:
                candidates = []

        return {
            "diagnostic": True,
            "query": query,
            "status": discovery.get(
                "status"
            ),
            "verified": discovery.get(
                "verified"
            ),
            "candidate_count": len(
                candidates
            ),
            "candidates": candidates[:50],
            "details": discovery,
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

    report = (
        diagnose(args.query)
        if args.diagnose
        else search_stream(args.query)
    )

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )
