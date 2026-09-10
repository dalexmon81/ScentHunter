"""
ScentHunter - Notino adapter
Fast live search with bounded fallbacks.

Order:
1. Notino FR internal search
2. direct product-page fetches in parallel
3. Jina reader only for product pages blocked by Notino
4. no sitemap crawling during live user search

Notino is intentionally isolated: failures here must never affect the
other seven retailers.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
READER_BASE = "https://r.jina.ai/http://"

CONNECT_TIMEOUT = 2.0
READ_TIMEOUT = 5.0
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

READER_TIMEOUT = 6.0
MAX_CANDIDATES = 18
PRODUCT_WORKERS = 8

PRODUCT_RE = re.compile(r"/p-(\d+)(?:/|$)", re.I)
SIZE_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl|dl|l|oz|fl\.?\s*oz)\b",
    re.I,
)

PRICE_RE = re.compile(
    r"(?:€\s*)?(\d{1,4}(?:[.,]\d{1,2})?)\s*€?",
    re.I,
)

GENERIC_WORDS = {
    "pour", "femme", "femmes", "homme", "hommes",
    "for", "the", "and", "avec", "de", "du", "des",
    "la", "le", "les", "un", "une", "par", "eau",
    "edp", "edt", "parfum", "parfums", "perfume",
    "perfumes", "woman", "women", "man", "men",
    "unisex", "unisexe", "extrait", "spray",
    "vaporisateur", "ml", "cl", "dl", "l",
}

NON_PERFUME_MARKERS = {
    "gift set", "set cadeau", "coffret", "discovery set",
    "travel set", "kit", "duo", "trio", "mystery box",
    "tester", "testeur", "sample", "samples", "shampoo",
    "shower gel", "body wash", "body lotion", "body cream",
    "body milk", "deodorant", "déodorant", "aftershave",
    "body spray", "hair mist", "makeup", "cosmetics",
    "skincare", "crème corps", "gel douche",
}

OUT_MARKERS = (
    "rupture de stock",
    "en rupture",
    "actuellement indisponible",
    "produit indisponible",
    "momentanément indisponible",
    "épuisé",
    "out of stock",
    "sold out",
    "currently unavailable",
    "unavailable",
    "non disponible",
)

IN_MARKERS = (
    "en stock",
    "ajouter au panier",
    "add to cart",
    "disponible",
    "available",
    "commander",
    "order now",
)

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
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def clean(value) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\\/", "/")
    text = text.replace("â‚¬", "€").replace("Â", "")
    return re.sub(r"\s+", " ", text).strip()


def norm(value) -> str:
    text = unicodedata.normalize(
        "NFKD",
        clean(value).casefold(),
    )
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )
    text = re.sub(
        r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)",
        " ",
        text,
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def query_tokens(query):
    return [
        token
        for token in norm(query).split()
        if token not in GENERIC_WORDS
        and len(token) > 1
    ]


def requested_size_ml(query):
    match = SIZE_RE.search(clean(query))
    if not match:
        return None

    number = float(
        match.group(1).replace(",", ".")
    )
    unit = match.group(2).lower().replace(" ", "")

    if unit == "cl":
        number *= 10
    elif unit == "dl":
        number *= 100
    elif unit == "l":
        number *= 1000
    elif unit in {"oz", "floz"}:
        number *= 29.5735

    return number


def extract_size(text):
    match = SIZE_RE.search(clean(text))
    if not match:
        return None

    number = float(
        match.group(1).replace(",", ".")
    )
    unit = match.group(2).lower().replace(" ", "")

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


def parse_price(value):
    text = clean(value)

    # Prefer a currency-bound value.
    currency_matches = re.findall(
        r"(?:€\s*)(\d{1,4}(?:[.,]\d{1,2})?)"
        r"|(\d{1,4}(?:[.,]\d{1,2})?)\s*€",
        text,
    )

    for groups in currency_matches:
        raw = next(
            (item for item in groups if item),
            None,
        )
        if raw:
            try:
                value = float(raw.replace(",", "."))
                if 0 < value <= 10000:
                    return round(value, 2)
            except ValueError:
                pass

    return None


def product_url(url):
    if not url:
        return ""

    value = clean(url)
    # Jina Reader returns Markdown links; absolute URLs captured from
    # Markdown can carry the closing `)` of the link. Remove only common
    # trailing punctuation, never characters from the product path itself.
    value = value.rstrip(").,;]")

    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = urljoin(BASE_URL, value)
    elif not value.lower().startswith(("http://", "https://")):
        value = urljoin(BASE_URL + "/", value)

    parsed = urlparse(value)

    host = parsed.netloc.lower().split(":", 1)[0]

    if not host.endswith("notino.fr"):
        return ""

    path = parsed.path

    if not PRODUCT_RE.search(path):
        return ""

    return parsed._replace(
        query="",
        fragment="",
    ).geturl()


def product_id(url):
    match = PRODUCT_RE.search(url or "")
    return match.group(1) if match else None


def slug_name(url):
    try:
        path = unquote(
            urlparse(url).path
        ).strip("/")

        pieces = [
            piece
            for piece in path.split("/")
            if piece
        ]

        if not pieces:
            return ""

        value = pieces[-1]
        value = re.sub(
            r"^p-\d+",
            "",
            value,
            flags=re.I,
        ).strip("-")

        return re.sub(
            r"\s+",
            " ",
            value.replace("-", " "),
        ).strip()

    except Exception:
        return ""


def name_matches(name, query):
    name_norm = norm(name)
    if not name_norm:
        return False

    required = query_tokens(query)

    if not required:
        # Queries consisting only of generic words are intentionally rejected.
        return False

    name_tokens = set(name_norm.split())

    if not all(
        token in name_tokens
        for token in required
    ):
        return False

    requested = requested_size_ml(query)

    if requested is not None:
        discovered = extract_size(name)

        if (
            discovered is not None
            and abs(discovered - requested) > 0.01
        ):
            return False

    return True


def non_perfume(name):
    value = f" {norm(name)} "

    for marker in NON_PERFUME_MARKERS:
        marker_norm = norm(marker)
        if f" {marker_norm} " in value:
            return True

    return False


def jsonld_objects(soup):
    objects = []

    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            data = json.loads(
                script.get_text(strip=True)
            )
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

            objects.append(item)

            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

    return objects


def product_jsonld(soup):
    for item in jsonld_objects(soup):
        kind = item.get("@type")

        if kind == "Product":
            return item

        if isinstance(kind, list) and "Product" in kind:
            return item

        if (
            item.get("name")
            and "offers" in item
        ):
            return item

    return {}


def offer_list(data):
    offers = data.get("offers")

    if isinstance(offers, dict):
        return [offers]

    if isinstance(offers, list):
        return [
            offer
            for offer in offers
            if isinstance(offer, dict)
        ]

    return []


def availability_from_text(text):
    value = norm(text)

    if any(
        norm(marker) in value
        for marker in OUT_MARKERS
    ):
        return False

    if any(
        norm(marker) in value
        for marker in IN_MARKERS
    ):
        return True

    return None


def offer_availability(offer):
    if not isinstance(offer, dict):
        return None

    return availability_from_text(
        offer.get("availability")
        or offer.get("itemAvailability")
        or offer.get("availabilityStatus")
        or ""
    )


def scoped_availability(soup):
    selectors = (
        '[itemprop="availability"]',
        '[data-testid*="availability" i]',
        '[data-test*="availability" i]',
        '[class*="availability" i]',
        '[class*="stock" i]',
        '[class*="add-to-cart" i]',
        '[class*="buy" i]',
        'button[type="submit"]',
    )

    parts = []

    for selector in selectors:
        try:
            nodes = soup.select(selector)
        except Exception:
            nodes = []

        for node in nodes[:12]:
            text = clean(
                node.get("content")
                or node.get("aria-label")
                or node.get_text(
                    " ",
                    strip=True,
                )
            )

            if text:
                parts.append(text)

    if not parts:
        return None

    return availability_from_text(
        " ".join(parts)
    )


def extract_brand(data, soup):
    brand = data.get("brand")

    if isinstance(brand, dict):
        brand = brand.get("name")

    brand = clean(brand)

    if brand:
        return brand

    node = soup.select_one(
        '[itemprop="brand"]'
    )

    if node:
        return clean(
            node.get("content")
            or node.get_text(
                " ",
                strip=True,
            )
        )

    return ""


def extract_concentration(name):
    value = norm(name)

    if (
        "eau de toilette" in value
        or re.search(r"\bedt\b", value)
    ):
        return "Eau de Toilette"

    if (
        "eau de parfum" in value
        or re.search(r"\bedp\b", value)
    ):
        return "Eau de Parfum"

    if "extrait de parfum" in value:
        return "Extrait de Parfum"

    if (
        re.search(r"\bparfum\b", value)
        and "eau de parfum" not in value
    ):
        return "Parfum"

    return None


def image_from_jsonld(data, url):
    image = data.get("image")

    if isinstance(image, list):
        image = image[0] if image else None

    if not image:
        return None

    return urljoin(
        url,
        str(image),
    )


def candidate_urls(html_text, query):
    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    candidates = {}

    q_tokens = query_tokens(query)

    def add(raw, context=""):
        url = product_url(raw)

        if not url:
            return

        blob = norm(
            f"{context} {url}"
        )

        hits = sum(
            1
            for token in q_tokens
            if token in blob
        )

        if q_tokens and hits == 0:
            return

        old = candidates.get(url)

        if old is None or hits > old:
            candidates[url] = hits

    # Normal anchors.
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

    # HTML / JSON / JS URLs.
    patterns = (
        r'https?://(?:www\.)?notino\.fr/[^"\'>\s]+/p-\d+(?:/[^"\'>\s]*)?',
        r'["\']((?:https?:)?//(?:www\.)?notino\.fr/[^"\']+/p-\d+(?:/[^"\']*)?)["\']',
        r'["\']((?:/[^"\']*)?/p-\d+(?:/[^"\']*)?)["\']',
    )

    for pattern in patterns:
        for raw in re.findall(
            pattern,
            html_text,
            flags=re.I,
        ):
            if isinstance(raw, tuple):
                raw = "".join(raw)
            add(raw)

    ordered = sorted(
        candidates.items(),
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


def discover(session, query):
    # Notino can return the public search page to normal browsers while
    # blocking server-side requests from cloud/datacenter IPs. Therefore
    # the first discovery path is the same public search page through
    # Jina Reader. This is discovery only: product data is still fetched
    # from Notino directly first, with Jina as the bounded product fallback.
    search_endpoint = (
        SEARCH_URL
        + "?exps="
        + quote_plus(query)
    )

    seen = set()
    candidates = []

    def add_from(text):
        for url in candidate_urls(text, query):
            if url in seen:
                continue

            seen.add(url)
            candidates.append(url)

            if len(candidates) >= MAX_CANDIDATES:
                return True

        return False

    # 1. Jina Reader search discovery. This is the primary route because
    # it avoids Notino's datacenter-IP blocking on the search endpoint.
    reader_url = (
        READER_BASE
        + search_endpoint.replace(
            "https://",
            "",
            1,
        )
    )

    try:
        response = requests.get(
            reader_url,
            headers={
                "User-Agent": "ScentHunter/1.0",
                "Accept": "text/plain",
            },
            timeout=READER_TIMEOUT,
        )

        if response.status_code < 400 and response.text:
            if add_from(response.text):
                return candidates
    except requests.RequestException:
        pass

    # 2. Direct Notino search fallback. Kept bounded and limited to the
    # current endpoint; older parameters are not useful enough to justify
    # four sequential 5-second waits on a blocked cloud IP.
    try:
        response = session.get(
            search_endpoint,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code < 400 and response.text:
            add_from(response.text)
    except requests.RequestException:
        pass

    return candidates


def parse_product(url, html_text, query):
    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    data = product_jsonld(soup)

    h1 = soup.find("h1")

    name = clean(
        data.get("name")
    ) or (
        clean(h1.get_text(
            " ",
            strip=True,
        ))
        if h1
        else ""
    )

    if not name:
        name = slug_name(url)

    if not name_matches(
        name,
        query,
    ):
        return []

    if non_perfume(name):
        return []

    brand = extract_brand(
        data,
        soup,
    )

    offers = offer_list(data)

    # Structured offers are the strongest source.
    structured = []

    for offer in offers:
        state = offer_availability(offer)

        if state is None:
            state = scoped_availability(
                soup
            )

        price = parse_price(
            offer.get("price")
            or offer.get("lowPrice")
        )

        offer_name = clean(
            offer.get("name")
            or ""
        )

        size = extract_size(
            offer_name
        )

        if size is None:
            size = extract_size(name)

        if (
            price is None
            and state is not False
        ):
            continue

        structured.append(
            make_result(
                name=name,
                brand=brand,
                url=url,
                price=price,
                size=size,
                state=state,
                data=data,
            )
        )

    if structured:
        return structured

    # Product-page scoped fallback.
    state = scoped_availability(
        soup
    )

    price = None

    price_nodes = soup.select(
        '[itemprop="price"], '
        '[data-testid*="price" i], '
        '[class*="price" i]'
    )

    for node in price_nodes[:25]:
        price = parse_price(
            node.get("content")
            or node.get_text(
                " ",
                strip=True,
            )
        )

        if price is not None:
            break

    size = extract_size(name)

    if (
        price is None
        and state is not False
    ):
        return []

    return [
        make_result(
            name=name,
            brand=brand,
            url=url,
            price=price,
            size=size,
            state=state,
            data=data,
        )
    ]


def make_result(
    name,
    brand,
    url,
    price,
    size,
    state,
    data,
):
    if state is True:
        availability = "in_stock"
    elif state is False:
        availability = "out_of_stock"
    else:
        availability = "unknown"

    if size is not None:
        size_label = (
            f"{int(size)} ml"
            if float(size).is_integer()
            else f"{size} ml"
        )
    else:
        size_label = None

    sku = clean(
        data.get("sku")
        or ""
    ) or None

    gtin = clean(
        data.get("gtin13")
        or data.get("gtin")
        or ""
    ) or None

    image = image_from_jsonld(
        data,
        url,
    )

    return {
        "store": STORE,
        "brand": brand,
        "name": name,
        "price": (
            f"{price:.2f}".replace(".", ",")
            + " €"
            if price is not None
            else None
        ),
        "price_num": price,
        "url": url,
        "size": size_label,
        "size_ml": size,
        "available": state,
        "availability": availability,
        "concentration": extract_concentration(name),
        "image": image,
        "sku": sku,
        "store_product_id": sku,
        "gtin": gtin,
    }


def fetch_requests(url):
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        try:
            response = session.get(
                url,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            return None, None

        if response.status_code >= 400:
            return None, None

        return (
            response.url,
            response.text,
        )

    finally:
        session.close()


def fetch_reader(url):
    """
    Jina fallback only for an individual product page.

    This is deliberately NOT used for search discovery and is hard bounded.
    """
    reader_url = (
        READER_BASE
        + url.replace(
            "https://",
            "",
            1,
        )
    )

    try:
        response = requests.get(
            reader_url,
            headers={
                "User-Agent": "ScentHunter/1.0",
                "Accept": "text/plain",
            },
            timeout=READER_TIMEOUT,
        )
    except requests.RequestException:
        return None

    if response.status_code >= 400:
        return None

    if not response.text:
        return None

    return response.text


def fetch_and_parse(url, query):
    fetched_url, html_text = fetch_requests(
        url
    )

    if html_text:
        items = parse_product(
            fetched_url or url,
            html_text,
            query,
        )

        if items:
            return items

    # Only blocked/empty product pages reach this path.
    reader_text = fetch_reader(url)

    if not reader_text:
        return []

    return parse_product(
        url,
        reader_text,
        query,
    )


def search(query):
    query = clean(query)

    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        candidates = discover(
            session,
            query,
        )
    finally:
        session.close()

    if not candidates:
        return []

    results = []
    seen = set()

    with ThreadPoolExecutor(
        max_workers=min(
            PRODUCT_WORKERS,
            len(candidates),
        )
    ) as executor:
        futures = {
            executor.submit(
                fetch_and_parse,
                url,
                query,
            ): url
            for url in candidates
        }

        for future in as_completed(
            futures
        ):
            try:
                items = future.result()
            except Exception:
                continue

            for item in items:
                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                key = (
                    item.get("url"),
                    item.get("size_ml"),
                    item.get("price_num"),
                    item.get("available"),
                )

                if key in seen:
                    continue

                seen.add(key)
                results.append(item)

    def sort_key(item):
        state = item.get("available")
        price = item.get("price_num")

        if state is False:
            rank = 2
        elif price is not None:
            rank = 0
        else:
            rank = 1

        try:
            numeric_price = float(price)
        except (
            TypeError,
            ValueError,
        ):
            numeric_price = float("inf")

        return (
            rank,
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
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "query",
        nargs="+",
    )

    args = parser.parse_args()

    print(
        json.dumps(
            search(
                " ".join(args.query)
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
