import argparse
import json
import os
import re
import unicodedata
from typing import Any, Dict
from urllib.parse import urljoin, urlparse, parse_qs, urlunparse

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.be"
SEARCH_PATH = "/zoeken.html"
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

PRODUCT_RE = re.compile(r"/product/(\d+)/", re.I)
PRODUCT_URL_RE = re.compile(
    r'(?:(?:https?:)?//(?:www\.)?deloox\.nl)?'
    r'/product/\d+/[^"\'<>\s\\]+',
    re.I,
)

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "for", "by",
}

NON_PRODUCT_TERMS = {
    "gift set", "set regalo", "coffret", "bundle", "deodorant",
    "deo spray", "shower gel", "body lotion", "after shave",
    "aftershave", "travel set", "discovery set", "kit",
    "body mist", "handcreme",
}

MAX_SEARCH_PAGES = 10
MAX_SITEMAPS = 120
MAX_SITEMAP_PRODUCTS = 200


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c)).lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def same_host(url):
    try:
        host = urlparse(url).netloc.lower()
        return host == "deloox.be" or host.endswith(".deloox.be")
    except Exception:
        return False


def product_url(url):
    return PRODUCT_RE.search(url or "") is not None


def query_tokens(query):
    return [t for t in norm(query).split() if t not in IGNORED_QUERY_WORDS]


def explicit_size(query):
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*ml\b",
        norm(query),
        re.I,
    )
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return int(value) if value.is_integer() else value


def extract_size_ml(*texts):
    for text in texts:
        for value in re.findall(
            r"(?<!\d)(\d+(?:[.,]\d+)?)\s*ml\b",
            str(text or ""),
            re.I,
        ):
            number = float(value.replace(",", "."))
            return int(number) if number.is_integer() else number
    return None


def extract_concentration(*texts):
    rules = (
        ("Extrait de Parfum", r"\bextrait de parfum\b"),
        ("Eau de Parfum", r"\beau de parfum\b"),
        ("Eau de Toilette", r"\beau de toilette\b"),
        ("Eau de Cologne", r"\beau de cologne\b"),
        ("Parfum", r"\bparfum\b"),
    )
    for text in texts:
        value = norm(text)
        if not value:
            continue
        for label, pattern in rules:
            if re.search(pattern, value, re.I):
                return label
    return None


def extract_gender(*texts):
    for text in texts:
        value = norm(text)
        if not value:
            continue

        if "unisex" in value or "unisexe" in value:
            return "unisex"

        if re.search(
            r"\b(men|male|him|heren|homme|pour homme)\b",
            value,
            re.I,
        ):
            return "men"

        if re.search(
            r"\b(women|female|her|dames|femme|pour femme)\b",
            value,
            re.I,
        ):
            return "women"

    return "unknown"


def extract_json_ld(soup):
    products = []

    for script in soup.find_all(
        "script",
        attrs={"type": re.compile(r"application/ld\+json", re.I)},
    ):
        raw = (script.string or script.get_text()).strip()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop(0)

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            item_type = item.get("@type", "")
            types = item_type if isinstance(item_type, list) else [item_type]

            if any(
                str(value).lower() == "product"
                for value in types
            ):
                products.append(item)

            graph = item.get("@graph")

            if isinstance(graph, list):
                stack.extend(graph)

    if not products:
        return None

    return products[0]


def extract_json_ld_products(soup):
    products = []

    for script in soup.find_all(
        "script",
        attrs={"type": re.compile(r"application/ld\+json", re.I)},
    ):
        raw = (script.string or script.get_text()).strip()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop(0)

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            item_type = item.get("@type", "")
            types = item_type if isinstance(item_type, list) else [item_type]

            if any(
                str(value).lower() == "product"
                for value in types
            ):
                products.append(item)

            graph = item.get("@graph")

            if isinstance(graph, list):
                stack.extend(graph)

    return products


