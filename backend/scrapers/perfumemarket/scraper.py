import json
import re
import time
import unicodedata
import difflib
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.perfumemarket.nl"
PRICE_RE = re.compile(r"€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€")


def log(msg):
    print(f"PERFUMEMARKET: {msg}")


def _extract_price(text):
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    value = match.group(1) or match.group(2)
    # Normalize representation to use comma as decimal separator and add euro symbol
    value = value.replace(".", ",")
    return value + " €"


def _normalize_text(s):
    """Normalize text by removing accents/diacritics and lowercasing."""
    if not s:
        return ""
    normalized = unicodedata.normalize("NFKD", str(s))
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    return without_accents.lower()


def _tokens(text):
    """
    Tokenize text robustly supporting Unicode letters and digits.
    Returns lowercase tokens with underscores removed.
    """
    if not text:
        return []
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    # \w includes underscore; we'll strip underscores later
    tokens = re.findall(r"[0-9\w]+", without_accents, flags=re.UNICODE)
    return [t.lower().replace("_", "") for t in tokens if t.strip() and not set(t) == {"_"}]


def _normalize_for_match(s):
    t = _normalize_text(s)
    # keep only alnum characters for compact matching
    return re.sub(r"[^0-9a-z]+", "", t, flags=re.UNICODE)


def _token_fuzzy_in_set(token, text_tokens):
    """
    Return True if token matches any token in text_tokens with fuzzy rules:
    - exact match
    - close match via difflib.get_close_matches (cutoff tuned)
    - simple plural/singular variants
    - SequenceMatcher ratio threshold for short near-misses
    """
    if token in text_tokens:
        return True

    # direct plural/singular heuristics
    if token.endswith("s") and token[:-1] in text_tokens:
        return True
    if (token + "s") in text_tokens:
        return True

    # use difflib close matches with a tolerant cutoff
    # cutoff tuned to accept small typos and man/men cases
    try:
        matches = difflib.get_close_matches(token, list(text_tokens), n=1, cutoff=0.72)
    except Exception:
        matches = []
    if matches:
        return True

    # fallback: SequenceMatcher ratio for tokens longer than 2 chars
    for t in text_tokens:
        if len(token) <= 2 or len(t) <= 2:
            continue
        ratio = difflib.SequenceMatcher(None, token, t).ratio()
        if ratio >= 0.8:
            return True

    return False


def _query_matches(text, query):
    """Generic product matching tolerant of spaces, hyphens, apostrophes, accents and small typos."""
    query = str(query or "")
    text = str(text or "")

    query_tokens = _tokens(query)
    if not query_tokens:
        return False

    text_tokens = set(_tokens(text))
    # Prefer strict token inclusion if possible, but allow fuzzy per-token matches
    all_matched = True
    for token in query_tokens:
        if not token:
            continue
        if _token_fuzzy_in_set(token, text_tokens):
            continue
        all_matched = False
        break
    if all_matched:
        return True

    # Shopify handles often normalize names differently from the visible query:
    # fallback to compact alphanumeric substring match (after normalization)
    compact_query = _normalize_for_match(query)
    compact_text = _normalize_for_match(text)
    if compact_query and compact_query in compact_text:
        return True

    return False


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

    # Look into title/aria-label/alt on anchors or images
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
        # Consider a node a product card if it has enough text length and either a price
        # or at least some tokens (we relax one previous strictness)
        if len(text) >= 20 and (_extract_price(text) or _tokens(text)):
            if len(text) <= 1800:
                return node

        node = getattr(node, "parent", None)

    return anchor.parent


