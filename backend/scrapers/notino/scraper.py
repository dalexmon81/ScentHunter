import json
import os
import re
import unicodedata
from urllib.parse import urljoin, urlparse, parse_qs, quote_plus

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:
    sync_playwright = None
    PlaywrightTimeoutError = Exception

from bs4 import BeautifulSoup


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = f"{BASE_URL}/search.asp"

BROWSER_TIMEOUT = int(os.getenv("NOTINO_BROWSER_TIMEOUT", "35000"))
MAX_SEARCH_PAGES = int(os.getenv("NOTINO_MAX_SEARCH_PAGES", "4"))
MAX_CANDIDATES = int(os.getenv("NOTINO_MAX_CANDIDATES", "80"))
MAX_VALIDATIONS = int(os.getenv("NOTINO_MAX_VALIDATIONS", "35"))

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

NON_PRODUCT_TERMS = {
    "coffret", "coffrets", "kit", "set", "discovery box", "cadeau",
    "body mist", "brume", "gel douche", "lotion", "deodorant",
    "déodorant", "deodorants", "déodorants", "shampoo", "shampoing",
    "conditioner", "après-shampoing", "hair", "cheveux", "makeup",
    "maquillage", "skincare", "soin du visage", "corps", "savon",
    "after shave", "après-rasage", "vaporisateur", "atomiseur",
}

IGNORED_QUERY_WORDS = {
    "eau", "de", "du", "des", "la", "le", "les", "parfum", "parfums",
    "perfume", "perfumes", "fragrance", "fragrances", "edp", "edt",
    "extrait", "spray", "for", "pour", "by", "homme", "hommes", "femme",
    "femmes", "men", "women", "male", "female", "unisex", "unisexe", "mixte",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def same_host(url):
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
        return host == "notino.fr" or host.endswith(".notino.fr")
    except Exception:
        return False


def product_url(url):
    try:
        path = urlparse(url).path.rstrip("/")
    except Exception:
        return False
    return bool(re.search(r"/p-\d+$", path, re.I))


def query_tokens(query):
    return [
        token for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS and len(token) >= 2
    ]


def explicit_size(query):
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        norm(query),
        re.I,
    )
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10
    return value


def extract_size_ml(*texts):
    for value, unit in re.findall(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        " ".join(str(x or "") for x in texts),
        re.I,
    ):
        number = float(value.replace(",", "."))
        if unit.lower() == "cl":
            number *= 10
        return int(number) if number.is_integer() else number
    return None


def extract_concentration(*texts):
    text = norm(" ".join(str(x or "") for x in texts))
    patterns = (
        ("Extrait de Parfum", r"\bextrait(?: de)? parfum\b"),
        ("Eau de Parfum", r"\beau de parfum\b|\bedp\b"),
        ("Eau de Toilette", r"\beau de toilette\b|\bedt\b"),
        ("Eau de Cologne", r"\beau de cologne\b|\bedc\b"),
        ("Parfum", r"\bparfum\b"),
    )
    for label, pattern in patterns:
        if re.search(pattern, text, re.I):
            return label
    return None


def extract_gender(*texts):
    text = norm(" ".join(str(x or "") for x in texts))
    if re.search(r"\b(men|male|homme|hommes|pour homme)\b", text):
        return "men"
    if re.search(r"\b(women|female|femme|femmes|pour femme)\b", text):
        return "women"
    if re.search(r"\b(unisex|unisexe|mixte)\b", text):
        return "unisex"
    return "unknown"


def extract_json_ld(soup):
    objects = []
    for script in soup.find_all(
        "script",
        attrs={"type": re.compile(r"application/ld\+json", re.I)},
    ):
        raw = script.string or script.get_text()
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            objects.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            objects.append(data)
            graph = data.get("@graph")
            if isinstance(graph, list):
                objects.extend(x for x in graph if isinstance(x, dict))

    for item in objects:
        item_type = item.get("@type")
        types = item_type if isinstance(item_type, list) else [item_type]
        if any(str(x).lower() == "product" for x in types):
            return item
    return None


def first_value(soup, selectors):
    for selector in selectors:
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
    return ""


def product_name(soup, json_ld=None):
    if isinstance(json_ld, dict):
        value = clean(json_ld.get("name"))
        if value:
            return value
    return first_value(
        soup,
        [
            "h1",
            '[itemprop="name"]',
            'meta[property="og:title"]',
            'meta[name="twitter:title"]',
            "title",
        ],
    )


def product_brand(soup, json_ld=None):
    if isinstance(json_ld, dict):
        brand = json_ld.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        brand = clean(brand)
        if brand:
            return brand

    return first_value(
        soup,
        [
            '[itemprop="brand"]',
            'meta[property="product:brand"]',
            '[data-brand]',
        ],
    )


def parse_price(value):
    if value in (None, ""):
        return None
    text = clean(value).replace("€", "").replace("\xa0", " ")
    text = re.sub(r"[^0-9,.\-]", "", text)
    if not text:
        return None
    try:
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            text = text.replace(",", ".")
        number = float(text)
        return round(number, 2) if 0 < number < 10000 else None
    except ValueError:
        return None


