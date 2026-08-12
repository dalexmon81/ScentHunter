import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, quote_plus, urljoin

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



def _parse_product_sitemap_locs(xml_text, query):
    """Return product URLs whose Shopify handle contains every query token."""
    if not xml_text:
        return []

    query_tokens = set(_tokens(query))
    if not query_tokens:
        return []

    soup = BeautifulSoup(xml_text, "xml")
    urls = []
    seen = set()

    for loc in soup.find_all("loc"):
        url = str(loc.get_text(strip=True) or "")
        if "/products/" not in url.lower():
            continue
        handle = url.lower().split("/products/", 1)[-1]
        handle_tokens = set(_tokens(handle.replace("-", " ")))
        if not query_tokens.issubset(handle_tokens):
            continue
        clean = url.split("?", 1)[0].rstrip("/")
        if clean and clean not in seen:
            seen.add(clean)
            urls.append(clean)

    return urls


def _find_candidates_from_sitemap(session, query):
    """Generic Shopify sitemap fallback; no perfume-specific exceptions."""
    try:
        response = session.get(
            BASE_URL + "/sitemap.xml",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if response.status_code != 200 or not response.text:
            return []
    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "xml")
    sitemap_urls = []
    for loc in soup.find_all("loc"):
        url = str(loc.get_text(strip=True) or "")
        if "sitemap_products_" in url.lower():
            sitemap_urls.append(url)

    # Shopify normally exposes only a small number of product sitemaps.
    # Stop as soon as matching product URLs are found.
    for sitemap_url in sitemap_urls:
        try:
            response = session.get(
                sitemap_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
        except requests.RequestException:
            continue

        if response.status_code != 200 or not response.text:
            continue

        urls = _parse_product_sitemap_locs(response.text, query)
        if urls:
            return urls[:20]

    return []


def _parse_product_page(html, query, product_url):
    """Extract a product name and price from a direct Shopify product page."""
    soup = BeautifulSoup(html or "", "html.parser")

    title = ""
    for selector in ("h1", "meta[property='og:title']", "title"):
        element = soup.select_one(selector)
        if not element:
            continue
        title = (
            element.get("content", "")
            if element.name == "meta"
            else element.get_text(" ", strip=True)
        ).strip()
        if title:
            break

    if not title:
        return None

    # Product pages can contain several prices. Prefer JSON-LD/product data,
    # then fall back to visible page text.
    price = None
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue

        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            offers = obj.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if not isinstance(offers, list):
                continue
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                price = _extract_price(str(offer.get("price") or ""))
                if not price:
                    raw_price = str(offer.get("price") or "").strip()
                    if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw_price):
                        price = raw_price.replace(".", ",") + " €"
                if price:
                    break
            if price:
                break
        if price:
            break

    if not price:
        price = _extract_price(soup.get_text(" ", strip=True))

    if not price or not _query_matches(title + " " + product_url, query):
        return None

    return {
        "store": "PerfumeMarket",
        "name": title,
        "price": price,
        "url": product_url,
    }

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

    session = requests.Session()
    session.headers.update(headers)
    results = []
    seen = set()

    def add_items(items):
        for item in items or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").split("?", 1)[0].rstrip("/").lower()
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(item)

    # 1) Shopify predictive search. Always run it, but never stop the search
    # here: a partial predictive response must not hide a valid product found
    # by another generic Shopify search method.
    suggest_urls = (
        BASE_URL
        + "/search/suggest.json?q="
        + quote(query)
        + "&resources[type]=product&resources[limit]=20",
        BASE_URL
        + "/search/suggest.json?q="
        + quote(query)
        + "&resources[type]=product&resources[limit]=20"
        + "&resources[options][unavailable_products]=last",
    )

    for suggest_url in suggest_urls:
        try:
            response = session.get(suggest_url, timeout=10)
            if response.ok:
                try:
                    add_items(_parse_search_suggest(response.json(), query))
                except (ValueError, TypeError, json.JSONDecodeError):
                    pass
        except requests.RequestException as error:
            print(f"PERFUMEMARKET SUGGEST ERROR: {error}")

    # 2) Normal Shopify search. Always run both forms, even if predictive
    # search already found something. Results are deduplicated by URL.
    search_urls = (
        BASE_URL + "/search?q=" + quote(query) + "&type=product",
        BASE_URL + "/search?q=" + quote(query),
    )

    for url in search_urls:
        try:
            response = session.get(url, timeout=12)
            response.raise_for_status()
        except requests.RequestException as error:
            print(f"PERFUMEMARKET ERROR: {error}")
            continue

        add_items(_parse_search_html(response.text, query))

    # 3) Generic Shopify sitemap fallback. This is the important safety net:
    # if Shopify search indexing misses a product, the official product
    # sitemap still exposes its URL. No perfume is hard-coded.
    if not results:
        candidate_urls = _find_candidates_from_sitemap(session, query)
        for product_url in candidate_urls:
            try:
                response = session.get(product_url, timeout=12)
                response.raise_for_status()
            except requests.RequestException:
                continue

            item = _parse_product_page(response.text, query, product_url)
            if item:
                add_items([item])

    return results


if __name__ == "__main__":
    results = search("Hawas Malibu")

    print("RISULTATI:", len(results))

    for item in results[:10]:
        print(item)
