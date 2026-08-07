import json
import re
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
}

PRICE_RE = re.compile(
    r"(?:€\s*)?(\d{1,4})\s*([,.])\s*(\d{2})(?:\s*€)?",
    re.I,
)

SOLD_OUT_WORDS = (
    "sold out",
    "out of stock",
    "temporarily unavailable",
    "not available",
)

BAD_PATHS = (
    "/cart",
    "/login",
    "/account",
    "/customer",
    "/contact",
    "/privacy",
    "/terms",
    "/search",
)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value):
    return [
        token
        for token in re.findall(r"[a-z0-9]+", _clean(value).lower())
        if len(token) > 1
    ]


def _matches(text, query):
    text_tokens = set(_tokens(text))
    query_tokens = _tokens(query)

    if not query_tokens:
        return False

    return all(token in text_tokens for token in query_tokens)


def _price(text):
    text = _clean(text)

    for match in PRICE_RE.finditer(text):
        whole = match.group(1)
        cents = match.group(3)
        return f"{whole},{cents}€"

    return None


def _is_product_url(url):
    low = _clean(url).lower()

    if not low.startswith(("http://", "https://")):
        return False

    if "deloox.com" not in low:
        return False

    if any(bad in low for bad in BAD_PATHS):
        return False

    return (
        "/product/" in low
        or "/category/" in low
        or low.endswith(".html")
    )


def _jsonld_products(soup, query):
    results = []
    seen = set()

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop()

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            for value in item.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)

            item_type = item.get("@type", "")
            if isinstance(item_type, list):
                is_product = "Product" in item_type
            else:
                is_product = str(item_type).lower() == "product"

            if not is_product:
                continue

            name = _clean(item.get("name"))
            if not name or not _matches(name, query):
                continue

            url = _clean(item.get("url"))

            offers = item.get("offers")
            if isinstance(offers, list):
                offers_list = offers
            elif isinstance(offers, dict):
                offers_list = [offers]
            else:
                offers_list = []

            for offer in offers_list or [{}]:
                offer_url = _clean(offer.get("url")) if isinstance(offer, dict) else ""
                product_url = urljoin(BASE_URL, offer_url or url)

                if not _is_product_url(product_url):
                    continue

                availability = _clean(
                    offer.get("availability") if isinstance(offer, dict) else ""
                ).lower()

                sold_out = (
                    "outofstock" in availability
                    or "soldout" in availability
                    or "discontinued" in availability
                )

                raw_price = (
                    offer.get("price") if isinstance(offer, dict) else None
                )

                price = None
                if raw_price not in (None, ""):
                    raw_price = str(raw_price).replace(".", ",")
                    match = re.search(r"(\d{1,4})[,](\d{2})", raw_price)
                    if match:
                        price = f"{match.group(1)},{match.group(2)}€"

                key = product_url.split("?")[0]
                if key in seen:
                    continue

                seen.add(key)
                results.append({
                    "store": STORE,
                    "name": name,
                    "price": price,
                    "url": key,
                    "available": not sold_out,
                    "availability": "out_of_stock" if sold_out else "in_stock",
                })

    return results


def _extract_cards(soup, query):
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))

        if not href:
            continue

        product_url = urljoin(BASE_URL, href).split("?")[0]

        if not _is_product_url(product_url):
            continue

        link_text = _clean(
            link.get("title")
            or link.get("aria-label")
            or link.get_text(" ", strip=True)
        )

        node = link
        card = None

        for _ in range(7):
            if node is None:
                break

            text = _clean(node.get_text(" ", strip=True))

            if len(text) <= 1200 and _matches(text, query) and _price(text):
                card = node
                break

            node = node.parent

        if card is None:
            continue

        text = _clean(card.get_text(" ", strip=True))
        low_text = text.lower()

        name = ""

        selectors = (
            "h1",
            "h2",
            "h3",
            "h4",
            "[itemprop='name']",
            "[class*='product-name']",
            "[class*='product-title']",
            "[class*='title']",
        )

        for selector in selectors:
            for element in card.select(selector):
                candidate = _clean(element.get_text(" ", strip=True))

                if (
                    candidate
                    and len(candidate) <= 250
                    and _matches(candidate, query)
                ):
                    name = candidate
                    break

            if name:
                break

        if not name and link_text and _matches(link_text, query):
            name = link_text

        if not name:
            continue

        price = _price(text)
        if not price:
            continue

        sold_out = any(word in low_text for word in SOLD_OUT_WORDS)

        if product_url in seen:
            continue

        seen.add(product_url)
        results.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": product_url,
            "available": not sold_out,
            "availability": "out_of_stock" if sold_out else "in_stock",
        })

    return results


def _extract_product_page(soup, url, query):
    json_results = _jsonld_products(soup, query)
    if json_results:
        return json_results

    text = _clean(soup.get_text(" ", strip=True))

    if not _matches(text, query):
        return []

    h1 = soup.find("h1")
    name = _clean(h1.get_text(" ", strip=True)) if h1 else ""

    if not name or not _matches(name, query):
        title = soup.find("title")
        title_text = _clean(title.get_text(" ", strip=True)) if title else ""

        if _matches(title_text, query):
            name = title_text

    if not name:
        return []

    price = _price(text)
    sold_out = any(word in text.lower() for word in SOLD_OUT_WORDS)

    if not price and not sold_out:
        return []

    return [{
        "store": STORE,
        "name": name,
        "price": price,
        "url": url.split("?")[0],
        "available": not sold_out,
        "availability": "out_of_stock" if sold_out else "in_stock",
    }]


def _parse_response(response, query):
    soup = BeautifulSoup(response.text, "html.parser")

    results = _jsonld_products(soup, query)
    if results:
        return results

    results = _extract_cards(soup, query)
    if results:
        return results

    if _is_product_url(response.url):
        results = _extract_product_page(soup, response.url, query)
        if results:
            return results

    return []


def search(query):
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    # Deloox usa più versioni/localizzazioni del sito.
    # Proviamo endpoint generici senza eccezioni per singoli profumi.
    search_urls = [
        f"{BASE_URL}/search?q={quote_plus(query)}",
        f"{BASE_URL}/search?query={quote_plus(query)}",
        f"{BASE_URL}/en/search?q={quote_plus(query)}",
        f"{BASE_URL}/en/search?query={quote_plus(query)}",
    ]

    for search_url in search_urls:
        try:
            response = session.get(
                search_url,
                timeout=12,
                allow_redirects=True,
            )

            print(
                "DELOOX DEBUG:",
                "requested=", search_url,
                "status=", response.status_code,
                "final_url=", response.url,
                "html_chars=", len(response.text or ""),
            )

            if response.status_code != 200 or not response.text:
                print("DELOOX DEBUG: skipped response")
                continue

            results = _parse_response(response, query)

            print(
                "DELOOX DEBUG:",
                "query=", query,
                "results=", len(results),
            )

            if results:
                print("DELOOX DEBUG FIRST RESULT:", results[0])
                return results[:10]

        except requests.RequestException as error:
            print("DELOOX ERROR:", error)
            continue

    return []


if __name__ == "__main__":
    for test_query in (
        "Liquid Brun",
        "Hawas Ice",
        "Aromatix Magnetiq",
        "Miu Miu",
    ):
        print(test_query, search(test_query))
