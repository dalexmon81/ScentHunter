from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
SITEMAP_URL = BASE_URL + "/sitemap.xml"
TIMEOUT = 10
MAX_PRODUCT_CANDIDATES = 30
MAX_CATEGORY_PAGES = 6

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-GB,en;q=0.9,it;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
    "spray", "ml", "for", "by", "pour", "the", "and",
}

NON_PRODUCT_TERMS = {
    "gift set", "set", "coffret", "bundle", "deodorant", "deo spray",
    "shower gel", "body lotion", "aftershave", "after shave", "travel set",
    "discovery set", "miniature", "body mist", "car perfume", "candle",
    "interior perfume", "home fragrance",
}


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value)).lower()
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(value: Any, *, ignore_generic: bool = False) -> List[str]:
    result = norm(value).split()
    if ignore_generic:
        result = [token for token in result if token not in IGNORED_QUERY_WORDS]
    return [token for token in result if len(token) > 1 or token.isdigit()]


def _compact(value: Any) -> str:
    return "".join(tokens(value, ignore_generic=True))


def _contains_all_tokens(text: Any, wanted: Iterable[str]) -> bool:
    haystack = set(tokens(text))
    return bool(wanted) and all(token in haystack for token in wanted)


def _query_size(query: str) -> Optional[float]:
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", clean(query), re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10
    return int(value) if value.is_integer() else value


