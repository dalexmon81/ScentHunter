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
MAX_CANDIDATES = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.6 Mobile/15E148 Safari/604.1"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
}

PRODUCT_ID_RE = re.compile(r"/p-(\d+)(?:/|$)", re.I)
SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", re.I)
PRICE_RE = re.compile(
    r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))(?:\s*€)?"
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
    value = re.sub(
        r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)",
        " ",
        value,
    )
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

    href = (
        href.replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("&amp;", "&")
    )

    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(base_url, href)
    elif not re.match(r"^https?://", href, re.I):
        href = urljoin(base_url + "/", href)

    parsed = urlparse(href)

    if parsed.scheme not in {"http", "https"}:
        return None
    if not same_host(href):
        return None

    path = parsed.path.rstrip("/")
    if not path or path == "/":
        return None
    if path.lower().endswith(
        (".jpg", ".jpeg", ".png", ".webp", ".svg", ".gif")
    ):
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

    # Notino currently uses both classic /p-<id>/ product URLs and
    # product slugs without a numeric id.
    if PRODUCT_ID_RE.search("/" + path + "/"):
        return True

    segments = [part for part in path.split("/") if part]
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
    match = SIZE_RE.search(str(query or ""))
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
    value = norm(" ".join(str(x or "") for x in texts))

    if re.search(
        r"\b(men|male|homme|pour homme|heren)\b",
        value,
        re.I,
    ):
        return "men"

    if re.search(
        r"\b(women|female|femme|pour femme|dames)\b",
        value,
        re.I,
    ):
        return "women"

    if re.search(r"\b(unisex|unisexe|mixte)\b", value, re.I):
        return "unisex"

    return "unknown"


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


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


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

        objects.extend(
            obj for obj in walk_json(data)
            if isinstance(obj, dict)
        )

    return [
        obj for obj in objects
        if str(obj.get("@type", "")).lower() == "product"
    ]


def product_brand(data):
    if not isinstance(data, dict):
        return ""

    brand = data.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    return clean(brand)


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


def find_product_data(products, query):
    wanted = query_tokens(query)
    if not products:
        return {}

    if not wanted:
        return products[0]

    for data in products:
        name = clean(data.get("name"))
        identity = norm(
            " ".join((name, product_brand(data)))
        )
        if name and all(token in identity for token in wanted):
            return data

    return products[0]


