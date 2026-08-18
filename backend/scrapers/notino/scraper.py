import json
import re
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_PATH = "/search.asp"
TIMEOUT = 25
SCRAPER_VERSION = "notino-diagnostic-2026-08-18-v1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

PRODUCT_ID_RE = re.compile(r"/p-(\d+)(?:/|$)", re.I)
PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*€")
SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*ml\b", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def same_host(url):
    try:
        host = urlparse(url).netloc.lower()
        return host == "notino.fr" or host.endswith(".notino.fr")
    except Exception:
        return False


def query_tokens(query):
    ignored = {
        "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
        "spray", "pour", "homme", "femme", "mixte", "men", "women",
        "for", "by"
    }
    return [
        token for token in norm(query).split()
        if len(token) > 1 and token not in ignored
    ]


def explicit_size(query):
    match = SIZE_RE.search(norm(query))
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return int(value) if value.is_integer() else value


def extract_size(*texts):
    for text in texts:
        match = SIZE_RE.search(str(text or ""))
        if match:
            value = float(match.group(1).replace(",", "."))
            return int(value) if value.is_integer() else value
    return None


def extract_jsonld(soup):
    objects = []
    for script in soup.find_all(
        "script",
        attrs={"type": re.compile(r"application/ld\+json", re.I)}
    ):
        raw = script.string or script.get_text()
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError, AttributeError):
            continue

        if isinstance(data, list):
            objects.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            objects.append(data)

    return objects


def product_jsonld(soup):
    for data in extract_jsonld(soup):
        types = data.get("@type")
        types = types if isinstance(types, list) else [types]
        if any(str(x).lower() == "product" for x in types):
            return data
    return None


def anchor_text(anchor):
    values = [
        anchor.get("title"),
        anchor.get("aria-label"),
        anchor.get_text(" ", strip=True),
    ]
    image = anchor.find("img")
    if image:
        values.extend([image.get("alt"), image.get("title")])
    return clean(" ".join(x for x in values if clean(x)))


def path_matches_query(url, query):
    path = norm(urlparse(url).path)
    tokens = query_tokens(query)
    return bool(tokens) and all(token in path for token in tokens)


def text_matches_query(text, query):
    value = norm(text)
    tokens = query_tokens(query)
    return bool(tokens) and all(token in value for token in tokens)


def candidate_kind(url):
    if PRODUCT_ID_RE.search(urlparse(url).path):
        return "product_id"

    path = urlparse(url).path.rstrip("/")
    if path in {"", "/search", "/search.asp"}:
        return "other"

    return "canonical_or_listing"


def extract_candidate_links(soup, page_url, query):
    candidates = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if not href:
            continue

        url = urljoin(page_url, href.split("#", 1)[0])
        if not same_host(url):
            continue

        path = urlparse(url).path.rstrip("/")
        if path in {"", "/search", "/search.asp"}:
            continue

        text = anchor_text(anchor)
        url_match = path_matches_query(url, query)
        text_match = text_matches_query(text, query)

        if not (url_match or text_match):
            continue

        key = url.lower()
        if key in seen:
            continue

        seen.add(key)
        candidates.append({
            "url": url.split("?", 1)[0],
            "text": text,
            "kind": candidate_kind(url),
            "url_match": url_match,
            "text_match": text_match,
        })

    return candidates


def page_diagnostics(soup):
    full_text = clean(soup.get_text(" ", strip=True))
    product_ld = product_jsonld(soup)

    product_links = 0
    for anchor in soup.find_all("a", href=True):
        href = urljoin(BASE_URL, clean(anchor.get("href")))
        if PRODUCT_ID_RE.search(urlparse(href).path):
            product_links += 1

    listing_markers = {
        "products_label": bool(re.search(r"\bproduits\s*:", full_text, re.I)),
        "filters": bool(
            re.search(
                r"\bFiltres\b.*\bPrix\b.*\bPour qui\b",
                full_text,
                re.I | re.S,
            )
        ),
        "sort": bool(re.search(r"\bLe plus pertinent\b", full_text, re.I)),
        "pagination": bool(re.search(r"\b1\s+2\s+3\b", full_text)),
    }

    product_markers = {
        "product_jsonld": product_ld is not None,
        "add_to_cart": bool(
            re.search(r"\bAjouter au panier\b", full_text, re.I)
        ),
        "stock": bool(
            re.search(r"\bEn stock\b|\bRupture de stock\b", full_text, re.I)
        ),
        "code": bool(re.search(r"\bCode\s*:", full_text, re.I)),
        "size_ml": bool(SIZE_RE.search(full_text)),
    }

    listing_score = sum(listing_markers.values())
    product_score = sum(product_markers.values())

    # A listing/category page must never be accepted as a product merely
    # because it has an H1 matching the query. Notino canonical landing
    # pages can have a product-looking H1 while containing several products.
    if listing_score >= 2 or product_links >= 2:
        page_type = "listing_or_landing"
    elif product_score >= 2:
        page_type = "product"
    else:
        page_type = "unknown"

    return {
        "page_type": page_type,
        "listing_score": listing_score,
        "product_score": product_score,
        "product_links": product_links,
        "listing_markers": listing_markers,
        "product_markers": product_markers,
        "jsonld_types": [
            data.get("@type")
            for data in extract_jsonld(soup)
            if isinstance(data, dict)
        ],
    }


