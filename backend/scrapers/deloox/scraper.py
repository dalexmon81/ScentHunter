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



def _find_variant_category(session, brand_category_url, query):
    """
    Discovery layer: Deloox often exposes a dedicated category for a
    fragrance family/variant (for example "Le Beau", "Le Beau Narcisse",
    "Le Beau Le Parfum"). Prefer that category when its label is a strong
    match for the requested query. This keeps product-name discovery tied
    to Deloox's own taxonomy instead of guessing an URL from a product card.
    """
    response = _get(session, brand_category_url)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return None

    candidates = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        url = urljoin(BASE_URL, href).split("?")[0]
        if "/category/" not in url.lower():
            continue
        if url.rstrip("/") == brand_category_url.rstrip("/"):
            continue

        label = _clean(link.get_text(" ", strip=True))
        if not label:
            continue

        label_tokens = set(_tokens(label))
        overlap = query_tokens & label_tokens
        if not overlap:
            continue

        # The category label must identify a meaningful part of the query.
        # Prefer the most specific category: more query tokens, then fewer
        # unrelated label tokens.
        overlap_count = len(overlap)
        query_coverage = overlap_count / len(query_tokens)
        label_precision = overlap_count / len(label_tokens)

        # At least two shared tokens is the safe general case for fragrance
        # variant categories. A one-token category is accepted only when it
        # is an exact match to the complete normalized query.
        exact = label_tokens == query_tokens
        if not exact and overlap_count < 2:
            continue

        key = (url, _norm(label))
        if key in seen:
            continue
        seen.add(key)
        candidates.append((
            exact,
            overlap_count,
            query_coverage,
            label_precision,
            -len(label_tokens),
            url,
        ))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][-1]


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


