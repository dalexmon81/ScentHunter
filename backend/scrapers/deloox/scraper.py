import json
import re
import unicodedata
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
HOME_URL = f"{BASE_URL}/en"
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

PRICE_RE = re.compile(
    r"""
    (?:
        €\s*(?P<euro_before>\d{1,4})\s*(?:[,.^]\s*)+(?P<cents_before>\d{2})\s*\^*
        |
        (?P<euro_after>\d{1,4})\s*(?:[,.^]\s*)+(?P<cents_after>\d{2})\s*\^*\s*€
        |
        €\s*(?P<integer_before>\d{1,4})(?![\d.,])
        |
        (?P<integer_after>\d{1,4})\s*€
    )
    """,
    re.I | re.X,
)

SOLD_OUT = (
    "sold out",
    "out of stock",
    "not available",
    "currently unavailable",
)

NON_FRAGRANCE = (
    "body mist", "body spray", "body lotion", "body cream", "body oil",
    "body wash", "shower gel", "shower oil", "hand and body", "hand cream",
    "deodorant", "after shave", "aftershave", "hair mist", "hair spray", "soap",
)

SIZE_RE = re.compile(r"\b(\d{1,3}(?:[.,]\d+)?)\s*ml\b", re.I)
SIZE_FULL_RE = re.compile(r"^(\d{1,3}(?:[.,]\d+)?)\s*ml$", re.I)

CATEGORY_FALLBACKS = (
    (("liquid", "brun"), "https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html"),
    (("french", "avenue"), "https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html"),
    (("le", "beau", "le", "parfum"), "https://www.deloox.com/category/1084243/le-beau-le-parfum.html"),
    (("jean", "paul", "gaultier"), "https://www.deloox.com/category/1072906/jean-paul-gaultier-fragrances.html"),
    (("miu", "miu"), "https://www.deloox.com/category/1071574/miu-miu-fragrances.html"),
)

