import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin

BASE_URL = "https://www.perfumemarket.nl"
PRICE_RE = re.compile(r"€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€")


def _extract_price(text):
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return value.replace(".", ",") + " €"


def _tokens(text):
    return [t.lower() for t in re.findall(r"[a-z0-9]+", text or "", re.I) if t.strip()]


def _query_matches(text, query):
    query_tokens = _tokens(query)
    text_tokens = set(_tokens(text))
    return bool(query_tokens) and all(token in text_tokens for token in query_tokens)


def _product_name(container, fallback):
    if container is None:
        return fallback

    selectors = (
        "h1", "h2", "h3", "h4",
        ".product-title", ".product__title",
        ".product-name", ".product-card__title",
        "[class*='product-title']", "[class*='product-name']",
    )

    for selector in selectors:
        try:
            element = container.select_one(selector)
        except Exception:
            element = None
        if element:
            name = element.get_text(" ", strip=True)
            if name and len(name) <= 300:
                return name

    # Shopify product cards often expose the complete product title in
    # an aria-label/title even when the visible anchor only contains the brand.
    for element in container.find_all(["a", "img"], limit=20):
        value = (
            element.get("title")
            or element.get("aria-label")
            or element.get("alt")
            or ""
        ).strip()
        if value and _query_matches(value, fallback):
            return value

    return fallback


def _find_card(anchor):
    node = anchor

    for _ in range(8):
        if node is None:
            break

        text = node.get_text(" ", strip=True)
        if len(text) >= 20 and (_extract_price(text) or _query_matches(text, "")):
            # Stop at a reasonably small product block.
            if len(text) <= 1800:
                return node

        node = getattr(node, "parent", None)

    return anchor.parent


def _parse_search_html(html, query):
    soup = BeautifulSoup(html or "", "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        product_url = urljoin(BASE_URL, href).split("?")[0].rstrip("/")

        if "/products/" not in product_url.lower():
            continue
        if product_url in seen:
            continue

        card = _find_card(link)
        if card is None:
            continue

        card_text = card.get_text(" ", strip=True)
        name = _product_name(card, link.get_text(" ", strip=True))

        # IMPORTANT: match the query against the complete product card/name,
        # not only the text of the clicked anchor. On Shopify the anchor can
        # contain only the brand or an image.
        if not _query_matches(f"{name} {card_text} {product_url}", query):
            continue

        price = _extract_price(card_text)
        if not price:
            continue

        key = product_url.lower()
        seen.add(key)

        results.append({
            "store": "PerfumeMarket",
            "name": name,
            "price": price,
            "url": product_url,
        })

    return results


def _parse_search_suggest(payload, query):
    results = []
    seen = set()

    resources = payload.get("resources", {}) if isinstance(payload, dict) else {}
    nested = resources.get("results", {}) if isinstance(resources, dict) else {}
    products = nested.get("products", []) if isinstance(nested, dict) else []

    if not isinstance(products, list):
        return results

    for product in products:
        if not isinstance(product, dict):
            continue

        name = str(product.get("title") or product.get("name") or "").strip()
        url = str(product.get("url") or "").strip()

        if not name or not url or not _query_matches(name, query):
            continue

        product_url = urljoin(BASE_URL, url).split("?")[0].rstrip("/")
        if "/products/" not in product_url.lower():
            continue

        price = None

        variants = product.get("variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                raw_variant_price = str(variant.get("price") or "").strip()
                price = _extract_price(raw_variant_price)
                if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw_variant_price):
                    price = raw_variant_price.replace(".", ",") + " €"
                if price:
                    break

        if not price:
            raw_product_price = str(
                product.get("price")
                or product.get("price_min")
                or ""
            ).strip()
            price = _extract_price(raw_product_price)
            if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw_product_price):
                price = raw_product_price.replace(".", ",") + " €"

        if not price:
            continue

        key = product_url.lower()
        if key in seen:
            continue

        seen.add(key)
        results.append({
            "store": "PerfumeMarket",
            "name": name,
            "price": price,
            "url": product_url,
        })

    return results


def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/18.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept-Language": "en-US,en;q=0.8",
    }

    results = []
    seen = set()

    def add_items(items):
        for item in items or []:
            url = str(item.get("url") or "").lower()
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(item)

    # 1) Shopify predictive search. This is useful when the normal search
    # page is rendered differently or the product anchor contains only
    # the brand/image.
    suggest_url = (
        BASE_URL
        + "/search/suggest.json?q="
        + quote(query)
        + "&resources[type]=product&resources[limit]=20"
    )

    try:
        response = requests.get(
            suggest_url,
            headers=headers,
            timeout=12,
        )
        if response.ok:
            try:
                add_items(_parse_search_suggest(response.json(), query))
            except (ValueError, TypeError):
                pass
    except requests.RequestException as error:
        print(f"PERFUMEMARKET SUGGEST ERROR: {error}")

    # 2) Normal Shopify search page.
    if not results:
        search_urls = (
            BASE_URL + "/search?q=" + quote(query) + "&type=product",
            BASE_URL + "/search?q=" + quote(query),
        )

        for url in search_urls:
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=15,
                )
                response.raise_for_status()
            except requests.RequestException as error:
                print(f"PERFUMEMARKET ERROR: {error}")
                continue

            add_items(_parse_search_html(response.text, query))

            if results:
                break

    return results


if __name__ == "__main__":
    results = search("Hawas Malibu")

    print("RISULTATI:", len(results))

    for item in results[:10]:
        print(item)