def _extract_price_from_node(node):
    """
    Try to extract price from node by checking common data-attributes, itemprop,
    class names and text contents. Returns price string or None.
    """
    if node is None:
        return None

    # Common data attributes that may contain price
    for elem in node.find_all(True):
        # try attributes that might directly hold a numeric price
        for attr in ("data-price", "data-product-price", "data-final-price", "data-price-amount", "data-priceamount"):
            if elem.has_attr(attr):
                candidate = str(elem[attr]).strip()
                price = _extract_price(candidate) or (candidate.replace(".", ",") + " €" if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", candidate) else None)
                if price:
                    return price

        # itemprop="price" or meta/property patterns
        if elem.has_attr("itemprop") and elem["itemprop"].lower() == "price":
            candidate = elem.get("content") or elem.get_text(" ", strip=True)
            price = _extract_price(candidate) or (candidate.replace(".", ",") + " €" if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", candidate) else None)
            if price:
                return price

        # classes that likely contain price
        class_attr = " ".join(elem.get("class") or [])
        if class_attr and re.search(r"price|kosten|prijs|product-price|final-price", class_attr, re.I):
            candidate = elem.get("content") or elem.get_text(" ", strip=True)
            price = _extract_price(candidate) or (candidate.replace(".", ",") + " €" if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", candidate) else None)
            if price:
                return price

    # As last resort, search visible text in the node
    text = node.get_text(" ", strip=True)
    return _extract_price(text)


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

        # match the query against the complete product card/name/url
        if not _query_matches(f"{name} {card_text} {product_url}", query):
            continue

        # Try multiple ways to get price: from data attributes, special classes, visible text
        price = _extract_price_from_node(card)
        if not price:
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


def _parse_catalog_json(payload, query):
    """Parse Shopify's public product catalog JSON without relying on search ranking."""
    if not isinstance(payload, dict):
        return []

    products = payload.get("products")
    if not isinstance(products, list):
        return []

    results = []
    seen = set()

    for product in products:
        if not isinstance(product, dict):
            continue

        title = str(product.get("title") or product.get("name") or "").strip()
        handle = str(product.get("handle") or "").strip()
        if not title or not _query_matches(title + " " + handle.replace("-", " "), query):
            continue

        product_id = str(product.get("id") or handle or title).strip().lower()
        if product_id in seen:
            continue

        variants = product.get("variants")
        if not isinstance(variants, list):
            variants = []

        price = None
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            raw_price = str(variant.get("price") or "").strip()
            if not raw_price:
                continue
            price = _extract_price(raw_price)
            if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw_price):
                price = raw_price.replace(".", ",") + " €"
            if price:
                if variant.get("available") is True:
                    break

        if not price:
            raw_price = str(product.get("price") or "").strip()
            price = _extract_price(raw_price)
            if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw_price):
                price = raw_price.replace(".", ",") + " €"

        if not price:
            continue

        if handle:
            product_url = urljoin(BASE_URL, "/products/" + handle).rstrip("/")
        else:
            continue

        seen.add(product_id)
        results.append({
            "store": "PerfumeMarket",
            "name": title,
            "price": price,
            "url": product_url,
        })

    return results


def _find_candidates_from_catalog_json(session, query):
    """Search the public Shopify catalog, bypassing Shopify search relevance."""
    endpoints = (
        BASE_URL + "/products.json?limit=250",
        BASE_URL + "/collections/all-perfumes/products.json?limit=250",
    )

    matches = []
    seen = set()

    for base_endpoint in endpoints:
        for page in range(1, 21):
            separator = "&" if "?" in base_endpoint else "?"
            url = base_endpoint + separator + "page=" + str(page)
            try:
                response = session.get(url, timeout=12)
            except requests.RequestException:
                break

            if response.status_code != 200 or not response.text:
                break

            try:
                payload = response.json()
            except (ValueError, TypeError, json.JSONDecodeError):
                break

            products = payload.get("products") if isinstance(payload, dict) else None
            if not isinstance(products, list) or not products:
                break

            # add items from this page
            for item in _parse_catalog_json(payload, query):
                key = item["url"].rstrip("/").lower()
                if key in seen:
                    continue
                seen.add(key)
                matches.append(item)

            # Shopify normally returns fewer than the requested limit on the last page.
            if len(products) < 250:
                break

            # Soft cap: if we already have plenty, stop scanning
            if len(matches) >= 200:
                return matches

            # small delay to avoid hammering
            time.sleep(0.1)

    return matches


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
        if not _query_matches(handle.replace("-", " "), query):
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

    matches = []
    seen = set()

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

        for url in _parse_product_sitemap_locs(response.text, query):
            key = url.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            matches.append(url)
            if len(matches) >= 200:
                return matches

        # small delay to be polite
        time.sleep(0.05)

    return matches


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

    # Prefer JSON-LD/product data for price, then visible page text.
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
        # search common selectors
        price = _extract_price_from_node(soup)
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


def _create_session_with_retries():
    session = requests.Session()
    # retries for idempotent requests
    retries = Retry(total=3, backoff_factor=0.3, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(['GET','HEAD','OPTIONS']))
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def add_items_to_results(results, items, seen):
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").split("?", 1)[0].rstrip("/").lower()
        if not url or url in seen:
            continue
        seen.add(url)
        results.append(item)


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

    session = _create_session_with_retries()
    session.headers.update(headers)
    results = []
    seen = set()

    # 1) Shopify predictive search
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
                    items = _parse_search_suggest(response.json(), query)
                    if items:
                        log(f"FOUND {len(items)} via suggest")
                    add_items_to_results(results, items, seen)
                except (ValueError, TypeError, json.JSONDecodeError):
                    pass
        except requests.RequestException as error:
            log(f"SUGGEST ERROR: {error}")

    # 2) Normal Shopify search (HTML)
    search_urls = (
        BASE_URL + "/search?q=" + quote(query) + "&type=product",
        BASE_URL + "/search?q=" + quote(query),
    )

    for url in search_urls:
        try:
            response = session.get(url, timeout=12)
            response.raise_for_status()
        except requests.RequestException as error:
            log(f"SEARCH HTML ERROR: {error}")
            continue

        items = _parse_search_html(response.text, query)
        if items:
            log(f"FOUND {len(items)} via search-html ({url})")
        add_items_to_results(results, items, seen)

    # 3) Public Shopify product catalog discovery
    catalog_items = _find_candidates_from_catalog_json(session, query)
    if catalog_items:
        log(f"FOUND {len(catalog_items)} via catalog-json")
    add_items_to_results(results, catalog_items, seen)

    # 4) Sitemap: run as supplement if results below threshold to find missing handles.
    # This prevents running sitemap-only when everything already found, but still
    # allows finding products missing from catalog JSON or search endpoints.
    if len(results) < 200:
        candidate_urls = _find_candidates_from_sitemap(session, query)
        if candidate_urls:
            log(f"FOUND {len(candidate_urls)} candidate URLs via sitemap")
        for product_url in candidate_urls:
            key = product_url.rstrip("/").lower()
            if key in seen:
                continue
            try:
                response = session.get(product_url, timeout=12)
                response.raise_for_status()
            except requests.RequestException:
                continue

            item = _parse_product_page(response.text, query, product_url)
            if item:
                add_items_to_results(results, [item], seen)
                log(f"ADDED via sitemap: {item.get('url')}")
            if len(results) >= 400:
                break

    return results


if __name__ == "__main__":
    # Quick manual test if run as script
    queries = [
        "chanel no 5",
        "l'aventure",
        "dior sauvage",
        "1 club de nuit intense man",
    ]
    for q in queries:
        log(f"Searching for: {q}")
        res = search(q)
        log(f"Results for '{q}': {len(res)} items")
        for r in res[:10]:
            log(f" - {r.get('name')} @ {r.get('price')} -> {r.get('url')}")