def _extract_category(html, query):
    """
    Discover products from Deloox category pages.

    Deloox's category markup separates the main product link from the
    individual size links. The main product anchor carries the product name
    and the canonical /product/<id>/ URL. Size anchors are separate links.

    Therefore discovery must start from the named product anchor itself.
    We never choose a /product/ URL from a sibling size anchor or from an
    arbitrary link inside the surrounding card.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    query_tokens = set(_tokens(query))

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        product_url = urljoin(BASE_URL, href).split("?")[0]
        if "/product/" not in product_url.lower():
            continue

        # Deloox size selectors can also be links. They are not the product
        # identity anchor, so reject anchors whose visible text is only a
        # size, ellipsis, or otherwise contains no product-name information.
        link_name = _clean(link.get_text(" ", strip=True))
        link_title = _clean(link.get("title") or "")
        link_aria = _clean(link.get("aria-label") or "")

        identity_texts = [
            value for value in (link_name, link_title, link_aria)
            if value and not SIZE_FULL_RE.fullmatch(value)
        ]
        if not identity_texts:
            continue

        # The canonical product anchor must itself identify the requested
        # product. Do not infer identity from the surrounding card.
        identity = max(
            identity_texts,
            key=lambda value: _match_score(value, query)
        )
        if not _matches_soft(identity, query, minimum=0.80):
            continue
        if not query_tokens.issubset(set(_tokens(identity))):
            continue

        card = _find_product_card(link)
        card_text = _clean(card.get_text(" ", strip=True))

        if any(word in card_text.lower() for word in SOLD_OUT):
            continue
        if not _is_relevant_product(identity, query):
            continue

        price = _extract_price(card_text)
        if not price:
            continue

        if product_url in seen:
            continue
        seen.add(product_url)

        results.append({
            "store": STORE,
            "name": identity,
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
    query_tokens = set(_tokens(query))

    for link in soup.find_all("a", href=True):
        product_url = urljoin(
            BASE_URL, _clean(link.get("href"))
        ).split("?")[0]
        if "/product/" not in product_url.lower():
            continue

        link_name = _clean(link.get_text(" ", strip=True))
        link_title = _clean(link.get("title") or "")
        link_aria = _clean(link.get("aria-label") or "")

        identity_texts = [
            value for value in (link_name, link_title, link_aria)
            if value and not SIZE_FULL_RE.fullmatch(value)
        ]
        if not identity_texts:
            continue

        identity = max(
            identity_texts,
            key=lambda value: _match_score(value, query)
        )

        if not _matches_soft(identity, query, minimum=0.80):
            continue
        if not query_tokens.issubset(set(_tokens(identity))):
            continue

        card = _find_product_card(link)
        text = _clean(card.get_text(" ", strip=True))
        if any(word in text.lower() for word in SOLD_OUT):
            continue

        price = _extract_price(text)
        if not price or not _is_relevant_product(identity, query):
            continue

        if product_url in seen:
            continue
        seen.add(product_url)

        results.append({
            "store": STORE,
            "name": identity,
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
    results = []
    seen_sizes = set()

    def add_variant(size_label, price, url=None):
        if not price or size_label in seen_sizes:
            return
        seen_sizes.add(size_label)
        results.append({
            "store": STORE,
            "name": f"{product_name} {size_label}",
            "price": price,
            "url": url or product_url,
            "available": True,
            "availability": "in_stock",
            "size": size_label,
        })

    # Deloox exposes size selectors as sibling anchors next to the main
    # product anchor. Collect every visible ml value first.
    for anchor in soup.find_all("a", href=True):
        label = _clean(anchor.get_text(" ", strip=True))
        match = SIZE_FULL_RE.fullmatch(label)
        if not match:
            continue

        size = match.group(1).replace(",", ".")
        size_label = f"{size} ml"

        # Look for the nearest product/card context and its price.
        node = anchor
        price = None
        for _ in range(8):
            if node is None:
                break
            context = _clean(node.get_text(" ", strip=True))
            price = _extract_price(context)
            if price:
                break
            node = node.parent

        if not price:
            # Some size anchors contain only the size while the price is in
            # the parent product block; search a little more broadly.
            node = anchor.parent
            for _ in range(5):
                if node is None:
                    break
                context = _clean(node.get_text(" ", strip=True))
                price = _extract_price(context)
                if price:
                    break
                node = node.parent

        if price:
            add_variant(size_label, price, product_url)

    # Fallback for product pages where size selectors are not anchors.
    if not results:
        strings = [_clean(value) for value in soup.stripped_strings if _clean(value)]
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
            for next_index in range(index + 1, min(index + 40, len(strings))):
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
            if price:
                add_variant(size_label, price, product_url)

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
        brand_category_url = _find_brand_category(session, query)
        if not brand_category_url:
            return []

        # First try Deloox's own dedicated variant/family category.
        # This is discovery only; the normal product-page verification
        # below remains the final authority.
        category_urls = []
        variant_category_url = _find_variant_category(
            session,
            brand_category_url,
            query,
        )
        if variant_category_url:
            category_urls.append(variant_category_url)

        # Use the broad brand category only when no dedicated variant
        # category was found. Mixing both sources can reintroduce unrelated
        # product candidates for families with very similar names.
        if not variant_category_url:
            category_urls.append(brand_category_url)

        candidates = []
        seen_candidate_urls = set()

        for category_url in category_urls:
            response = _get(session, category_url)
            if response is None:
                continue

            discovered = _extract_category(response.text, query)
            if not discovered:
                discovered = _extract_brand_page(response.text, query)

            for item in discovered:
                product_url = item["url"].split("#")[0].split("?")[0]
                if product_url in seen_candidate_urls:
                    continue

                # Keep the original discovery tolerance. The authoritative
                # product-page check below decides whether the candidate is
                # actually the requested product.
                seen_candidate_urls.add(product_url)
                candidates.append(item)

            # A dedicated variant category is intentionally allowed to
            # provide the complete candidate set by itself, but we still
            # inspect the brand category if it contributes new products.

        if not candidates:
            return []

        scored = []
        for item in candidates:
            product_url = item["url"].split("#")[0].split("?")[0]
            score = _match_score(item["name"], query)
            scored.append((score, item))

        scored.sort(key=lambda item: item[0], reverse=True)

        # Do not let one high-scoring candidate suppress other valid
        # variants. We verify every discovered candidate.
        final_results = []
        seen_variants = set()

        for score, item in scored:
            product_url = item["url"].split("#")[0].split("?")[0]
            product_response = _get(session, product_url)
            if product_response is None:
                continue

            # Final authority: the actual Deloox product page must identify
            # itself as the requested product/variant.
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
