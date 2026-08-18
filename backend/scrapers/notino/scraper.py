import json
import re
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_PATH = "/search.asp"
TIMEOUT = 20

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
PRICE_RE = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))(?:\s*€)?")
SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", re.I)
ABSOLUTE_PRODUCT_RE = re.compile(
    r'(?:https?:)?//(?:www\.)?notino\.fr/[^"\'<>\s\\]+/p-\d+/?',
    re.I,
)
RELATIVE_PRODUCT_RE = re.compile(
    r'(?:(?:"|\'|=))(/[^"\'<>\s\\]+/p-\d+/?)',
    re.I,
)

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "for", "pour", "homme", "femme",
    "men", "women", "mixte", "unisex", "unisexe",
}

NON_PRODUCT_TERMS = {
    "gift set", "set regalo", "coffret", "bundle",
    "deodorant", "deo spray", "shower gel", "body lotion",
    "after shave", "aftershave", "travel set",
    "discovery set", "kit", "body mist", "hand cream",
}

PATH_EXCLUSIONS = {
    "search.asp", "search", "marche", "marques", "brand",
    "brands", "categorie", "categories", "parfums", "parfum",
    "visage", "corps", "cheveux", "maquillage", "hommes",
    "femmes", "nouveautes", "promotions", "solde", "avis",
    "inspirations", "blog", "magazine", "livraison",
    "contact", "login", "account", "panier", "wishlist",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(
        char for char in value if not unicodedata.combining(char)
    ).lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def same_host(url):
    try:
        host = urlparse(url).netloc.lower()
        return host in {"notino.fr", "www.notino.fr"}
    except Exception:
        return False


def normalise_url(href, base_url=BASE_URL):
    href = clean(href)
    if not href:
        return None

    href = href.replace("\\/", "/").replace("\\u002F", "/")

    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(base_url, href)

    parsed = urlparse(href)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not same_host(href):
        return None

    path = parsed.path.rstrip("/")
    if not path or path == "/":
        return None
    if path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".svg")):
        return None

    return f"{parsed.scheme}://{parsed.netloc}{path}"


def product_url(url):
    if not same_host(url):
        return False

    path = urlparse(url).path.strip("/").lower()
    if not path:
        return False

    first = path.split("/", 1)[0]
    if first in PATH_EXCLUSIONS:
        return False

    if PRODUCT_ID_RE.search("/" + path + "/"):
        return True

    segments = [x for x in path.split("/") if x]
    if len(segments) < 2:
        return False

    return segments[-1] not in PATH_EXCLUSIONS


def query_tokens(query):
    return [
        token
        for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS
    ]


def explicit_size(query):
    match = SIZE_RE.search(norm(query))
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10
    return int(value) if value.is_integer() else value


def extract_size_ml(*texts):
    for text in texts:
        match = SIZE_RE.search(str(text or ""))
        if not match:
            continue
        value = float(match.group(1).replace(",", "."))
        if match.group(2).lower() == "cl":
            value *= 10
        return int(value) if value.is_integer() else value
    return None


def extract_concentration(*texts):
    for text in texts:
        value = norm(text)
        if re.search(r"\bextrait de parfum\b|\bextrait\b", value):
            return "Extrait de Parfum"
        if re.search(r"\beau de parfum\b|\bedp\b", value):
            return "Eau de Parfum"
        if re.search(r"\beau de toilette\b|\bedt\b", value):
            return "Eau de Toilette"
        if re.search(r"\beau de cologne\b", value):
            return "Eau de Cologne"
        if re.search(r"\bparfum\b", value):
            return "Parfum"
    return None


def extract_gender(*texts):
    value = norm(" ".join(str(x or "") for x in texts))
    if re.search(r"\b(men|homme|pour homme)\b", value):
        return "men"
    if re.search(r"\b(women|femme|pour femme)\b", value):
        return "women"
    if re.search(r"\b(unisex|unisexe|mixte)\b", value):
        return "unisex"
    return "unknown"