def extract_price(soup, json_ld=None):
    values = []

    if isinstance(json_ld, dict):
        offers = json_ld.get("offers")
        offer_list = offers if isinstance(offers, list) else [offers]
        for offer in offer_list:
            if isinstance(offer, dict):
                values.extend([
                    offer.get("price"),
                    offer.get("lowPrice"),
                ])

    for selector in (
        'meta[itemprop="price"]',
        'meta[property="product:price:amount"]',
        '[itemprop="price"]',
        "[data-price]",
    ):
        for node in soup.select(selector):
            values.append(
                node.get("content")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )

    # Use visible price-like text only as a last fallback.
    text = soup.get_text(" ", strip=True)
    for match in re.finditer(
        r"(?:€\s*)?(\d{1,4}(?:[.,]\d{1,2}))(?:\s*€)?",
        text,
    ):
        values.append(match.group(1))

    for value in values:
        price = parse_price(value)
        if price is not None:
            return price
    return None


def extract_availability(soup, json_ld=None):
    if isinstance(json_ld, dict):
        offers = json_ld.get("offers")
        offer_list = offers if isinstance(offers, list) else [offers]
        for offer in offer_list:
            if not isinstance(offer, dict):
                continue
            value = norm(offer.get("availability"))
            if "instock" in value:
                return "in_stock"
            if "outofstock" in value:
                return "out_of_stock"

    # Prefer explicit availability-related elements before whole-page text.
    for selector in (
        '[itemprop="availability"]',
        '[data-testid*="availability" i]',
        '[data-testid*="stock" i]',
    ):
        node = soup.select_one(selector)
        if node:
            value = norm(node.get("content") or node.get_text(" ", strip=True))
            if any(x in value for x in ("instock", "in stock", "en stock", "en voorraad")):
                return "in_stock"
            if any(x in value for x in ("outofstock", "out of stock", "plus de stock", "niet op voorraad")):
                return "out_of_stock"

    text = norm(soup.get_text(" ", strip=True))
    if re.search(r"\ben stock\b|\ben voorraad\b|\bavailable\b", text):
        return "in_stock"
    if re.search(r"\bout of stock\b|\bplus de stock\b|\bniet op voorraad\b", text):
        return "out_of_stock"
    return "unknown"


def extract_image(soup, json_ld=None):
    if isinstance(json_ld, dict):
        image = json_ld.get("image")
        if isinstance(image, list):
            image = image[0] if image else ""
        image = clean(image)
        if image:
            return image
    return first_value(
        soup,
        [
            'meta[property="og:image"]',
            'meta[name="twitter:image"]',
        ],
    )


def looks_like_fragrance(name, concentration=None):
    identity = norm(name)
    if not identity:
        return False

    for term in NON_PRODUCT_TERMS:
        if norm(term) in identity:
            return False

    if concentration:
        return True

    return bool(
        re.search(
            r"\b(eau de parfum|eau de toilette|eau de cologne|"
            r"extrait de parfum|parfum|perfume|fragrance)\b",
            identity,
        )
    )


def candidate_from_anchor(anchor, page_url):
    href = clean(anchor.get("href"))
    if not href:
        return None

    url = urljoin(page_url, href)
    parsed = urlparse(url)
    clean_url = parsed._replace(query="", fragment="").geturl()

    if not same_host(clean_url) or not product_url(clean_url):
        return None

    pieces = [
        anchor.get("title"),
        anchor.get("aria-label"),
        anchor.get_text(" ", strip=True),
    ]
    image = anchor.find("img")
    if image:
        pieces.extend([image.get("alt"), image.get("title")])

    return {
        "url": clean_url,
        "text": clean(" ".join(x for x in pieces if x)),
    }


