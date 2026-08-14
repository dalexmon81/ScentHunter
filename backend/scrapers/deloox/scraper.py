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


def _unique_product_urls(node):
    """Return unique Deloox product URLs contained in this DOM node."""
    urls = []
    seen = set()
    for anchor in node.find_all("a", href=True):
        href = _clean(anchor.get("href"))
        if "/product/" not in href.lower():
            continue
        url = urljoin(BASE_URL, href).split("?")[0].rstrip("/")
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _nearest_product_context(link):
    """
    Find the smallest DOM container that represents this product.

    The old scraper climbed to the first ancestor containing a price/size.
    On some Deloox layouts that ancestor can contain neighbouring products,
    so its first /product/ link is not necessarily the link for the name.

    We instead prefer the nearest ancestor that contains exactly one unique
    product URL. This keeps the product name and URL in the same DOM entity.
    """
    node = link.parent
    best = link

    for _ in range(12):
        if node is None:
            break

        urls = _unique_product_urls(node)
        if len(urls) == 1:
            best = node
            node = node.parent
            continue

        break

    return best


def _local_product_name(context, link, query):
    candidates = []

    for value in (
        link.get_text(" ", strip=True),
        link.get("title"),
        link.get("aria-label"),
        link.get("data-product-name"),
        link.get("data-name"),
    ):
        value = _clean(value)
        if value and not SIZE_FULL_RE.fullmatch(value):
            candidates.append(value)

    for tag in ("h1", "h2", "h3", "h4", "h5"):
        for node in context.find_all(tag):
            value = _clean(node.get_text(" ", strip=True))
            if value:
                candidates.append(value)

    # Prefer a local heading/name that actually matches the requested product.
    query_tokens = set(_tokens(query))
    ranked = []
    for value in candidates:
        score = _match_score(value, query)
        ranked.append((score, -len(_tokens(value)), value))

    if ranked:
        ranked.sort(reverse=True)
        return ranked[0][2]

    return query



def _local_matches_query(context_text, product_name, query):
    """
    Discovery-stage match.

    Short two-token searches such as "Le Beau" are allowed to match the
    family/variant text. Longer queries (for example "Le Beau Narcisse" or
    "Jean Paul Gaultier Le Beau Narcisse") must have every meaningful query
    token in the same local product context. This prevents Narcisse from
    borrowing the plain Le Beau URL while still allowing a family search to
    discover its variants.
    """
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return False

    combined = f"{product_name} {context_text}"
    combined_tokens = set(_tokens(combined))

    if len(query_tokens) >= 3:
        return query_tokens.issubset(combined_tokens)

    return _matches_soft(combined, query, minimum=0.55)

def _extract_category(html, query):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        product_url = urljoin(BASE_URL, href).split("?")[0].rstrip("/")
        if "/product/" not in product_url.lower():
            continue

        context = _nearest_product_context(link)
        context_text = _clean(context.get_text(" ", strip=True))

        if not context_text:
            continue
        if any(word in context_text.lower() for word in SOLD_OUT):
            continue
        product_name = _local_product_name(context, link, query)
        if not _local_matches_query(context_text, product_name, query):
            continue
        if not _is_relevant_product(f"{product_name} {context_text}", query):
            continue

        price = _extract_price(context_text)
        if not price:
            continue

        # Never manufacture an association between a name and another URL.
        # The URL here is the URL of THIS anchor.
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
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        product_url = urljoin(BASE_URL, href).split("?")[0].rstrip("/")
        if "/product/" not in product_url.lower():
            continue

        context = _nearest_product_context(link)
        text = _clean(context.get_text(" ", strip=True))

        if not text:
            continue
        if any(word in text.lower() for word in SOLD_OUT):
            continue
        product_name = _local_product_name(context, link, query)
        if not _local_matches_query(text, product_name, query):
            continue
        if not _is_relevant_product(f"{product_name} {text}", query):
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