def extract_availability(soup, json_ld=None, product_name=""):
    """Determine the availability of the selected product offer.

    Availability evidence is ranked by specificity:
    1) explicit purchase controls on the product page;
    2) structured Offer availability;
    3) text around the product name.

    This prevents stale recommendation text or a stale JSON-LD value from
    overriding a live purchase action. The rule is generic for every product.
    """
    page_text = norm(soup.get_text(" ", strip=True))

    in_stock_markers = (
        "in winkelwagen",
        "toevoegen aan winkelwagen",
        "bestel nu",
        "vandaag besteld",
        "morgen in huis",
        "voor 22 00 besteld",
        "voor 22 00 uur besteld",
    )

    out_stock_markers = (
        "tijdelijk uitverkocht",
        "uitverkocht",
        "niet op voorraad",
        "niet beschikbaar",
    )

    # Purchase controls are the strongest live signal. Inspect button/input/link
    # text and disabled state before generic page text.
    purchase_in = False
    purchase_out = False
    for node in soup.find_all(["button", "input", "a"]):
        text = clean(
            node.get("value")
            or node.get("aria-label")
            or node.get_text(" ", strip=True)
        )
        low = norm(text)
        if not low:
            continue

        if any(marker in low for marker in in_stock_markers):
            disabled = node.has_attr("disabled") or str(node.get("aria-disabled") or "").lower() == "true"
            if not disabled:
                purchase_in = True

        if any(marker in low for marker in out_stock_markers):
            purchase_out = True

    if purchase_in:
        return "in_stock"
    if purchase_out:
        # Do not return immediately: structured Offer data below may provide
        # a stronger current state than a passive text label.
        pass

    # Use the selected Product/Offer JSON-LD as the next source of evidence.
    products = []
    if isinstance(json_ld, dict):
        products.append(json_ld)

    for product in extract_json_ld_products(soup):
        if product not in products:
            products.append(product)

    structured_in = False
    structured_out = False

    for product in products:
        offers = product.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        if not isinstance(offers, list):
            continue

        for offer in offers:
            if not isinstance(offer, dict):
                continue
            value = norm(" ".join(
                str(part)
                for part in (
                    offer.get("availability"),
                    offer.get("itemCondition"),
                    offer.get("stock"),
                )
                if part
            ))

            if any(marker in value for marker in (
                "instock", "limitedavailability", "preorder"
            )):
                structured_in = True
            elif any(marker in value for marker in (
                "outofstock", "soldout", "discontinued"
            )):
                structured_out = True

    if structured_in:
        return "in_stock"
    if structured_out:
        return "out_of_stock"

    # Finally inspect the local product-name window. If both passive markers
    # are present, prefer the positive purchase signal.
    local_text = page_text
    product_norm = norm(product_name)
    if product_norm:
        pos = page_text.find(product_norm)
        if pos >= 0:
            local_text = page_text[max(0, pos - 2500):pos + 6000]

    local_in = any(marker in local_text for marker in in_stock_markers)
    local_out = any(marker in local_text for marker in out_stock_markers)

    if local_in:
        return "in_stock"
    if local_out:
        return "out_of_stock"

    return "unknown"

def extract_price(soup, json_ld=None):
    candidates = []

    if isinstance(json_ld, dict):
        offers = json_ld.get("offers")

        if isinstance(offers, dict):
            candidates.append(offers.get("price"))

        elif isinstance(offers, list):
            candidates.extend(
                offer.get("price")
                for offer in offers
                if isinstance(offer, dict)
            )

    for selector in (
        'meta[itemprop="price"]',
        'meta[property="product:price:amount"]',
        "[data-price]",
    ):
        for node in soup.select(selector):
            candidates.append(
                node.get("content")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )

    for value in candidates:
        try:
            number = float(
                str(value)
                .replace("€", "")
                .replace(" ", "")
                .replace(",", ".")
            )
        except (TypeError, ValueError):
            continue

        if 0 < number < 10000:
            return round(number, 2)

    text = soup.get_text(" ", strip=True)

    for match in re.finditer(
        r"(?:€\s*)?(\d{1,4}[.,]\d{2})(?:\s*€)?",
        text,
    ):
        try:
            number = float(
                match.group(1)
                .replace(".", "")
                .replace(",", ".")
            )
        except ValueError:
            continue

        if 0 < number < 10000:
            return round(number, 2)

    return None


def visible_product_name(soup, json_ld=None):
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

    if isinstance(json_ld, dict):
        value = clean(json_ld.get("name"))

        if value:
            return value

    return (
        clean(soup.title.get_text(" ", strip=True))
        if soup.title
        else ""
    )


