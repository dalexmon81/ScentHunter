import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://bplatz.de"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}
SEARCH_TIMEOUT = (2.0, 5.0)
PRODUCT_TIMEOUT = (2.0, 5.0)
MAX_CANDIDATES = 12

NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "discovery set", "fragrance set", "perfume set",
    "parfum set", "coffret", "bundle", "pack", "travel set", "kit", "duo",
    "trio", "mystery box", "tester", "testeur", "sample", "shampoo",
    "shower gel", "body lotion", "body cream", "deodorant", "deo spray",
    "aftershave", "after shave", "makeup", "skin care", "skincare",
    "cosmetics", "cosmetici",
}


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def contains_non_perfume_marker(name):
    text = norm(name)
    tokens = set(text.split())
    for marker in NON_PERFUME_MARKERS:
        marker_tokens = set(norm(marker).split())
        if marker_tokens and marker_tokens.issubset(tokens):
            return True
    return False


def query_matches(name, query):
    if contains_non_perfume_marker(name):
        return False
    ignored = {
        "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
        "spray", "ml", "for", "by", "the",
    }
    query_tokens = [t for t in norm(query).split() if t not in ignored]
    name_tokens = set(norm(name).split())
    return bool(query_tokens) and all(t in name_tokens for t in query_tokens)


def parse_price(value):
    if value in (None, ""):
        return None
    text = str(value).strip().replace("\xa0", " ")
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        if len(text.rsplit(",", 1)[-1]) <= 2:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def money(value):
    price = parse_price(value)
    return "" if price is None else f"{price:.2f}".replace(".", ",") + " €"


def request_get(session, url, timeout):
    try:
        response = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if response.ok and response.text:
            return response
    except requests.RequestException:
        return None
    return None


def search_html(session, query):
    url = BASE + "/search?q=" + quote_plus(query) + "&type=product"
    response = request_get(session, url, SEARCH_TIMEOUT)
    if not response:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    found = []
    seen = set()

    for anchor in soup.select('a[href*="/products/"]'):
        href = anchor.get("href") or ""
        absolute = urljoin(BASE, href).split("?")[0].rstrip("/")
        path = urlparse(absolute).path
        if "/products/" not in path:
            continue
        if path in seen:
            continue

        texts = [
            anchor.get("title") or "",
            anchor.get("aria-label") or "",
            anchor.get_text(" ", strip=True) or "",
        ]
        if not any(query_matches(text, query) for text in texts):
            # Check the nearest product card without walking too far into page
            card = anchor
            for _ in range(4):
                card = card.parent
                if not card:
                    break
                text = card.get_text(" ", strip=True)
                if query_matches(text, query):
                    texts.append(text)
                    break

        if any(query_matches(text, query) for text in texts):
            seen.add(path)
            found.append(absolute)
            if len(found) >= MAX_CANDIDATES:
                break

    return found


def predictive_html(session, query):
    # Shopify predictive search fallback. Keep it independent from the HTML
    # search because some Shopify themes disable predictive suggestions.
    endpoint = BASE + "/search/suggest.json"
    params = {
        "q": query,
        "resources[type]": "product",
        "resources[limit]": "20",
        "resources[options][unavailable_products]": "show",
    }
    response = request_get(
        session,
        endpoint + "?" + "&".join(f"{quote_plus(str(k))}={quote_plus(str(v))}" for k, v in params.items()),
        SEARCH_TIMEOUT,
    )
    if not response:
        return []

    try:
        data = response.json()
    except (ValueError, TypeError):
        return []

    products = (
        (((data or {}).get("resources") or {}).get("results") or {}).get("products")
        or []
    )
    urls = []
    seen = set()
    for product in products:
        title = product.get("title") or product.get("name") or ""
        if not query_matches(title, query):
            continue
        raw_url = product.get("url") or product.get("handle") or ""
        if not raw_url:
            continue
        if not raw_url.startswith("http"):
            raw_url = "/products/" + str(raw_url).strip("/")
        absolute = urljoin(BASE, raw_url).split("?")[0].rstrip("/")
        path = urlparse(absolute).path
        if "/products/" not in path or path in seen:
            continue
        seen.add(path)
        urls.append(absolute)
        if len(urls) >= MAX_CANDIDATES:
            break
    return urls


def jsonld_objects(soup):
    objects = []
    for node in soup.select('script[type="application/ld+json"]'):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(data, list):
            objects.extend(data)
        else:
            objects.append(data)
    return objects


def walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def extract_size_ml(text):
    matches = re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", text or "", flags=re.I)
    if not matches:
        return None
    values = []
    for number, unit in matches:
        try:
            value = float(number.replace(",", "."))
            if unit.lower() == "cl":
                value *= 10
            values.append(value)
        except ValueError:
            pass
    return min(values) if values else None