NON_FRAGRANCE_TOKENS = {
    tuple(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())
    for value in NON_FRAGRANCE
}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    value = unicodedata.normalize("NFKD", _clean(value).lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _tokens(value):
    return [token for token in _norm(value).split() if len(token) > 1]


def _matches_soft(text, query, minimum=0.55):
    text_tokens = set(_tokens(text))
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return False
    found = sum(token in text_tokens for token in query_tokens)
    return found / len(query_tokens) >= minimum


def _match_score(text, query):
    text_tokens = _tokens(text)
    query_tokens = _tokens(query)
    if not query_tokens:
        return -9999
    text_set = set(text_tokens)
    query_set = set(query_tokens)
    found = sum(token in text_set for token in query_set)
    if found == 0:
        return -9999
    missing = len(query_set) - found
    extras = [token for token in text_tokens if token not in query_set]
    return found * 100 - missing * 35 - len(extras) * 3 - abs(len(text_tokens) - len(query_tokens))


def _extract_price(text):
    if not text:
        return None
    match = PRICE_RE.search(_clean(text))
    if not match:
        return None
    if match.group("euro_before"):
        return f"{match.group('euro_before')},{match.group('cents_before')} €"
    if match.group("euro_after"):
        return f"{match.group('euro_after')},{match.group('cents_after')} €"
    if match.group("integer_before"):
        return f"{match.group('integer_before')},00 €"
    if match.group("integer_after"):
        return f"{match.group('integer_after')},00 €"
    return None


def _get(session, url):
    try:
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        return response
    except requests.RequestException as error:
        print(f"DELOOX ERROR: {error}")
        return None


def _query_wants_non_fragrance(query):
    query_tokens = set(_tokens(query))
    return any(set(phrase).issubset(query_tokens) for phrase in NON_FRAGRANCE_TOKENS)


def _contains_non_fragrance_product(text):
    tokens = _tokens(text)
    for phrase in NON_FRAGRANCE_TOKENS:
        size = len(phrase)
        for index in range(len(tokens) - size + 1):
            if tuple(tokens[index:index + size]) == phrase:
                return True
    return False


def _is_relevant_product(text, query):
    if not _matches_soft(text, query, minimum=0.55):
        return False
    if not _query_wants_non_fragrance(query) and _contains_non_fragrance_product(text):
        return False
    return True


def _find_brand_category(session, query):
    query_tokens = set(_tokens(query))

    if query_tokens == {"liquid", "brun"}:
        return "https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html"

    if {"liquid", "brun", "limited", "edition"}.issubset(query_tokens):
        return "https://www.deloox.com/en/category/1132834/liquid-brun.html"

    for required_tokens, fallback_url in CATEGORY_FALLBACKS:
        if set(required_tokens).issubset(query_tokens):
            return fallback_url

    response = _get(session, HOME_URL)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    candidates = []

    for link in soup.find_all("a", href=True):
        name = _clean(link.get_text(" ", strip=True))
        href = _clean(link.get("href"))
        if not name or not href:
            continue
        url = urljoin(BASE_URL, href)
        if "/category/" not in url.lower():
            continue
        category_tokens = set(_tokens(name))
        overlap = len(category_tokens & query_tokens)
        if overlap:
            candidates.append((overlap, overlap / len(category_tokens), url))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _find_product_card(link):
    node = link
    for _ in range(8):
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if _extract_price(text) or SIZE_RE.search(text):
            return node
        node = node.parent
    return link


def _url_matches_query(product_url, query):
    url_tokens = set(_tokens(product_url))
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return False
    if query_tokens.issubset(url_tokens):
        return True
    found = sum(1 for token in query_tokens if token in url_tokens)
    return found / len(query_tokens) >= 0.55


def _url_matches_name(product_url, product_name):
    """
    Check that the URL identifies the same product name.

    A card can contain several anchors, and the visible title can be correct
    while one of the anchors points somewhere else. We therefore require the
    product URL to carry a meaningful overlap with the exact product name.
    Brand words alone are not enough.
    """
    url_tokens = set(_tokens(product_url))
    name_tokens = set(_tokens(product_name))
    if not url_tokens or not name_tokens:
        return False

    # Product URLs normally contain the distinctive product-line tokens.
    # Ignore generic words that are frequently absent from slugs.
    generic = {
        "jean", "paul", "gaultier", "eau", "de", "toilette", "parfum",
        "edp", "edt", "intense", "edition", "for", "men", "women",
    }
    distinctive = [token for token in name_tokens if token not in generic]

    if not distinctive:
        return _matches_soft(product_url, product_name, minimum=0.60)

    found = sum(token in url_tokens for token in distinctive)
    return found / len(distinctive) >= 0.60


def _product_anchor_name(link):
    """Return only text that belongs to this exact product anchor."""
    values = [
        _clean(link.get_text(" ", strip=True)),
        _clean(link.get("title") or ""),
        _clean(link.get("aria-label") or ""),
    ]
    for value in values:
        if value and not SIZE_FULL_RE.fullmatch(value):
            return value
    return ""


def _product_container(link):
    """
    Find the smallest useful product card around an exact /product/ anchor.

    The old scraper climbed a fixed number of parents until it found a price or
    size. On modern Deloox pages that can cross the product-card boundary and
    attach the title/price of one product to the URL of another product.
    """
    node = link
    for _ in range(6):
        if node is None:
            break

        product_links = []
        for anchor in node.find_all("a", href=True):
            href = urljoin(BASE_URL, _clean(anchor.get("href"))).split("?")[0]
            if "/product/" in href.lower():
                product_links.append(href)

        if len(set(product_links)) == 1:
            return node

        node = node.parent

    return link


def _extract_category(html, query):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    query_tokens = set(_tokens(query))

    # Deloox product cards contain several anchors (image, title, sizes,
    # price). The product URL must always come from the exact product anchor,
    # never from an unrelated anchor inside a broad parent container.
    product_anchors = []
    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        product_url = urljoin(BASE_URL, href).split("?")[0]
        if "/product/" not in product_url.lower():
            continue
        product_anchors.append((link, product_url))

    for link, product_url in product_anchors:
        anchor_name = _product_anchor_name(link)

        # If this anchor itself identifies another product, never borrow the
        # name from a surrounding card.
        if anchor_name and not _is_relevant_product(anchor_name, query):
            continue

        container = _product_container(link)
        container_text = _clean(container.get_text(" ", strip=True))

        if any(word in container_text.lower() for word in SOLD_OUT):
            continue

        # The query must be supported by product-specific evidence first.
        # We allow the surrounding card to supply the title only when it
        # contains exactly one product URL.
        product_name = anchor_name
        if not product_name:
            headings = []
            for tag in ("h1", "h2", "h3", "h4"):
                for heading in container.find_all(tag):
                    value = _clean(heading.get_text(" ", strip=True))
                    if value:
                        headings.append(value)

            for value in headings:
                if _is_relevant_product(value, query):
                    product_name = value
                    break

        if not product_name:
            # Last safe fallback: inspect links that point to the exact same
            # product URL. This is safer than borrowing text from a broad
            # ancestor and also handles image/price anchors with no text.
            for sibling in soup.find_all("a", href=True):
                sibling_url = urljoin(
                    BASE_URL, _clean(sibling.get("href"))
                ).split("?")[0]
                if sibling_url != product_url:
                    continue
                value = _product_anchor_name(sibling)
                if value and _is_relevant_product(value, query):
                    product_name = value
                    break

        if not product_name or not _is_relevant_product(product_name, query):
            continue

        # Never pair a visible product name with an unrelated URL.
        if not _url_matches_name(product_url, product_name):
            continue

        if not _url_matches_query(product_url, query):
            # For searches such as "Le Beau", the product title is the
            # authoritative discovery signal; do not reject a correct product
            # solely because Deloox's slug is incomplete.
            if not _matches_soft(product_name, query, minimum=0.80):
                continue

        price = _extract_price(container_text)
        if not price:
            continue

        if product_url in seen:
            continue
        seen.add(product_url)

        results.append({
            "store": STORE,
            "name": product_name,
            "price": price,
            "url": product_url,
            "available": True,
            "availability": "in_stock",
        })

    return results

def _extract_brand_page(html, query):
    """
    Extract products from a brand/category page without mixing a card title
    with the first product URL found in a larger ancestor.

    The old implementation could climb into a container containing several
    products and then choose the first matching /product/ link inside it.
    That is exactly the kind of title/URL mismatch we saw with Le Beau -> Le Male.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        product_url = urljoin(BASE_URL, href).split("?")[0]
        if "/product/" not in product_url.lower():
            continue

        anchor_name = _product_anchor_name(link)

        # A visible product name and its URL must agree before we use them.
        if anchor_name:
            if not _is_relevant_product(anchor_name, query):
                continue
            if not _url_matches_name(product_url, anchor_name):
                continue

        container = _product_container(link)
        text = _clean(container.get_text(" ", strip=True))

        if any(word in text.lower() for word in SOLD_OUT):
            continue

        product_name = anchor_name
        if not product_name:
            for sibling in soup.find_all("a", href=True):
                sibling_url = urljoin(
                    BASE_URL, _clean(sibling.get("href"))
                ).split("?")[0]
                if sibling_url != product_url:
                    continue
                value = _product_anchor_name(sibling)
                if value and _is_relevant_product(value, query):
                    product_name = value
                    break

        if not product_name or not _is_relevant_product(product_name, query):
            continue

        if not _url_matches_name(product_url, product_name):
            continue

        if not _url_matches_query(product_url, query):
            if not _matches_soft(product_name, query, minimum=0.80):
                continue

        price = _extract_price(text)
        if not price:
            continue

        if product_url in seen:
            continue

        seen.add(product_url)
        results.append({
            "store": STORE,
            "name": product_name,
            "price": price,
            "url": product_url,
            "available": True,
            "availability": "in_stock",
        })

    return results

def _page_product_names(html):
    """Extract authoritative product names from the product page."""
    soup = BeautifulSoup(html, "html.parser")
    names = []

    for node in soup.find_all("h1"):
        value = _clean(node.get_text(" ", strip=True))
        if value:
            names.append(value)

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue

        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            item_type = str(item.get("@type", "")).lower()
            if item_type == "product":
                value = _clean(item.get("name"))
                if value:
                    names.append(value)

            for key in ("mainEntity", "item", "@graph"):
                child = item.get(key)
                if child:
                    stack.extend(child if isinstance(child, list) else [child])

    # Keep order and remove duplicates.
    unique = []
    seen = set()
    for name in names:
        key = _norm(name)
        if key and key not in seen:
            seen.add(key)
            unique.append(name)
    return unique


def _page_matches_query(html, query):
    """
    FINAL PRODUCT-ID CHECK.

    The category/URL search is only discovery. Before a Deloox link is returned,
    the actual product page must identify itself as the requested product.
    This blocks cases where a category result/redirect points to a different
    fragrance (for example Le Beau -> Le Male).
    """
    names = _page_product_names(html)
    if not names:
        return False

    # Prefer an exact token match; never accept a page merely because the URL
    # contains some of the requested words.
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return False

    for name in names:
        name_tokens = set(_tokens(name))
        if query_tokens.issubset(name_tokens):
            if _is_relevant_product(name, query):
                return True

    # A small fallback is allowed for generic searches such as "Le Beau",
    # where the product page may append concentration/size/marketing text.
    return any(_matches_soft(name, query, minimum=0.80) for name in names)


def _extract_product_variants(html, product_name, product_url):
    soup = BeautifulSoup(html, "html.parser")
    strings = [_clean(value) for value in soup.stripped_strings if _clean(value)]

    results = []
    seen_sizes = set()

    for index, value in enumerate(strings):
        size_match = SIZE_FULL_RE.fullmatch(value)
        if not size_match:
            continue

        size = size_match.group(1).replace(",", ".")
        size_label = f"{size} ml"

        if size_label in seen_sizes:
            continue

        chunk = []
        sold_out = False
        for next_index in range(index + 1, min(index + 30, len(strings))):
            next_value = strings[next_index]
            if SIZE_FULL_RE.fullmatch(next_value):
                break
            chunk.append(next_value)
            if any(word in next_value.lower() for word in SOLD_OUT):
                sold_out = True
                break

        if sold_out:
            continue

        price = _extract_price(" ".join(chunk))
        if not price:
            continue

        seen_sizes.add(size_label)
        slug = re.sub(r"[^a-z0-9]+", "-", size_label.lower()).strip("-")

        results.append({
            "store": STORE,
            "name": f"{product_name} {size_label}",
            "price": price,
            "url": f"{product_url}#{slug}",
            "available": True,
            "availability": "in_stock",
            "size": size_label,
        })

    return results


def _extract_jsonld_variants(html, product_name, product_url):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue

        objects = data if isinstance(data, list) else [data]
        for item in objects:
            if not isinstance(item, dict):
                continue

            item_text = " ".join([
                str(item.get("name", "")),
                str(item.get("description", "")),
            ])
            size_match = SIZE_RE.search(item_text)
            if not size_match:
                continue

            size = size_match.group(1).replace(",", ".")
            offers = item.get("offers", [])
            if isinstance(offers, dict):
                offers = [offers]

            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                price = offer.get("price")
                if price is None:
                    continue
                if str(offer.get("priceCurrency", "EUR")) != "EUR":
                    continue
                availability = str(offer.get("availability", "")).lower()
                if "outofstock" in availability:
                    continue

                price_text = str(price).replace(".", ",")
                if "," not in price_text:
                    price_text += ",00"

                results.append({
                    "store": STORE,
                    "name": f"{product_name} {size} ml",
                    "price": f"{price_text} €",
                    "url": product_url,
                    "available": True,
                    "availability": "in_stock",
                    "size": f"{size} ml",
                })

    return results


def _size_number(item):
    match = SIZE_RE.search(item.get("size", ""))
    if not match:
        return 9999
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return 9999


def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    try:
        category_url = _find_brand_category(session, query)
        if not category_url:
            return []

        response = _get(session, category_url)
        if response is None:
            return []

        candidates = _extract_category(response.text, query)
        if not candidates:
            candidates = _extract_brand_page(response.text, query)
        if not candidates:
            return []

        scored = []
        seen_urls = set()

        for item in candidates:
            product_url = item["url"].split("#")[0].split("?")[0]
            if product_url in seen_urls:
                continue
            if not _url_matches_query(product_url, query):
                continue
            seen_urls.add(product_url)
            scored.append((_match_score(item["name"], query), item))

        if not scored:
            return []

        scored.sort(key=lambda item: item[0], reverse=True)
        best_score = scored[0][0]
        minimum_score = best_score - 45

        final_results = []
        seen_variants = set()

        for score, item in scored:
            if score < minimum_score:
                break

            product_url = item["url"].split("#")[0].split("?")[0]
            product_response = _get(session, product_url)
            if product_response is None:
                continue

            # NEW: verify the real product page before exposing any offer.
            if not _page_matches_query(product_response.text, query):
                continue

            variants = _extract_product_variants(
                product_response.text,
                item["name"],
                product_url,
            )
            if not variants:
                variants = _extract_jsonld_variants(
                    product_response.text,
                    item["name"],
                    product_url,
                )

            for variant in variants:
                key = (
                    variant["url"],
                    variant.get("size", ""),
                    variant["price"],
                )
                if key in seen_variants:
                    continue
                seen_variants.add(key)
                final_results.append(variant)

        if final_results:
            final_results.sort(key=_size_number)
            return final_results[:20]

        # IMPORTANT: do not fall back to unverified candidates.
        # The old fallback could return a wrong product link after the
        # variant extraction failed.
        return []

    finally:
        session.close()


if __name__ == "__main__":
    queries = (
        "Tom Ford Neroli Portofino",
        "Miu Miu Miutine",
        "Le Beau Le Parfum",
        "Jean Paul Gaultier Le Beau Le Parfum",
        "Rasasi Hawas Ice",
    )

    for query in queries:
        print("\nQUERY:", query)
        results = search(query)
        if not results:
            print("NESSUN RISULTATO")
        else:
            for result in results:
                print(result)