def visible_brand(soup, json_ld=None):
    if isinstance(json_ld, dict):
        brand = json_ld.get("brand")

        if isinstance(brand, dict):
            brand = brand.get("name")

        brand = clean(brand)

        if brand:
            return brand

    return ""


def query_matches_product(
    name,
    query,
    brand="",
    size_ml=None,
    url="",
):
    if not name or not query or not product_url(url):
        return False

    tokens = query_tokens(query)

    if not tokens:
        return False

    identity = norm(" ".join((name, brand)))

    if not all(token in identity for token in tokens):
        return False

    requested_size = explicit_size(query)

    if requested_size is not None and size_ml is not None:
        if float(requested_size) != float(size_ml):
            return False

    name_only = norm(name)
    query_n = norm(query)

    for phrase in NON_PRODUCT_TERMS:
        if (
            norm(phrase) in name_only
            and norm(phrase) not in query_n
        ):
            return False

    return True


def _add_candidate(
    candidates,
    seen,
    page_url,
    url,
    text="",
):
    url = (
        urljoin(page_url, str(url))
        .replace("\\/", "/")
        .replace("\\u002F", "/")
    )

    url = url.split("#", 1)[0].split("?", 1)[0]

    if (
        not same_host(url)
        or not product_url(url)
        or url in seen
    ):
        return

    seen.add(url)

    candidates.append(
        {
            "url": url,
            "text": clean(text),
        }
    )


def extract_search_candidates(
    soup,
    page_url,
    raw_html="",
):
    candidates = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        text = clean(
            anchor.get("title")
            or anchor.get("aria-label")
            or anchor.get_text(" ", strip=True)
        )

        image = anchor.find("img")

        if image:
            text = clean(
                " ".join(
                    value
                    for value in (
                        text,
                        image.get("alt"),
                        image.get("title"),
                    )
                    if value
                )
            )

        _add_candidate(
            candidates,
            seen,
            page_url,
            anchor.get("href"),
            text,
        )

        for attr in (
            "data-href",
            "data-url",
            "data-product-url",
        ):
            if anchor.get(attr):
                _add_candidate(
                    candidates,
                    seen,
                    page_url,
                    anchor.get(attr),
                    text,
                )

    # Some products can exist only in embedded JSON/JS or lazy-load data.
    # Read product URLs from the complete response, not only from <a> tags.
    raw = (
        raw_html
        .replace("\\/", "/")
        .replace("\\u002F", "/")
    )

    for match in PRODUCT_URL_RE.finditer(raw):
        _add_candidate(
            candidates,
            seen,
            page_url,
            match.group(0),
        )

    return candidates


def _search_page_urls(
    soup,
    page_url,
    query,
):
    urls = []
    seen = set()
    wanted = norm(query)

    for anchor in soup.find_all("a", href=True):
        url = urljoin(
            page_url,
            anchor.get("href"),
        )

        parsed = urlparse(url)

        if parsed.netloc and not same_host(url):
            continue

        if (
            parsed.path.rstrip("/")
            != SEARCH_PATH.rstrip("/")
        ):
            continue

        params = parse_qs(parsed.query)
        q_values = params.get("q", [])

        if (
            q_values
            and norm(q_values[0]) != wanted
        ):
            continue

        if "page" not in params:
            continue

        try:
            page = int(params["page"][0])
        except (TypeError, ValueError):
            continue

        if page < 1 or page > MAX_SEARCH_PAGES:
            continue

        clean_url = urlunparse(
            (
                parsed.scheme or "https",
                parsed.netloc or "www.deloox.be",
                parsed.path,
                parsed.params,
                parsed.query,
                "",
            )
        )

        if clean_url not in seen:
            seen.add(clean_url)
            urls.append(clean_url)

    return urls


def fetch(
    session,
    url,
    params=None,
):
    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if (
            not response.ok
            or not same_host(response.url)
        ):
            return None

        return response

    except requests.RequestException:
        return None