def extract_json_ld(soup):
    objects = []
    for script in soup.find_all(
        "script",
        attrs={"type": re.compile(r"application/ld\+json", re.I)},
    ):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            objects.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            objects.append(data)

    return [
        obj for obj in objects
        if str(obj.get("@type", "")).lower() == "product"
    ]


def product_name(soup, data):
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

    return clean(soup.title.get_text(" ", strip=True)) if soup.title else ""


def product_brand(data):
    if not isinstance(data, dict):
        return ""
    brand = data.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    return clean(brand)


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def find_product_data(products, query):
    wanted = query_tokens(query)
    if not wanted:
        return products[0] if products else {}

    for data in products:
        name = clean(data.get("name"))
        identity = norm(" ".join((name, product_brand(data))))
        if name and all(token in identity for token in wanted):
            return data

    return products[0] if products else {}


def parse_price(value):
    if value is None:
        return None

    text = clean(value).replace("\xa0", " ")
    match = PRICE_RE.search(text)
    if not match:
        return None

    raw = match.group(1).replace(" ", "")
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")

    try:
        number = float(raw)
    except ValueError:
        return None

    return round(number, 2) if 0 < number < 10000 else None


def extract_price(soup, data):
    if isinstance(data, dict):
        offers = data.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        if isinstance(offers, list):
            for offer in offers:
                if isinstance(offer, dict):
                    price = parse_price(offer.get("price"))
                    if price is not None:
                        return price

    for selector in (
        'meta[itemprop="price"]',
        'meta[property="product:price:amount"]',
        '[data-price]',
    ):
        for node in soup.select(selector):
            price = parse_price(
                node.get("content")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )
            if price is not None:
                return price

    text = soup.get_text(" ", strip=True)
    for match in PRICE_RE.finditer(text):
        price = parse_price(match.group(1))
        if price is not None:
            return price

    return None


def extract_availability(soup, data):
    values = []
    if isinstance(data, dict):
        offers = data.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        if isinstance(offers, list):
            values.extend(
                offer.get("availability")
                for offer in offers
                if isinstance(offer, dict)
            )

    for selector in (
        '[itemprop="availability"]',
        'meta[property="product:availability"]',
        'meta[name="availability"]',
    ):
        for node in soup.select(selector):
            values.append(
                node.get("content") or node.get_text(" ", strip=True)
            )

    for raw in values:
        value = norm(raw)
        if any(x in value for x in (
            "instock", "in stock", "available", "disponible", "en stock",
        )):
            return "in_stock"
        if any(x in value for x in (
            "outofstock", "out of stock", "soldout", "sold out",
            "unavailable", "indisponible", "rupture", "epuise",
        )):
            return "out_of_stock"

    return "unknown"


def image_from_product(soup, data, page_url):
    image = data.get("image") if isinstance(data, dict) else None
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")

    if not image:
        node = soup.select_one('meta[property="og:image"]')
        image = node.get("content") if node else ""

    image = clean(image)
    return urljoin(page_url, image) if image else ""


def selected_size(soup, data, name):
    size = extract_size_ml(
        name,
        data.get("name") if isinstance(data, dict) else "",
    )
    if size is not None:
        return size

    for selector in (
        'input[type="radio"][checked]',
        'input[type="radio"][aria-checked="true"]',
        'input[checked][name*="size" i]',
        "option[selected]",
        '[aria-selected="true"]',
    ):
        for node in soup.select(selector):
            blob = " ".join((
                node.get("value", ""),
                node.get("aria-label", ""),
                node.get("data-value", ""),
                node.get("data-size", ""),
                node.get_text(" ", strip=True),
            ))
            size = extract_size_ml(blob)
            if size is not None:
                return size

    return None


def query_matches_product(name, query, brand="", size_ml=None, url=""):
    if not name or not norm(query) or not product_url(url):
        return False

    wanted = query_tokens(query)
    if not wanted:
        return False

    identity = norm(" ".join((name, brand)))
    if not all(token in identity for token in wanted):
        return False

    requested_size = explicit_size(query)
    if requested_size is not None and size_ml is not None:
        if float(requested_size) != float(size_ml):
            return False

    name_only = norm(name)
    for phrase in NON_PRODUCT_TERMS:
        if norm(phrase) in name_only and norm(phrase) not in norm(query):
            return False

    return True