def extract_price(soup, data):
    if isinstance(data, dict):
        offers = data.get("offers")
        if isinstance(offers, dict):
            offers = [offers]

        if isinstance(offers, list):
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
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
                node.get("content")
                or node.get_text(" ", strip=True)
            )

    for raw in values:
        value = norm(raw)

        if any(term in value for term in (
            "instock", "in stock", "available",
            "disponible", "en stock",
        )):
            return "in_stock"

        if any(term in value for term in (
            "outofstock", "out of stock", "soldout",
            "sold out", "unavailable", "indisponible",
            "rupture", "epuise",
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
            blob = " ".join(
                (
                    node.get("value", ""),
                    node.get("aria-label", ""),
                    node.get("data-value", ""),
                    node.get("data-size", ""),
                    node.get_text(" ", strip=True),
                )
            )
            size = extract_size_ml(blob)
            if size is not None:
                return size

    return None


def query_matches_product(
    name,
    query,
    brand="",
    size_ml=None,
    url="",
):
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
    query_normalized = norm(query)

    for phrase in NON_PRODUCT_TERMS:
        phrase_n = norm(phrase)
        if phrase_n in name_only and phrase_n not in query_normalized:
            return False

    return True


def candidate_score(url, text, query):
    wanted = query_tokens(query)
    if not wanted:
        return 0

    identity = norm(
        " ".join(
            (
                text,
                urlparse(url).path.replace("-", " "),
            )
        )
    )

    score = 0
    for token in wanted:
        if token in identity:
            score += 1

    # A numeric product id is a strong structural signal, but not required.
    if PRODUCT_ID_RE.search(url):
        score += 0.25

    return score


def extract_search_candidates(soup, page_url, query, raw_html=""):
    candidates = []
    seen = set()

    def add(raw_url, text=""):
        url = normalise_url(raw_url, page_url)
        if not url or not product_url(url):
            return

        if url in seen:
            return

        score = candidate_score(url, text, query)

        # Search results should be relevant before they are fetched.
        # A candidate with no query token is not useful and only creates
        # unnecessary requests.
        if score < 1:
            return

        seen.add(url)
        candidates.append(
            {
                "url": url,
                "text": clean(text),
                "score": score,
            }
        )

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")

        text_parts = [
            anchor.get("title"),
            anchor.get("aria-label"),
            anchor.get_text(" ", strip=True),
        ]

        image = anchor.find("img")
        if image:
            text_parts.extend(
                (
                    image.get("alt"),
                    image.get("title"),
                )
            )

        text = clean(" ".join(
            str(value or "")
            for value in text_parts
        ))

        add(href, text)

    # Some product URLs are present only in structured data.
    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
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
                    add(value, clean(
                        " ".join(
                            (
                                str(obj.get("name") or ""),
                                str(obj.get("brand") or ""),
                            )
                        )
                    ))

            item = obj.get("item")
            if isinstance(item, dict):
                for key in ("url", "@id"):
                    value = item.get(key)
                    if isinstance(value, str):
                        add(
                            value,
                            clean(
                                " ".join(
                                    (
                                        str(item.get("name") or ""),
                                        str(item.get("brand") or ""),
                                    )
                                )
                            ),
                        )

    # Last-resort extraction from embedded HTML/JSON.
    decoded = (
        raw_html
        or ""
    ).replace("\\/", "/").replace("\\u002F", "/")

    for raw_url in re.findall(
        r'(?:https?:)?//(?:www\.)?notino\.fr/[^"\'<>\\\s]+',
        decoded,
        re.I,
    ):
        add(raw_url, raw_url)

    candidates.sort(
        key=lambda item: (-item["score"], item["url"])
    )

    return candidates[:MAX_CANDIDATES]


def fetch(session, url, params=None, referer=None):
    headers = dict(HEADERS)

    if referer:
        headers["Referer"] = referer

    try:
        response = session.get(
            url,
            params=params,
            headers=headers,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        print(
            f"NOTINO_FETCH_ERROR url={url!r} "
            f"type={type(exc).__name__} error={exc}",
            flush=True,
        )
        return None

    final_url = response.url

    if not response.ok:
        print(
            f"NOTINO_FETCH_HTTP url={url!r} "
            f"status={response.status_code} final={final_url!r}",
            flush=True,
        )
        return None

    if not same_host(final_url):
        print(
            f"NOTINO_FETCH_HOST_REJECTED url={url!r} "
            f"final={final_url!r}",
            flush=True,
        )
        return None

    return response


def parse_product_page(response, query):
    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    products = extract_json_ld(soup)
    data = find_product_data(products, query)

    name = product_name(soup, data)

    brand = product_brand(data)

    if not brand:
        brand_node = soup.select_one(
            '[itemprop="brand"], '
            '[data-brand], '
            'meta[property="product:brand"]'
        )
        if brand_node:
            brand = clean(
                brand_node.get("content")
                or brand_node.get("data-brand")
                or brand_node.get_text(" ", strip=True)
            )

    page_text = soup.get_text(" ", strip=True)

    size = selected_size(
        soup,
        data,
        name,
    )
    if size is None:
        size = extract_size_ml(
            page_text
        )

    url = normalise_url(
        response.url
    )

    if not query_matches_product(
        name,
        query,
        brand=brand,
        size_ml=size,
        url=url,
    ):
        print(
            f"NOTINO_REJECT name={name!r} "
            f"brand={brand!r} url={url!r} "
            f"query={query!r}",
            flush=True,
        )
        return None

    price = extract_price(
        soup,
        data,
    )

    if price is None:
        print(
            f"NOTINO_REJECT_NO_PRICE name={name!r} "
            f"url={url!r}",
            flush=True,
        )
        return None

    concentration = extract_concentration(
        name,
    )

    gender = extract_gender(
        name,
        page_text,
    )

    availability = extract_availability(
        soup,
        data,
    )

    image = image_from_product(
        soup,
        data,
        url,
    )

    product_id_match = PRODUCT_ID_RE.search(
        url or ""
    )

    product_id = (
        product_id_match.group(1)
        if product_id_match
        else None
    )

    gtin = ""
    mpn = ""
    sku = ""

    if isinstance(data, dict):
        gtin = clean(
            data.get("gtin13")
            or data.get("gtin")
            or ""
        )
        mpn = clean(
            data.get("mpn")
            or ""
        )
        sku = clean(
            data.get("sku")
            or ""
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
        "price": (
            f"{price:.2f}".replace(".", ",")
            + " €"
        ),
        "url": url,
        "image": image,
        "available": availability == "in_stock",
    }


def search(query):
    query = clean(query)

    if not query:
        return []

    print(
        f"NOTINO_SEARCH: START query={query!r}",
        flush=True,
    )

    session = requests.Session()

    try:
        # First visit establishes the site's cookies/session.
        homepage = fetch(
            session,
            BASE_URL + "/",
        )

        if homepage is None:
            print(
                "NOTINO_SEARCH: HOME_FAILED",
                flush=True,
            )
            return []

        response = fetch(
            session,
            urljoin(BASE_URL, SEARCH_PATH),
            params={"exps": query},
            referer=homepage.url,
        )

        if response is None:
            print(
                "NOTINO_SEARCH: SEARCH_FAILED",
                flush=True,
            )
            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        candidates = extract_search_candidates(
            soup,
            response.url,
            query,
            response.text,
        )

        print(
            f"NOTINO_SEARCH: CANDIDATES "
            f"query={query!r} count={len(candidates)} "
            f"top={[item['url'] for item in candidates[:5]]}",
            flush=True,
        )

        results = []
        seen = set()

        for candidate in candidates:
            url = candidate["url"]

            if url in seen:
                continue

            seen.add(url)

            product_response = fetch(
                session,
                url,
                referer=response.url,
            )

            if product_response is None:
                continue

            product = parse_product_page(
                product_response,
                query,
            )

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

        print(
            f"NOTINO_SEARCH: END query={query!r} "
            f"results={len(results)}",
            flush=True,
        )

        return results

    except Exception as exc:
        print(
            f"NOTINO_SEARCH: EXCEPTION "
            f"type={type(exc).__name__} error={exc}",
            flush=True,
        )
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