def select_matching_json_ld_product(
    soup,
    query,
    url="",
):
    """Select the Product JSON-LD that actually matches this product page.

    Deloox pages can contain several Product objects for recommendations or
    related variants. The first object is not necessarily the current page.
    """
    products = extract_json_ld_products(soup)
    if not products:
        return None

    page_url = str(url or "").split("?", 1)[0].rstrip("/").lower()
    best = None
    best_score = -1

    for product in products:
        name = clean(product.get("name"))
        brand = product.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        brand = clean(brand)

        identity = norm(" ".join((name, brand)))
        if not name:
            continue

        score = 0
        if query_matches_product(
            name,
            query,
            brand,
            extract_size_ml(name),
            page_url,
        ):
            score += 100

        product_url = clean(
            product.get("url")
            or product.get("@id")
        ).split("?", 1)[0].rstrip("/").lower()

        if product_url and page_url and product_url == page_url:
            score += 50

        query_n = norm(query)
        if query_n and query_n in identity:
            score += 20

        if score > best_score:
            best_score = score
            best = product

    return best if best_score >= 100 else None


def extract_offer_availability(product):
    """Return stock state from the selected Product's offers only."""
    if not isinstance(product, dict):
        return "unknown"

    offers = product.get("offers")
    if isinstance(offers, dict):
        offers = [offers]

    if not isinstance(offers, list):
        return "unknown"

    has_out = False
    for offer in offers:
        if not isinstance(offer, dict):
            continue

        value = norm(" ".join(
            str(part)
            for part in (
                offer.get("availability"),
                offer.get("itemCondition"),
                offer.get("stock"),
            )
            if part
        ))

        if any(marker in value for marker in (
            "instock",
            "limitedavailability",
            "preorder",
        )):
            return "in_stock"

        if any(marker in value for marker in (
            "outofstock",
            "soldout",
            "discontinued",
        )):
            has_out = True

    return "out_of_stock" if has_out else "unknown"


def extract_offer_price(product):
    if not isinstance(product, dict):
        return None

    offers = product.get("offers")
    if isinstance(offers, dict):
        offers = [offers]

    if not isinstance(offers, list):
        return None

    for offer in offers:
        if not isinstance(offer, dict):
            continue
        value = offer.get("price")
        try:
            number = float(
                str(value)
                .replace("€", "")
                .replace(" ", "")
                .replace(",", ".")
            )
        except (TypeError, ValueError):
            continue
        if 0 < number < 10000:
            return round(number, 2)

    return None


def parse_product_page(
    response,
    query,
):
    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    url = response.url.split("?", 1)[0]

    selected_product = select_matching_json_ld_product(
        soup,
        query,
        url,
    )

    if selected_product is not None:
        name = clean(selected_product.get("name"))
        brand_value = selected_product.get("brand")
        if isinstance(brand_value, dict):
            brand_value = brand_value.get("name")
        brand = clean(brand_value)
        json_ld = selected_product
    else:
        json_ld = extract_json_ld(soup)
        name = visible_product_name(
            soup,
            json_ld,
        )
        brand = visible_brand(
            soup,
            json_ld,
        )

    page_text = soup.get_text(
        " ",
        strip=True,
    )

    size_ml = extract_size_ml(
        name,
    )

    concentration = extract_concentration(
        name,
    )

    gender = extract_gender(
        name,
        page_text,
    )

    if selected_product is not None:
        price = extract_offer_price(
            selected_product,
        )
        availability = extract_availability(
            soup,
            selected_product,
            name,
        )
    else:
        price = extract_price(
            soup,
            json_ld,
        )
        availability = extract_availability(
            soup,
            json_ld,
            name,
        )

    if not query_matches_product(
        name,
        query,
        brand,
        size_ml,
        url,
    ):
        return None

    image = ""

    if isinstance(json_ld, dict):
        image_value = json_ld.get("image")

        if (
            isinstance(image_value, list)
            and image_value
        ):
            image = clean(image_value[0])
        else:
            image = clean(image_value)

    if not image:
        node = soup.select_one(
            'meta[property="og:image"]'
        )

        if node:
            image = clean(
                node.get("content")
            )

    match = PRODUCT_RE.search(url)

    product_id = (
        match.group(1)
        if match
        else None
    )

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand or None,
            "url": url,
            "image": image or None,
        },
        "identity": {
            "gtin": None,
            "mpn": None,
            "sku": None,
            "store_product_id": product_id,
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {
                "value": size_ml,
                "source": "product_page",
            },
            "concentration": {
                "value": concentration,
                "source": "product_page",
            },
            "gender": {
                "value": gender,
                "source": "product_page",
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
            "name_source": "product_page",
            "brand_source": "product_page",
            "price_source": "product_page",
            "product_source": "product_page",
        },
        "raw_data": {
            "name": name,
            "brand": brand,
            "size_ml": size_ml,
            "concentration": concentration,
            "gender": gender,
        },
        "name": name,
        "price": (
            f"{price:.2f}".replace(".", ",")
            + " €"
            if price is not None
            else ""
        ),
        "url": url,
        "image": image,
        "available": (
            True if availability == "in_stock"
            else False if availability == "out_of_stock"
            else None
        ),
    }