def extract_search_candidates(soup, page_url, raw_html=""):
    candidates = []
    seen = set()

    def add(raw_url):
        url = normalise_url(raw_url, page_url)
        if not url or not product_url(url):
            return
        if url in seen:
            return
        seen.add(url)
        candidates.append(url)

    for anchor in soup.find_all("a", href=True):
        add(anchor.get("href"))

    canonical = soup.select_one('link[rel="canonical"]')
    if canonical:
        add(canonical.get("href"))

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        for obj in walk_json(data):
            if not isinstance(obj, dict):
                continue
            for key in ("url", "@id"):
                value = obj.get(key)
                if isinstance(value, str):
                    add(value)
            item = obj.get("item")
            if isinstance(item, dict):
                for key in ("url", "@id"):
                    value = item.get(key)
                    if isinstance(value, str):
                        add(value)

    decoded = (raw_html or "").replace("\\/", "/").replace("\\u002F", "/")
    for raw_url in ABSOLUTE_PRODUCT_RE.findall(decoded):
        add(raw_url)
    for raw_url in RELATIVE_PRODUCT_RE.findall(decoded):
        add(raw_url)

    return candidates


def fetch(session, url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None

    if not response.ok or not same_host(response.url):
        return None

    return response


def parse_product_page(response, query):
    soup = BeautifulSoup(response.text, "html.parser")
    products = extract_json_ld(soup)
    data = find_product_data(products, query)

    name = product_name(soup, data)
    brand = product_brand(data)

    if not brand:
        brand_node = soup.select_one(
            '[itemprop="brand"], [data-brand], meta[property="product:brand"]'
        )
        if brand_node:
            brand = clean(
                brand_node.get("content")
                or brand_node.get("data-brand")
                or brand_node.get_text(" ", strip=True)
            )

    page_text = soup.get_text(" ", strip=True)
    size = selected_size(soup, data, name)
    if size is None:
        size = extract_size_ml(page_text)

    url = normalise_url(response.url)

    if not query_matches_product(
        name,
        query,
        brand=brand,
        size_ml=size,
        url=url,
    ):
        return None

    price = extract_price(soup, data)
    if price is None:
        return None

    concentration = extract_concentration(name)
    gender = extract_gender(name, page_text)
    availability = extract_availability(soup, data)
    image = image_from_product(soup, data, url)

    product_id_match = PRODUCT_ID_RE.search(url or "")
    product_id = (
        product_id_match.group(1)
        if product_id_match
        else None
    )

    gtin = (
        clean(data.get("gtin13") or data.get("gtin") or "")
        if isinstance(data, dict)
        else ""
    )
    mpn = clean(data.get("mpn") or "") if isinstance(data, dict) else ""
    sku = clean(data.get("sku") or "") if isinstance(data, dict) else ""

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": brand or None,
            "url": url,
            "image": image or None,
        },
        "identity": {
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
            "mpn": {"value": mpn, "source": "jsonld"} if mpn else None,
            "sku": {"value": sku, "source": "jsonld"} if sku else None,
            "store_product_id": product_id,
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {
                "value": size,
                "source": "selected_variant_or_product_name",
            },
            "concentration": {
                "value": concentration,
                "source": "product_name",
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
            "size_ml": size,
            "concentration": concentration,
            "gender": gender,
        },
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": url,
        "image": image,
        "available": availability == "in_stock",
    }


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    try:
        response = fetch(
            session,
            urljoin(BASE_URL, SEARCH_PATH),
            params={"exps": query},
        )
        if response is None:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        candidates = extract_search_candidates(
            soup,
            response.url,
            response.text,
        )

        results = []
        seen = set()

        for url in candidates:
            if url in seen:
                continue
            seen.add(url)

            product_response = fetch(session, url)
            if product_response is None:
                continue

            product = parse_product_page(product_response, query)
            if product is None:
                continue

            key = (
                product["url"].lower(),
                norm(product["name"]),
            )
            if key in seen:
                continue

            seen.add(key)
            results.append(product)

        return results
    except Exception:
        return []
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