def extract_product_html(html, url):
    soup = BeautifulSoup(html, "html.parser")
    objects = jsonld_objects(soup)

    title = ""
    brand = ""
    price = None
    available = None
    sku = ""
    gtin = ""

    for obj in walk_dicts(objects):
        typ = obj.get("@type")
        types = typ if isinstance(typ, list) else [typ]
        if "Product" in types or typ == "Product":
            title = title or str(obj.get("name") or "").strip()
            brand_value = obj.get("brand")
            if isinstance(brand_value, dict):
                brand = brand or str(brand_value.get("name") or "").strip()
            elif brand_value:
                brand = brand or str(brand_value).strip()
            sku = sku or str(obj.get("sku") or "").strip()
            gtin = gtin or str(
                obj.get("gtin13") or obj.get("gtin") or obj.get("gtin12") or ""
            ).strip()

            offers = obj.get("offers")
            offer_list = offers if isinstance(offers, list) else [offers]
            for offer in offer_list:
                if not isinstance(offer, dict):
                    continue
                if price is None:
                    price = parse_price(offer.get("price"))
                if available is None and offer.get("availability"):
                    availability = str(offer.get("availability")).lower()
                    if "instock" in availability:
                        available = True
                    elif "outofstock" in availability or "soldout" in availability:
                        available = False

    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
    if not title:
        meta = soup.find("meta", attrs={"property": "og:title"})
        title = (meta.get("content") or "").strip() if meta else ""

    if not brand:
        # Bplatz currently exposes the seller/brand near the product title.
        for text in soup.stripped_strings:
            if text.strip().lower() in {"fragrance world", "french avenue"}:
                brand = text.strip()
                break

    if price is None:
        meta_price = soup.find("meta", attrs={"itemprop": "price"})
        if meta_price:
            price = parse_price(meta_price.get("content"))
    if price is None:
        node = soup.select_one('[data-price], [data-product-price], .price-item--sale, .price-item--regular')
        if node:
            price = parse_price(node.get("data-price") or node.get_text(" ", strip=True))

    if available is None:
        availability_meta = soup.find("meta", attrs={"itemprop": "availability"})
        if availability_meta:
            value = str(availability_meta.get("content") or "").lower()
            if "instock" in value:
                available = True
            elif "outofstock" in value or "soldout" in value:
                available = False

    if available is None:
        text = soup.get_text(" ", strip=True).lower()
        if any(marker in text for marker in (
            "out of stock", "nicht vorrätig", "ausverkauft", "sold out",
        )):
            available = False
        elif any(marker in text for marker in (
            "in den warenkorb", "add to cart", "jetzt kaufen",
        )):
            available = True

    if not title or contains_non_perfume_marker(title):
        return None
    return {
        "store": "Bplatz",
        "name": title,
        "brand": brand,
        "price": money(price),
        "price_num": price,
        "url": url,
        "available": bool(available) if available is not None else False,
        "availability": "in_stock" if available is True else ("out_of_stock" if available is False else "unknown"),
        "size_ml": extract_size_ml(title),
        "sku": sku,
        "gtin": gtin,
    }


def fetch_product(url):
    session = requests.Session()
    try:
        response = request_get(session, url, PRODUCT_TIMEOUT)
        if not response:
            return None
        return extract_product_html(response.text, url)
    finally:
        session.close()


def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    session = requests.Session()
    try:
        # HTML search is currently the most reliable first-party route on Bplatz:
        # the live site exposes Liquid Brun directly in /search and collections.
        urls = search_html(session, query)

        # Predictive fallback for themes where search HTML is incomplete.
        if not urls:
            urls = predictive_html(session, query)

        # Last-resort token search: useful when the exact phrase is not indexed
        # by the theme but the product is discoverable by a distinctive token.
        if not urls:
            for token in norm(query).split():
                if len(token) < 3:
                    continue
                urls = search_html(session, token)
                if urls:
                    break

        urls = urls[:MAX_CANDIDATES]
    finally:
        session.close()

    if not urls:
        return []

    results = []
    with ThreadPoolExecutor(max_workers=min(6, len(urls))) as executor:
        futures = {executor.submit(fetch_product, url): url for url in urls}
        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception:
                item = None
            if item and query_matches(item.get("name", ""), query):
                results.append(item)

    # Stable deterministic order and duplicate suppression.
    seen = set()
    final = []
    for item in results:
        key = urlparse(item["url"]).path.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        final.append(item)

    final.sort(key=lambda x: (not bool(x.get("available")), x.get("price_num") is None, x.get("price_num") or 999999))
    return final


if __name__ == "__main__":
    for query in ("Liquid Brun", "9 PM", "Turathi Blue"):
        print("\nQUERY:", query)
        for result in search(query):
            print(result)