def _xml_locs(text):
    if not text:
        return []

    try:
        soup = BeautifulSoup(
            text,
            "xml",
        )

        return [
            clean(node.get_text(strip=True))
            for node in soup.find_all("loc")
            if clean(
                node.get_text(strip=True)
            )
        ]

    except Exception:
        return [
            clean(value)
            for value in re.findall(
                r"<loc[^>]*>\s*(.*?)\s*</loc>",
                text,
                re.I | re.S,
            )
            if clean(value)
        ]


def _sitemap_urls(
    session,
    query,
):
    wanted = set(
        query_tokens(query)
    )

    if not wanted:
        return []

    queue = [
        BASE_URL + path
        for path in (
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap-index.xml",
            "/en/sitemap.xml",
        )
    ]

    seen_maps = set()
    seen_products = set()
    product_urls = []

    try:
        robots = session.get(
            BASE_URL + "/robots.txt",
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if robots.ok:
            for line in robots.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    queue.append(
                        line.split(
                            ":",
                            1,
                        )[1].strip()
                    )

    except requests.RequestException:
        pass

    while (
        queue
        and len(seen_maps) < MAX_SITEMAPS
        and len(product_urls)
        < MAX_SITEMAP_PRODUCTS
    ):
        sitemap_url = queue.pop(0)

        if sitemap_url in seen_maps:
            continue

        seen_maps.add(sitemap_url)

        try:
            response = session.get(
                sitemap_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )

        except requests.RequestException:
            continue

        if not response.ok:
            continue

        for value in _xml_locs(
            response.text
        ):
            low = value.lower()

            if (
                low.endswith(".xml")
                or "sitemap" in low
            ):
                if value not in seen_maps:
                    queue.append(value)
                continue

            if (
                not same_host(value)
                or not product_url(value)
            ):
                continue

            url = (
                value
                .split("#", 1)[0]
                .split("?", 1)[0]
            )

            if url in seen_products:
                continue

            # Generic discovery only. The product page remains
            # the final authority for product identity.
            if not wanted.issubset(
                set(query_tokens(url))
            ):
                continue

            seen_products.add(url)
            product_urls.append(url)

            if (
                len(product_urls)
                >= MAX_SITEMAP_PRODUCTS
            ):
                break

    return product_urls



def _debug_visible_stock_evidence(
    soup: BeautifulSoup,
    product_name: str = "",
) -> Dict[str, Any]:
    page_text = norm(soup.get_text(" ", strip=True))

    in_markers = (
        "in winkelwagen",
        "toevoegen aan winkelwagen",
        "bestel nu",
        "vandaag besteld",
        "morgen in huis",
        "voor 22 00 besteld",
        "voor 22 00 uur besteld",
    )
    out_markers = (
        "tijdelijk uitverkocht",
        "uitverkocht",
        "niet op voorraad",
        "niet beschikbaar",
    )

    local_text = page_text
    product_n = norm(product_name)
    anchor_position = page_text.find(product_n) if product_n else -1
    if anchor_position >= 0:
        local_text = page_text[
            max(0, anchor_position - 2500):
            anchor_position + 6000
        ]

    def evidence(markers):
        result = []
        for marker in markers:
            pos = local_text.find(marker)
            if pos >= 0:
                result.append({
                    "marker": marker,
                    "context": local_text[
                        max(0, pos - 220):
                        pos + len(marker) + 320
                    ],
                })
        return result

    return {
        "product_anchor_found": anchor_position >= 0,
        "in_stock": evidence(in_markers),
        "out_of_stock": evidence(out_markers),
        "local_text_length": len(local_text),
    }


def _debug_deloox_product(
    session,
    url,
    query,
):
    trace = {
        "url": url,
        "request": {},
        "page": {},
        "identity": {},
        "json_ld": [],
        "price": {},
        "availability": {},
        "decision": {},
    }

    response = fetch(session, url)
    if response is None:
        trace["request"] = {
            "status": None,
            "error": "fetch() returned None",
        }
        trace["decision"] = {
            "accepted": False,
            "reason": "fetch_failed",
        }
        return trace

    trace["request"] = {
        "status": response.status_code,
        "final_url": response.url,
        "html_length": len(response.text or ""),
    }

    soup = BeautifulSoup(response.text, "html.parser")
    final_url = response.url.split("?", 1)[0]

    all_products = extract_json_ld_products(soup)
    visible_name = visible_product_name(soup)
    visible_brand_value = visible_brand(soup)

    trace["page"] = {
        "visible_name": visible_name,
        "visible_brand": visible_brand_value,
        "title": (
            clean(soup.title.get_text(" ", strip=True))
            if soup.title else ""
        ),
        "url": final_url,
    }

    selected = select_matching_json_ld_product(
        soup,
        query,
        final_url,
    )

    selected_index = None
    selected_identity = ""
    for index, product in enumerate(all_products):
        name = clean(product.get("name"))
        brand = product.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        brand = clean(brand)
        identity = norm(" ".join((name, brand)))
        matches = query_matches_product(
            name,
            query,
            brand,
            extract_size_ml(name),
            final_url,
        )
        trace["json_ld"].append({
            "index": index,
            "name": name,
            "brand": brand,
            "url": clean(
                product.get("url") or product.get("@id")
            ),
            "query_match": matches,
            "identity": identity,
            "offers": [
                {
                    "price": offer.get("price"),
                    "availability": offer.get("availability"),
                    "sku": offer.get("sku"),
                    "url": offer.get("url"),
                }
                for offer in (
                    [product.get("offers")]
                    if isinstance(product.get("offers"), dict)
                    else product.get("offers", [])
                    if isinstance(product.get("offers"), list)
                    else []
                )
                if isinstance(offer, dict)
            ],
        })
        if selected is product:
            selected_index = index
            selected_identity = identity

    trace["identity"] = {
        "query": query,
        "visible_name_match": query_matches_product(
            visible_name,
            query,
            visible_brand_value,
            extract_size_ml(visible_name),
            final_url,
        ),
        "selected_json_ld_index": selected_index,
        "selected_json_ld_identity": selected_identity,
        "selected_json_ld_name": (
            clean(selected.get("name"))
            if selected else ""
        ),
    }

    if selected:
        json_price = extract_offer_price(selected)
        json_stock = extract_offer_availability(selected)
    else:
        json_price = None
        json_stock = "unknown"

    visible_stock = _debug_visible_stock_evidence(
        soup,
        clean(selected.get("name")) if selected else visible_name,
    )
    page_stock = extract_availability(
        soup,
        selected,
        clean(selected.get("name")) if selected else visible_name,
    )

    meta_prices = []
    for selector in (
        'meta[itemprop="price"]',
        'meta[property="product:price:amount"]',
        "[data-price]",
    ):
        for node in soup.select(selector):
            meta_prices.append({
                "selector": selector,
                "value": (
                    node.get("content")
                    or node.get("data-price")
                    or node.get_text(" ", strip=True)
                ),
            })

    generic_price = extract_price(soup, selected)

    trace["price"] = {
        "selected_json_ld": json_price,
        "generic_page_extractor": generic_price,
        "meta_and_data_price": meta_prices[:30],
    }

    trace["availability"] = {
        "visible_evidence": visible_stock,
        "availability_function_final": page_stock,
        "selected_json_ld": json_stock,
        "explicit_conflict": (
            page_stock != "unknown"
            and json_stock != "unknown"
            and page_stock != json_stock
        ),
    }

    try:
        actual = parse_product_page(response, query)
    except Exception as exc:
        actual = {
            "debug_exception": f"{type(exc).__name__}: {exc}"
        }

    trace["decision"] = {
        "actual_parse_product_page": actual,
        "accepted": bool(actual),
        "final_available": (
            actual.get("available")
            if isinstance(actual, dict)
            else None
        ),
        "final_price": (
            actual.get("price")
            if isinstance(actual, dict)
            else None
        ),
    }

    return trace


def diagnose(
    query,
):
    query = clean(query)
    session = requests.Session()

    try:
        first = fetch(
            session,
            urljoin(BASE_URL, SEARCH_PATH),
            params={"q": query},
        )

        if first is None:
            return {
                "diagnostic": True,
                "store": STORE.lower(),
                "query": query,
                "error": "search_request_failed",
            }

        discovery = []
        seen = set()

        def merge_debug(items, source):
            for item in items:
                url = item["url"]
                if url not in seen:
                    seen.add(url)
                    discovery.append({
                        "url": url,
                        "source": source,
                        "search_context": item.get("text", ""),
                    })

        soup = BeautifulSoup(first.text, "html.parser")
        merge_debug(
            extract_search_candidates(
                soup,
                first.url,
                first.text,
            ),
            "search",
        )

        for page_url in _search_page_urls(
            soup,
            first.url,
            query,
        ):
            page = fetch(session, page_url)
            if page is None:
                continue
            page_soup = BeautifulSoup(
                page.text,
                "html.parser",
            )
            merge_debug(
                extract_search_candidates(
                    page_soup,
                    page.url,
                    page.text,
                ),
                "pagination",
            )

        for url in _sitemap_urls(session, query):
            if url not in seen:
                seen.add(url)
                discovery.append({
                    "url": url,
                    "source": "sitemap",
                    "search_context": "",
                })

        traces = [
            _debug_deloox_product(
                session,
                item["url"],
                query,
            )
            for item in discovery
        ]

        return {
            "diagnostic": True,
            "store": STORE.lower(),
            "query": query,
            "search_status": first.status_code,
            "search_final_url": first.url,
            "discovery_count": len(discovery),
            "discovery": discovery,
            "product_traces": traces,
        }
    finally:
        session.close()


def search(query):
    query = clean(query)

    if not query:
        return []

    session = requests.Session()

    try:
        first = fetch(
            session,
            urljoin(
                BASE_URL,
                SEARCH_PATH,
            ),
            params={"q": query},
        )

        if first is None:
            return []

        discovery_urls = []
        seen_urls = set()

        def merge(candidates):
            for item in candidates:
                url = item["url"]

                if url not in seen_urls:
                    seen_urls.add(url)
                    discovery_urls.append(url)

        soup = BeautifulSoup(
            first.text,
            "html.parser",
        )

        # 1. Normal result cards.
        # 2. data-* product URLs.
        # 3. Embedded/lazy-loaded product URLs.
        merge(
            extract_search_candidates(
                soup,
                first.url,
                first.text,
            )
        )

        # Follow pagination only when Deloox exposes it.
        page_urls = _search_page_urls(
            soup,
            first.url,
            query,
        )

        for page_url in page_urls:
            page = fetch(
                session,
                page_url,
            )

            if page is None:
                continue

            page_soup = BeautifulSoup(
                page.text,
                "html.parser",
            )

            merge(
                extract_search_candidates(
                    page_soup,
                    page.url,
                    page.text,
                )
            )

        # Sitemap discovery is an independent generic fallback.
        merge(
            {
                "url": url,
                "text": "",
            }
            for url in _sitemap_urls(
                session,
                query,
            )
        )

        results = []
        seen_keys = set()

        for url in discovery_urls:
            response = fetch(
                session,
                url,
            )

            if response is None:
                continue

            product = parse_product_page(
                response,
                query,
            )

            if product is None:
                continue

            key = (
                product["url"].lower(),
                norm(product["name"]),
            )

            if key in seen_keys:
                continue

            seen_keys.add(key)
            results.append(product)

        return results

    except Exception:
        return []

    finally:
        session.close()


def scrape(query):
    # Production behavior is unchanged unless the temporary diagnostic flag
    # is explicitly enabled in the environment.
    if os.getenv("SCENTHUNTER_SCRAPER_DEBUG", "").strip() == "1":
        trace = diagnose(query)
        print(
            "[SCENTHUNTER_SCRAPER_DEBUG]"
            + json.dumps(
                trace,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

        results = []
        seen = set()
        for item in trace.get("product_traces", []):
            result = (
                item.get("decision", {})
                .get("actual_parse_product_page")
            )
            if not result:
                continue

            key = (
                str(result.get("url", ""))
                + "|"
                + norm(result.get("name", ""))
            ).lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(result)

        return results

    return search(query)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="run a detailed, non-production diagnostic trace",
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