def _extract_size(*values: Any) -> Optional[float]:
    text = " ".join(clean(value) for value in values)
    matches = list(re.finditer(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", text, re.I))
    if not matches:
        return None
    match = matches[0]
    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10
    return int(value) if value.is_integer() else value


def _concentration(value: Any) -> Optional[str]:
    text = norm(value)
    rules = (
        ("Extrait de Parfum", r"\bextrait(?: de)? parfum\b"),
        ("Eau de Parfum", r"\beau de parfum\b|\bedp\b"),
        ("Eau de Toilette", r"\beau de toilette\b|\bedt\b"),
        ("Eau de Cologne", r"\beau de cologne\b|\bedc\b"),
        ("Parfum", r"\bparfum\b"),
    )
    for label, pattern in rules:
        if re.search(pattern, text, re.I):
            return label
    return None


def _query_matches_product(name: str, query: str, extra: str = "") -> bool:
    """Strict generic identity check for a final product candidate."""
    if not clean(name):
        return False

    query_tokens = tokens(query, ignore_generic=True)
    if not query_tokens:
        return False

    name_text = f"{name} {extra}".strip()
    name_tokens = set(tokens(name_text))

    # Every meaningful query token must be represented by the candidate.
    if not all(token in name_tokens for token in query_tokens):
        return False

    requested_size = _query_size(query)
    if requested_size is not None:
        detected_size = _extract_size(name_text)
        if detected_size is not None and detected_size != requested_size:
            return False

    requested_concentration = _concentration(query)
    if requested_concentration:
        candidate_concentration = _concentration(name_text)
        if candidate_concentration and candidate_concentration != requested_concentration:
            return False

    return True


def _is_product_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
        return False
    return bool(re.search(r"/product/\d+(?:/|$)", parsed.path, re.I))


def _is_category_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
        return False
    return bool(re.search(r"/category/\d+(?:/|$)", parsed.path, re.I))


def _url_path_text(url: str) -> str:
    return unquote(urlparse(url).path.replace("/", " "))


def _parse_sitemap_locs(xml_text: str) -> List[str]:
    try:
        root = ET.fromstring(xml_text)
        return [
            clean(node.text)
            for node in root.iter()
            if node.tag.lower().endswith("loc") and clean(node.text)
        ]
    except (ET.ParseError, ValueError):
        return [
            clean(match.group(1))
            for match in re.finditer(r"<loc>\s*([^<]+?)\s*</loc>", xml_text or "", re.I)
        ]


def _get(session: requests.Session, url: str) -> Optional[requests.Response]:
    try:
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if response.status_code != 200 or not response.text:
        response.close()
        return None
    return response


def _sitemap_urls(session: requests.Session) -> List[str]:
    response = _get(session, SITEMAP_URL)
    if response is None:
        return []

    root_urls = _parse_sitemap_locs(response.text)
    response.close()

    child_sitemaps = [
        url for url in root_urls
        if url.lower().endswith((".xml", ".xml.gz")) and "sitemap" in url.lower()
    ]

    if not child_sitemaps:
        return root_urls

    output: List[str] = []
    for sitemap in child_sitemaps:
        response = _get(session, sitemap)
        if response is None:
            continue
        output.extend(_parse_sitemap_locs(response.text))
        response.close()

    return output


def _candidate_score(url: str, query: str) -> float:
    wanted = tokens(query, ignore_generic=True)
    path = _url_path_text(url)
    path_tokens = set(tokens(path))
    if not wanted:
        return 0.0

    score = sum(len(token) for token in wanted if token in path_tokens)
    if all(token in path_tokens for token in wanted):
        score += 100.0

    requested_size = _query_size(query)
    if requested_size is not None and _extract_size(path) == requested_size:
        score += 25.0

    requested_concentration = _concentration(query)
    if requested_concentration == _concentration(path):
        score += 15.0

    return score


def _discover_from_sitemap(session: requests.Session, query: str) -> Tuple[List[str], List[str]]:
    urls = _sitemap_urls(session)
    if not urls:
        return [], []

    product_candidates = []
    category_candidates = []
    seen_products = set()
    seen_categories = set()

    wanted = tokens(query, ignore_generic=True)
    if not wanted:
        return [], []

    for url in urls:
        if _is_product_url(url):
            if _contains_all_tokens(_url_path_text(url), wanted):
                canonical = url.split("#", 1)[0].split("?", 1)[0]
                if canonical not in seen_products:
                    seen_products.add(canonical)
                    product_candidates.append(canonical)
        elif _is_category_url(url):
            category_tokens = set(tokens(_url_path_text(url)))
            if not category_tokens:
                continue

            # A category slug can omit the brand even when the category page
            # contains the brand in its own product cards. Accept only a
            # meaningful token overlap here; the individual product card and
            # the final product page perform the strict full-query validation.
            weighted_total = sum(len(token) for token in wanted)
            weighted_overlap = sum(
                len(token) for token in wanted if token in category_tokens
            )
            category_match = (
                weighted_overlap == weighted_total
                or (len(wanted) >= 2 and weighted_overlap / max(weighted_total, 1) >= 0.5)
            )

            if category_match:
                canonical = url.split("#", 1)[0].split("?", 1)[0]
                if canonical not in seen_categories:
                    seen_categories.add(canonical)
                    category_candidates.append(canonical)

    product_candidates.sort(key=lambda url: _candidate_score(url, query), reverse=True)
    category_candidates.sort(key=lambda url: _candidate_score(url, query), reverse=True)

    return product_candidates[:MAX_PRODUCT_CANDIDATES], category_candidates[:MAX_CATEGORY_PAGES]


def _local_card_context(anchor) -> str:
    values = [
        anchor.get("title"),
        anchor.get("aria-label"),
        anchor.get("data-name"),
        anchor.get("data-product-name"),
        anchor.get_text(" ", strip=True),
    ]

    node = anchor
    for _ in range(5):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = clean(node.get_text(" ", strip=True))
        if text:
            values.append(text)
        if len(text) > 700:
            break

    return clean(" ".join(value for value in values if clean(value)))


def _discover_from_categories(session: requests.Session, categories: List[str], query: str) -> List[str]:
    wanted = tokens(query, ignore_generic=True)
    found: List[str] = []
    seen = set()

    for category_url in categories:
        response = _get(session, category_url)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        response.close()

        for anchor in soup.find_all("a", href=True):
            href = urljoin(BASE_URL, clean(anchor.get("href")))
            href = href.split("#", 1)[0].split("?", 1)[0]
            if not _is_product_url(href) or href in seen:
                continue

            context = _local_card_context(anchor)
            slug_context = _url_path_text(href)

            # Candidate is admitted only if the query is locally represented
            # by the product card/anchor or by the product URL itself.
            if not (
                _contains_all_tokens(context, wanted)
                or _contains_all_tokens(slug_context, wanted)
            ):
                continue

            seen.add(href)
            found.append(href)
            if len(found) >= MAX_PRODUCT_CANDIDATES:
                return found

    return found


def _jsonld_objects(soup: BeautifulSoup) -> Iterable[Dict[str, Any]]:
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue

        queue: List[Any] = [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
            elif isinstance(item, dict):
                yield item
                for value in item.values():
                    if isinstance(value, (dict, list)):
                        queue.append(value)


def _product_jsonld(soup: BeautifulSoup) -> Dict[str, Any]:
    for item in _jsonld_objects(soup):
        item_type = item.get("@type")
        types = item_type if isinstance(item_type, list) else [item_type]
        if any(str(value).lower() == "product" for value in types):
            return item
    return {}


def _jsonld_price(product: Dict[str, Any]) -> Optional[float]:
    offers = product.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        value = offer.get("price")
        if value in (None, ""):
            continue
        match = re.search(r"\d+(?:[.,]\d+)?", clean(value))
        if not match:
            continue
        try:
            amount = float(match.group(0).replace(",", "."))
        except ValueError:
            continue
        if 0 < amount < 10000:
            return round(amount, 2)
    return None


def _semantic_price(soup: BeautifulSoup) -> Optional[float]:
    selectors = [
        '[itemprop="price"]',
        'meta[property="product:price:amount"]',
        'meta[itemprop="price"]',
        '[data-price]',
        '[data-product-price]',
        '.product-price',
        '.product_price',
        '.current-price',
        '.current_price',
        '.final-price',
        '.final_price',
        '.sale-price',
        '.sale_price',
    ]

    candidates: List[Tuple[int, float]] = []
    for selector in selectors:
        for node in soup.select(selector):
            raw = node.get("content") or node.get("data-price") or node.get("data-product-price") or node.get_text(" ", strip=True)
            match = re.search(r"\d+(?:[.,]\d{1,2})?", clean(raw))
            if not match:
                continue
            try:
                amount = float(match.group(0).replace(",", "."))
            except ValueError:
                continue
            if not 0 < amount < 10000:
                continue

            marker = (
                " ".join(node.get("class", []))
                + " "
                + str(node.get("id", ""))
            ).lower()
            score = 0
            if "product" in marker:
                score += 20
            if any(word in marker for word in ("current", "final", "sale")):
                score += 15
            if node.find_parent(["del", "s", "strike"]):
                score -= 50
            if any(word in marker for word in ("old-price", "list-price", "compare-price", "coupon", "discount", "voucher")):
                score -= 40
            candidates.append((score, amount))

    if not candidates:
        return None
    candidates.sort(key=lambda pair: (pair[0], -pair[1]), reverse=True)
    return round(candidates[0][1], 2)


def _availability(product: Dict[str, Any], soup: BeautifulSoup) -> str:
    offers = product.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        raw = clean(offer.get("availability") or offer.get("availabilityStatus") or "")
        text = norm(raw)
        if any(value in text for value in ("instock", "in stock", "available")):
            return "in_stock"
        if any(value in text for value in ("outofstock", "out of stock", "soldout", "sold out", "unavailable")):
            return "out_of_stock"

    for node in soup.select('[itemprop="availability"], meta[property="product:availability"], meta[name="availability"]'):
        text = norm(node.get("content") or node.get_text(" ", strip=True))
        if any(value in text for value in ("instock", "in stock", "available")):
            return "in_stock"
        if any(value in text for value in ("outofstock", "out of stock", "soldout", "sold out", "unavailable")):
            return "out_of_stock"

    return "unknown"


def _brand_name(product: Dict[str, Any], soup: BeautifulSoup) -> Optional[str]:
    brand = product.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    brand = clean(brand)
    if brand:
        return brand

    for selector in ('[itemprop="brand"]', '.brand', '.product-brand'):
        node = soup.select_one(selector)
        if node:
            value = clean(node.get("content") or node.get_text(" ", strip=True))
            if value:
                return value
    return None


def _selected_size(soup: BeautifulSoup, product: Dict[str, Any], name: str) -> Optional[float]:
    size = _extract_size(name)
    if size is not None:
        return size

    selectors = [
        'input[type="radio"][checked]',
        'input[type="radio"][aria-checked="true"]',
        'input[checked][name*="size" i]',
        'option[selected]',
        '[aria-selected="true"]',
    ]
    for selector in selectors:
        for node in soup.select(selector):
            values = [
                node.get("value"),
                node.get("aria-label"),
                node.get("data-value"),
                node.get("data-size"),
                node.get_text(" ", strip=True),
            ]
            parent = getattr(node, "parent", None)
            if parent:
                values.append(parent.get_text(" ", strip=True))
            value = _extract_size(*values)
            if value is not None:
                return value

    for key in ("name", "description", "category"):
        value = product.get(key)
        size = _extract_size(value)
        if size is not None:
            return size

    return None


def _extract_product(session: requests.Session, url: str, query: str) -> Optional[Dict[str, Any]]:
    response = _get(session, url)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    response.close()

    h1 = soup.find("h1")
    h1_name = clean(h1.get_text(" ", strip=True)) if h1 else ""
    product = _product_jsonld(soup)
    structured_name = clean(product.get("name"))
    name = h1_name or structured_name

    if not name:
        return None

    brand = _brand_name(product, soup)
    product_line = ""
    page_text = clean(soup.get_text(" ", strip=True))
    match = re.search(
        r"product line\s+(.+?)(?:for whom|fragrance type|season|spray|article number|product information)",
        page_text,
        re.I,
    )
    if match:
        product_line = clean(match.group(1))

    # Identity is validated against the actual product title, with structured
    # product-line/brand context only as supplementary evidence.
    extra = " ".join(value for value in (brand, product_line) if value)
    if not _query_matches_product(name, query, extra=extra):
        return None

    size = _selected_size(soup, product, name)
    requested_size = _query_size(query)
    if requested_size is not None and size is not None and size != requested_size:
        return None

    price = _jsonld_price(product)
    if price is None:
        price = _semantic_price(soup)
    if price is None:
        return None

    image = product.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    image = urljoin(url, clean(image)) if image else None

    gtin = clean(product.get("gtin13") or product.get("gtin") or "") or None
    sku = clean(product.get("sku") or "") or None
    mpn = clean(product.get("mpn") or "") or None
    availability = _availability(product, soup)
    concentration = _concentration(name)

    # Product pages must expose clear product signals. This prevents a generic
    # internal page with an H1 and incidental price from becoming a result.
    has_product_identity = bool(product) or bool(h1)
    has_offer_signal = price is not None
    if not (has_product_identity and has_offer_signal):
        return None

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand,
            "url": url,
            "image": image,
        },
        "identity": {
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
            "mpn": {"value": mpn, "source": "jsonld"} if mpn else None,
            "sku": {"value": sku, "source": "jsonld"} if sku else None,
            "store_product_id": {"value": sku, "source": "deloox_sku"} if sku else None,
        },
        "attributes": {
            "size_ml": {"value": size, "source": "product_page"} if size is not None else None,
            "concentration": {"value": concentration, "source": "product_title"} if concentration else None,
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
            "product_line": {"value": product_line, "source": "deloox_page"} if product_line else None,
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": availability,
        },
        "provenance": {
            "source_page": url,
            "product_source": "jsonld_or_product_page",
        },
        "raw_data": {"jsonld": product},
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": availability == "in_stock",
    }


def search(query: str) -> List[Dict[str, Any]]:
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        product_urls, category_urls = _discover_from_sitemap(session, query)

        # Category pages are a bounded discovery fallback. They are never
        # crawled recursively and only product URLs from those pages are used.
        category_product_urls = _discover_from_categories(session, category_urls, query)

        ordered_urls: List[str] = []
        seen = set()
        for url in product_urls + category_product_urls:
            if url not in seen:
                seen.add(url)
                ordered_urls.append(url)

        results: List[Dict[str, Any]] = []
        result_keys = set()

        for url in ordered_urls[:MAX_PRODUCT_CANDIDATES]:
            item = _extract_product(session, url, query)
            if not item:
                continue

            key = (
                item.get("url", "").lower(),
                norm(item.get("name", "")),
                (item.get("attributes") or {}).get("size_ml", {}).get("value")
                if isinstance((item.get("attributes") or {}).get("size_ml"), dict)
                else None,
            )
            if key in result_keys:
                continue
            result_keys.add(key)
            results.append(item)

        return results
    finally:
        session.close()


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generic Deloox store adapter")
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