def fetch(session, url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        print(
            f"NOTINO_HTTP: status={response.status_code} "
            f"url={response.url} bytes={len(response.content)}",
            flush=True,
        )
        if not response.ok or not same_host(response.url):
            return None
        return response
    except requests.RequestException as exc:
        print(f"NOTINO_HTTP_ERROR: url={url} error={exc}", flush=True)
        return None


def extract_name(soup, data=None):
    if isinstance(data, dict) and clean(data.get("name")):
        return clean(data["name"])

    node = soup.select_one("h1")
    if node and clean(node.get_text(" ", strip=True)):
        return clean(node.get_text(" ", strip=True))

    node = soup.select_one('meta[property="og:title"]')
    if node and clean(node.get("content")):
        return clean(node.get("content"))

    return ""


def extract_brand(soup, data=None):
    if isinstance(data, dict):
        brand = data.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        if clean(brand):
            return clean(brand)

    for selector in (
        '[itemprop="brand"]',
        '[data-testid*="brand" i]',
    ):
        node = soup.select_one(selector)
        if node:
            value = clean(node.get("content") or node.get_text(" ", strip=True))
            if value:
                return value

    return ""


def extract_image(soup, data=None):
    if isinstance(data, dict):
        image = data.get("image")
        if isinstance(image, list):
            image = next((x for x in image if clean(x)), None)
        if clean(image):
            return urljoin(BASE_URL, clean(image))

    node = soup.select_one('meta[property="og:image"]')
    if node and clean(node.get("content")):
        return urljoin(BASE_URL, clean(node.get("content")))

    return ""


def extract_price(soup, data=None):
    if isinstance(data, dict):
        offers = data.get("offers")
        offers = offers if isinstance(offers, list) else [offers]
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            value = offer.get("price") or offer.get("lowPrice")
            if value is not None:
                try:
                    return round(float(str(value).replace(",", ".")), 2)
                except ValueError:
                    pass

    for selector in (
        'meta[itemprop="price"]',
        'meta[property="product:price:amount"]',
        '[data-price]',
        '[data-testid*="price" i]',
        "[class*='price' i]",
    ):
        for node in soup.select(selector):
            raw = node.get("content") or node.get("data-price")
            raw = raw or node.get_text(" ", strip=True)
            match = PRICE_RE.search(clean(raw))
            if match:
                try:
                    return round(
                        float(match.group(1).replace(".", "").replace(",", ".")),
                        2,
                    )
                except ValueError:
                    continue

    return None


def extract_concentration(text):
    value = norm(text)
    if "extrait de parfum" in value or re.search(r"\bextrait\b", value):
        return "Extrait de Parfum"
    if "eau de parfum" in value:
        return "Eau de Parfum"
    if "eau de toilette" in value:
        return "Eau de Toilette"
    if "eau de cologne" in value:
        return "Eau de Cologne"
    if re.search(r"\bparfum\b", value):
        return "Parfum"
    return None


def extract_gender(text):
    value = norm(text)
    if re.search(r"\b(homme|men|male|pour homme)\b", value):
        return "men"
    if re.search(r"\b(femme|women|female|pour femme)\b", value):
        return "women"
    if re.search(r"\b(mixte|unisex|unisexe)\b", value):
        return "unisex"
    return "unknown"


def extract_sku(soup, data=None):
    if isinstance(data, dict):
        for key in ("sku", "mpn", "gtin", "gtin13", "gtin12", "gtin14"):
            value = clean(data.get(key))
            if value:
                return key, value

    for selector in (
        '[itemprop="sku"]',
        '[itemprop="gtin13"]',
        '[itemprop="gtin"]',
    ):
        node = soup.select_one(selector)
        if node:
            value = clean(node.get("content") or node.get_text(" ", strip=True))
            if value:
                return selector, value

    return None, None


def extract_availability(soup, data=None):
    values = []

    if isinstance(data, dict):
        offers = data.get("offers")
        offers = offers if isinstance(offers, list) else [offers]
        for offer in offers:
            if isinstance(offer, dict):
                values.append(offer.get("availability"))

    values.extend(
        node.get("content") or node.get_text(" ", strip=True)
        for node in soup.select(
            '[itemprop="availability"], [data-testid*="availability" i]'
        )
    )

    text = norm(" ".join(str(x or "") for x in values))
    visible = norm(soup.get_text(" ", strip=True))

    if "instock" in text or "en stock" in text or "disponible" in text:
        return "in_stock"
    if "outofstock" in text or "rupture" in text or "indisponible" in text:
        return "out_of_stock"

    if "en stock" in visible:
        return "in_stock"
    if "rupture de stock" in visible:
        return "out_of_stock"

    return "unknown"


def validate_product_page(response, query):
    soup = BeautifulSoup(response.text, "html.parser")
    diagnostics = page_diagnostics(soup)

    print(
        f"NOTINO_PAGE: url={response.url} "
        f"type={diagnostics['page_type']} "
        f"listing_score={diagnostics['listing_score']} "
        f"product_score={diagnostics['product_score']} "
        f"product_links={diagnostics['product_links']}",
        flush=True,
    )

    if diagnostics["page_type"] != "product":
        print(
            f"NOTINO_PAGE: NOT_PRODUCT url={response.url} "
            f"markers={diagnostics['product_markers']} "
            f"listing={diagnostics['listing_markers']}",
            flush=True,
        )
        return None

    data = product_jsonld(soup)
    name = extract_name(soup, data)
    brand = extract_brand(soup, data)
    text = soup.get_text(" ", strip=True)
    size_ml = extract_size(name, text)
    concentration = extract_concentration(text)
    gender = extract_gender(text)
    price = extract_price(soup, data)
    image = extract_image(soup, data)
    availability = extract_availability(soup, data)
    id_key, id_value = extract_sku(soup, data)

    tokens = query_tokens(query)
    identity = norm(f"{name} {brand}")
    query_match = bool(tokens) and all(token in identity for token in tokens)

    requested_size = explicit_size(query)
    size_match = (
        requested_size is None
        or size_ml is None
        or float(requested_size) == float(size_ml)
    )

    print(
        f"NOTINO_PRODUCT_DATA: name={name!r} brand={brand!r} "
        f"size={size_ml!r} concentration={concentration!r} "
        f"price={price!r} availability={availability!r} "
        f"query_match={query_match} size_match={size_match} "
        f"id={id_key}:{id_value}",
        flush=True,
    )

    if not name or not query_match or not size_match:
        print(
            f"NOTINO_VALIDATE: REJECT url={response.url} "
            f"name={name!r} brand={brand!r}",
            flush=True,
        )
        return None

    product_id_match = PRODUCT_ID_RE.search(urlparse(response.url).path)
    product_id = product_id_match.group(1) if product_id_match else None

    identity_data = {
        "gtin": None,
        "mpn": None,
        "sku": None,
        "store_product_id": product_id,
        "store_variant_id": None,
    }

    if id_key in {"gtin", "gtin13", "gtin12", "gtin14"}:
        identity_data["gtin"] = id_value
    elif id_key == "mpn":
        identity_data["mpn"] = id_value
    elif id_key == "sku":
        identity_data["sku"] = id_value

    result = {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand or None,
            "url": response.url.split("?", 1)[0],
            "image": image or None,
        },
        "identity": identity_data,
        "attributes": {
            "size_ml": {"value": size_ml, "source": "product_page"},
            "concentration": {
                "value": concentration,
                "source": "product_page",
            },
            "gender": {"value": gender, "source": "product_page"},
            "packaging_type": {
                "value": "product",
                "source": "product_page",
            },
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": availability,
        },
        "provenance": {
            "source_page": response.url.split("?", 1)[0],
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
        "brand": brand,
        "price": (
            f"{price:.2f}".replace(".", ",") + " €"
            if price is not None
            else ""
        ),
        "url": response.url.split("?", 1)[0],
        "image": image,
        "available": availability == "in_stock",
    }

    print(
        f"NOTINO_VALIDATE: ACCEPT name={name!r} "
        f"brand={brand!r} url={response.url}",
        flush=True,
    )
    return result


def discover_from_page(session, page_response, query, visited):
    """
    Diagnose the opened page first. If it is a real product page, validate it.
    If it is a listing/landing page, discover its child product links and
    validate those pages. This deliberately separates page classification from
    product extraction.
    """
    url = page_response.url.split("?", 1)[0]
    if url.lower() in visited:
        return []

    visited.add(url.lower())

    soup = BeautifulSoup(page_response.text, "html.parser")
    diagnostics = page_diagnostics(soup)

    print(
        f"NOTINO_DISCOVERY_PAGE: url={url} "
        f"type={diagnostics['page_type']} "
        f"product_links={diagnostics['product_links']}",
        flush=True,
    )

    if diagnostics["page_type"] == "product":
        product = validate_product_page(page_response, query)
        return [product] if product else []

    nested = extract_candidate_links(soup, page_response.url, query)

    print(
        f"NOTINO_NESTED_DISCOVERY: url={url} "
        f"candidates={len(nested)}",
        flush=True,
    )

    for index, candidate in enumerate(nested, 1):
        print(
            f"NOTINO_NESTED[{index}]: kind={candidate['kind']} "
            f"url_match={candidate['url_match']} "
            f"text_match={candidate['text_match']} "
            f"url={candidate['url']} "
            f"text={candidate['text'][:180]!r}",
            flush=True,
        )

    results = []

    for candidate in nested:
        candidate_url = candidate["url"]

        if candidate_url.lower() in visited:
            continue

        print(
            f"NOTINO_OPEN_CANDIDATE: url={candidate_url}",
            flush=True,
        )

        child = fetch(session, candidate_url)
        if child is None:
            print(
                f"NOTINO_OPEN_CANDIDATE: FAILED url={candidate_url}",
                flush=True,
            )
            continue

        child_product = validate_product_page(child, query)

        if child_product:
            results.append(child_product)
            continue

        # If this is another generic landing page, recurse one level further.
        child_soup = BeautifulSoup(child.text, "html.parser")
        child_diag = page_diagnostics(child_soup)

        if child_diag["page_type"] == "listing_or_landing":
            results.extend(
                discover_from_page(session, child, query, visited)
            )

    return results


def search(query):
    query = clean(query)

    print(f"NOTINO_SCRAPER_VERSION: {SCRAPER_VERSION}", flush=True)
    print(f"NOTINO_SEARCH: START query={query!r}", flush=True)

    if not query:
        return []

    session = requests.Session()
    visited = set()
    results = []
    seen = set()

    try:
        # Step 1: homepage — diagnostic only.
        homepage = fetch(session, BASE_URL)
        if homepage is not None:
            home_soup = BeautifulSoup(homepage.text, "html.parser")
            print(
                f"NOTINO_DIAG_HOMEPAGE: title={clean(home_soup.title.get_text()) if home_soup.title else ''!r} "
                f"bytes={len(homepage.content)}",
                flush=True,
            )

        # Step 2: the real Notino search endpoint.
        response = fetch(
            session,
            urljoin(BASE_URL, SEARCH_PATH),
            params={"exps": query},
        )

        if response is None:
            print("NOTINO_SEARCH: SEARCH_HTTP_FAILED", flush=True)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        diag = page_diagnostics(soup)

        print(
            f"NOTINO_SEARCH_PAGE: url={response.url} "
            f"title={clean(soup.title.get_text()) if soup.title else ''!r} "
            f"page_type={diag['page_type']} "
            f"product_links={diag['product_links']} "
            f"listing_score={diag['listing_score']} "
            f"product_score={diag['product_score']}",
            flush=True,
        )

        # Step 3: discovery on the search page.
        candidates = extract_candidate_links(soup, response.url, query)

        print(
            f"NOTINO_DISCOVERY: search_candidates={len(candidates)}",
            flush=True,
        )

        for index, candidate in enumerate(candidates, 1):
            print(
                f"NOTINO_CANDIDATE[{index}]: "
                f"kind={candidate['kind']} "
                f"url_match={candidate['url_match']} "
                f"text_match={candidate['text_match']} "
                f"url={candidate['url']} "
                f"text={candidate['text'][:180]!r}",
                flush=True,
            )

        # Step 4: open every discovered candidate. Do not decide that a
        # canonical URL is a product before opening it.
        for candidate in candidates:
            url = candidate["url"]

            if url.lower() in visited:
                continue

            print(
                f"NOTINO_OPEN: candidate={url}",
                flush=True,
            )

            page = fetch(session, url)
            if page is None:
                print(
                    f"NOTINO_OPEN: FAILED url={url}",
                    flush=True,
                )
                continue

            page_product = validate_product_page(page, query)

            if page_product:
                key = (
                    page_product["url"].lower(),
                    norm(page_product["name"]),
                    page_product["attributes"]["size_ml"]["value"],
                )
                if key not in seen:
                    seen.add(key)
                    results.append(page_product)
                continue

            # Step 5: if it was a landing/category page, discover the real
            # product URLs from inside it.
            nested_results = discover_from_page(
                session, page, query, visited
            )

            for product in nested_results:
                key = (
                    product["url"].lower(),
                    norm(product["name"]),
                    product["attributes"]["size_ml"]["value"],
                )
                if key not in seen:
                    seen.add(key)
                    results.append(product)

        print(
            f"NOTINO_SEARCH: END query={query!r} results={len(results)}",
            flush=True,
        )
        return results

    finally:
        session.close()


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
