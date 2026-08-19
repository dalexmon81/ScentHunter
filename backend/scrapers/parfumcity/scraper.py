import json
import re
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup

STORE = "ParfumCity"
BASE_URL = "https://www.parfumcity.nl"
TIMEOUT = 8
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def norm(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(value).lower())).strip()

def tokens(value):
    return [x for x in norm(value).split() if len(x) > 1]

def matches(text, query):
    q = set(tokens(query))
    return bool(q) and q.issubset(set(tokens(text)))

def price(value):
    match = re.search(r"(?<![\d.,])(\d{1,4}(?:[.,]\d{2}))\s*€|€\s*(\d{1,4}(?:[.,]\d{2}))", clean(value))
    if not match:
        return None
    raw = next(x for x in match.groups() if x)
    return float(raw.replace(".", "").replace(",", ".")) if "," in raw and "." in raw else float(raw.replace(",", "."))

def size_ml(*values):
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", " ".join(clean(x) for x in values), re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10
    return int(value) if value.is_integer() else value

def concentration(*values):
    text = norm(" ".join(clean(x) for x in values))
    if re.search(r"\beau de toilette\b|\bedt\b", text): return "Eau de Toilette"
    if re.search(r"\beau de parfum\b|\bedp\b", text): return "Eau de Parfum"
    if re.search(r"\bextrait(?: de parfum)?\b", text): return "Extrait de Parfum"
    return None

def product_page(session, url, query):
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    name = clean(h1.get_text(" ", strip=True)) if h1 else ""
    if not name or not matches(name, query):
        return None

    amount = None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                offers = item.get("offers")
                offers = offers if isinstance(offers, list) else [offers]
                for offer in offers:
                    if isinstance(offer, dict):
                        try:
                            amount = float(str(offer.get("price")).replace(",", "."))
                        except (TypeError, ValueError):
                            pass
                        if amount:
                            break
                if amount:
                    break

    if amount is None:
        text = soup.get_text(" ", strip=True)
        amount = price(text)

    if amount is None:
        return None

    image = None
    meta = soup.select_one('meta[property="og:image"]')
    if meta and meta.get("content"):
        image = urljoin(url, meta["content"])

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": None,
            "url": url,
            "image": image,
        },
        "identity": {
            "gtin": None,
            "mpn": None,
            "sku": None,
            "store_product_id": None,
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {"value": size_ml(name), "source": "product_title"} if size_ml(name) else None,
            "concentration": {"value": concentration(name), "source": "product_title"} if concentration(name) else None,
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
        },
        "offer": {
            "price": round(amount, 2),
            "currency": "EUR",
            "availability": "unknown",
        },
        "provenance": {"source_page": url, "name_source": "h1", "price_source": "jsonld_or_page"},
        "raw_data": {},
        "name": name,
        "price": f"{amount:.2f}".replace(".", ",") + "€",
        "url": url,
        "available": True,
    }

def _add_url(urls, seen, url):
    url = urljoin(BASE_URL, str(url or "")).split("?")[0].rstrip("/")
    if not url or "/products/" not in url:
        return
    if url in seen:
        return
    seen.add(url)
    urls.append(url)


def _discover_from_html(soup, query, urls, seen):
    # Standard Shopify search/collection HTML.
    for a in soup.select('a[href*="/products/"]'):
        href = a.get("href") or ""
        card = a
        card_text = ""
        for _ in range(9):
            if card is None:
                break
            card_text = clean(card.get_text(" ", strip=True))
            if matches(card_text, query):
                break
            card = card.parent
        # Do not require a price in the card: Shopify may render it separately.
        if card is not None and matches(card_text, query):
            _add_url(urls, seen, href)


def _discover_from_predictive_search(session, query, urls, seen):
    # Generic Shopify predictive-search JSON fallback.
    endpoint = (
        BASE_URL
        + "/search/suggest.json?q="
        + quote_plus(query)
        + "&resources[type]=product"
        + "&resources[limit]=20"
    )
    try:
        r = session.get(endpoint, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return
        data = r.json()
    except (requests.RequestException, ValueError):
        return

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"url", "product_url"} and isinstance(item, str):
                    if "/products/" in item:
                        _add_url(urls, seen, item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)