def extract_candidates(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        candidate = candidate_from_anchor(anchor, page_url)
        if not candidate:
            continue
        url = candidate["url"]
        if url in seen:
            continue
        seen.add(url)
        candidates.append(candidate)

    return candidates


def candidate_score(candidate, query):
    wanted = query_tokens(query)
    text = norm(candidate.get("text"))
    if not wanted or not text:
        return 0

    score = 0
    for token in wanted:
        if token in set(text.split()):
            score += 3
        elif token in text:
            score += 1

    return score


def search_page_urls(query):
    # Notino's public search endpoint accepts the query in "exps".
    return [f"{SEARCH_URL}?exps={quote_plus(clean(query))}"]


def next_page_url(page):
    candidates = []
    try:
        hrefs = page.locator("a[href]").evaluate_all(
            """els => els.map(a => ({
                href: a.href,
                text: (a.innerText || a.getAttribute('aria-label') || '').trim(),
                rel: a.getAttribute('rel') || ''
            }))"""
        )
    except Exception:
        return None

    current = page.url
    current_page = None
    try:
        query = parse_qs(urlparse(current).query)
        current_page = int(query.get("page", ["1"])[0])
    except Exception:
        pass

    for item in hrefs:
        href = item.get("href") or ""
        text = norm(item.get("text"))
        rel = norm(item.get("rel"))
        if not same_host(href):
            continue
        if "next" in rel or text in {"suivant", "next", "suivante"}:
            candidates.append(href)

    if candidates:
        return candidates[0]

    # Generic numeric pagination fallback. Never assumes a fixed page URL shape.
    for item in hrefs:
        href = item.get("href") or ""
        if not same_host(href):
            continue
        try:
            query = parse_qs(urlparse(href).query)
            number = int(query.get("page", ["0"])[0])
        except Exception:
            continue
        if current_page is not None and number == current_page + 1:
            return href

    return None


def browser_discover(query):
    if sync_playwright is None:
        return []

    candidates = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="fr-BE",
            viewport={"width": 1440, "height": 1100},
        )
        page = context.new_page()

        try:
            page_urls = search_page_urls(query)

            for start_url in page_urls:
                try:
                    page.goto(
                        start_url,
                        wait_until="domcontentloaded",
                        timeout=BROWSER_TIMEOUT,
                    )
                except PlaywrightTimeoutError:
                    pass

                for _ in range(MAX_SEARCH_PAGES):
                    try:
                        page.wait_for_timeout(1200)
                    except Exception:
                        pass

                    html = page.content()
                    page_candidates = extract_candidates(html, page.url)

                    for candidate in page_candidates:
                        url = candidate["url"]
                        if url in seen:
                            continue
                        seen.add(url)
                        candidate["score"] = candidate_score(candidate, query)
                        candidates.append(candidate)

                    if len(candidates) >= MAX_CANDIDATES:
                        break

                    nxt = next_page_url(page)
                    if not nxt or nxt == page.url:
                        break

                    try:
                        page.goto(
                            nxt,
                            wait_until="domcontentloaded",
                            timeout=BROWSER_TIMEOUT,
                        )
                    except PlaywrightTimeoutError:
                        pass

                if candidates:
                    break
        finally:
            context.close()
            browser.close()

    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    return candidates[:MAX_CANDIDATES]


def parse_product_html(html, response_url, query):
    soup = BeautifulSoup(html, "html.parser")
    json_ld = extract_json_ld(soup)

    name = product_name(soup, json_ld)
    brand = product_brand(soup, json_ld)
    page_text = soup.get_text(" ", strip=True)

    size_ml = extract_size_ml(name, page_text)
    concentration = extract_concentration(name, page_text)
    gender = extract_gender(name, page_text)

    if not name:
        return None
    if not looks_like_fragrance(name, concentration):
        return None

    url = urlparse(response_url)._replace(query="", fragment="").geturl()
    if not same_host(url) or not product_url(url):
        return None

    wanted = query_tokens(query)
    identity = norm(" ".join(x for x in (brand, name) if x))

    # The final validation is deliberately based on the product identity,
    # never on the URL slug or candidate anchor text.
    if wanted and not all(token in identity or token in norm(name) for token in wanted):
        return None

    requested_size = explicit_size(query)
    if requested_size is not None:
        if size_ml is None or abs(float(size_ml) - float(requested_size)) > 0.01:
            return None

    price = extract_price(soup, json_ld)
    availability = extract_availability(soup, json_ld)
    image = extract_image(soup, json_ld)

    product_id_match = re.search(r"/p-(\d+)$", urlparse(url).path, re.I)
    product_id = product_id_match.group(1) if product_id_match else None

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
            "size_ml": {"value": size_ml, "source": "product_page"},
            "concentration": {"value": concentration, "source": "product_page"},
            "gender": {"value": gender, "source": "product_page"},
            "packaging_type": {"value": "product", "source": "default"},
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
        "price": f"{price:.2f} €" if price is not None else "",
        "url": url,
        "image": image,
        "available": availability == "in_stock",
    }


def validate_candidates(candidates, query):
    if sync_playwright is None:
        return []

    results = []
    seen = set()

    ordered = sorted(
        candidates,
        key=lambda item: item.get("score", 0),
        reverse=True,
    )[:MAX_VALIDATIONS]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="fr-BE",
            viewport={"width": 1440, "height": 1100},
        )
        page = context.new_page()

        try:
            for candidate in ordered:
                url = candidate.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)

                try:
                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=BROWSER_TIMEOUT,
                    )
                    page.wait_for_timeout(500)
                    html = page.content()
                    final_url = page.url
                except Exception:
                    continue

                product = parse_product_html(html, final_url, query)
                if not product:
                    continue

                key = (
                    product["url"].lower(),
                    norm(product["name"]),
                    product["attributes"]["size_ml"]["value"],
                )
                if key in seen:
                    continue

                seen.add(key)
                results.append(product)
        finally:
            context.close()
            browser.close()

    return results


def search(query):
    query = clean(query)
    if not query:
        return []

    candidates = browser_discover(query)
    if not candidates:
        return []

    return validate_candidates(candidates, query)


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