def _discover_from_sitemap(session, query, urls, seen):
    # Generic Shopify fallback: inspect product sitemap URLs and match
    # query tokens against the product slug. No product is hard-coded.
    try:
        r = session.get(BASE_URL + "/sitemap.xml", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return
        root = BeautifulSoup(r.text, "xml")
        sitemap_urls = [
            clean(x.get_text(strip=True))
            for x in root.find_all("loc")
            if "/sitemap_products" in clean(x.get_text(strip=True))
        ]
    except requests.RequestException:
        return

    q_tokens = tokens(query)
    if not q_tokens:
        return

    for sitemap_url in sitemap_urls:
        if len(urls) >= 30:
            break
        try:
            rr = session.get(sitemap_url, headers=HEADERS, timeout=TIMEOUT)
            if rr.status_code != 200:
                continue
            sm = BeautifulSoup(rr.text, "xml")
        except requests.RequestException:
            continue

        for loc in sm.find_all("loc"):
            product_url = clean(loc.get_text(strip=True))
            if "/products/" not in product_url:
                continue
            slug = norm(product_url.rsplit("/products/", 1)[-1])
            if all(token in slug.split() for token in q_tokens):
                _add_url(urls, seen, product_url)
                if len(urls) >= 30:
                    break


def _predictive_product_result(item, query):
    """Build a generic product result from Shopify predictive-search data."""
    if not isinstance(item, dict):
        return None

    title = clean(item.get("title") or item.get("product_title") or item.get("name") or "")
    url = item.get("url") or item.get("product_url") or item.get("link") or ""

    if not title or not url or "/products/" not in str(url):
        return None

    available = item.get("available")
    if available is False:
        return None

    if not matches(title, query):
        return None

    price = item.get("price")
    if price is None:
        price = item.get("price_min")

    if isinstance(price, str):
        price = price.replace(",", ".").strip()

    try:
        price_value = float(price) if price not in (None, "") else None
    except (TypeError, ValueError):
        price_value = None

    image = item.get("image") or item.get("featured_image") or ""
    if isinstance(image, dict):
        image = image.get("url") or image.get("src") or ""

    return {
        "name": title,
        "brand": clean(item.get("vendor") or item.get("brand") or ""),
        "price": price_value,
        "currency": "EUR",
        "url": urljoin(BASE_URL, str(url)).split("?")[0],
        "image": urljoin(BASE_URL, str(image)) if image else None,
        "available": True,
        "query": query,
        "source": "parfumcity",
    }


def _predictive_results(data, query):
    """Extract product objects recursively from Shopify predictive-search JSON."""
    found = []

    def walk(value):
        if isinstance(value, dict):
            if (
                ("url" in value or "product_url" in value or "link" in value)
                and ("title" in value or "product_title" in value or "name" in value)
            ):
                result = _predictive_product_result(value, query)
                if result:
                    found.append(result)

            for child in value.values():
                walk(child)

        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)

    unique = []
    seen = set()
    for item in found:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    return unique



def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()

    try:
        # Primary path: Shopify predictive-search JSON.
        endpoint = (
            BASE_URL
            + "/search/suggest.json?q="
            + quote_plus(query)
            + "&resources[type]=product"
            + "&resources[limit]=20"
        )

        try:
            r = session.get(endpoint, headers=HEADERS, timeout=TIMEOUT)

            if r.status_code == 200:
                data = r.json()
                direct_results = _predictive_results(data, query)

                if direct_results:
                    return direct_results[:15]

        except (requests.RequestException, ValueError):
            pass

        # Generic HTML fallback.
        urls, seen = [], set()

        for search_url in (
            BASE_URL + "/search?q=" + quote_plus(query),
            BASE_URL + "/search?options%5Bprefix%5D=last&q=" + quote_plus(query),
        ):
            try:
                r = session.get(search_url, headers=HEADERS, timeout=TIMEOUT)

                if r.status_code != 200:
                    continue

                soup = BeautifulSoup(r.text, "html.parser")

                for a in soup.select('a[href*="/products/"]'):
                    href = urljoin(BASE_URL, a.get("href") or "").split("?")[0]
                    card = a
                    card_text = ""

                    for _ in range(9):
                        if card is None:
                            break

                        card_text = clean(card.get_text(" ", strip=True))

                        if matches(card_text, query):
                            break

                        card = card.parent

                    if (
                        card is not None
                        and matches(card_text, query)
                        and href not in seen
                    ):
                        seen.add(href)
                        urls.append(href)

            except requests.RequestException:
                continue

            if len(urls) >= 15:
                break

        results = []

        for url in urls[:15]:
            item = product_page(session, url, query)

            if item:
                results.append(item)

        return results

    finally:
        session.close()

def scrape(query):
    return search(query)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generic ParfumCity store adapter")
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
