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

    query_tokens = set(_tokens(query))
    if not _query_wants_non_fragrance(query) and _contains_non_fragrance_product(text):
        return False

    # A gift set is a different commercial product from the perfume itself.
    # Only accept it when the user explicitly searched for a set.
    if "gift" not in query_tokens and "set" not in query_tokens:
        if re.search(r"\bgift\s+set\b", _norm(text)):
            return False

    return True



def _category_links_from_page(html):
    """Return Deloox category links with their visible labels."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        url = urljoin(BASE_URL, href).split("?")[0]
        if "/category/" not in url.lower():
            continue

        label = _clean(
            link.get_text(" ", strip=True)
            or link.get("title")
            or link.get("aria-label")
            or ""
        )
        if not label:
            continue

        key = (url.rstrip("/"), _norm(label))
        if key in seen:
            continue
        seen.add(key)
        found.append((label, url))

    return found


def _category_match_score(label, query):
    """Score a Deloox taxonomy label against the requested variant."""
    q = set(_tokens(query))
    l = set(_tokens(label))
    if not q or not l:
        return -1

    overlap = len(q & l)
    if not overlap:
        return -1

    coverage = overlap / len(q)
    precision = overlap / len(l)

    # Exact taxonomy match is strongest.
    if q == l:
        return 1000

    # Prefer labels that contain the complete query.
    if q.issubset(l):
        return 900 + int(100 * precision)

    # For family navigation, allow a parent such as "Le Beau" to be used
    # as a bridge to discover a child such as "Le Beau Narcisse".
    if overlap >= 2:
        return 500 + int(100 * coverage) + int(50 * precision)

    return -1


def _find_variant_category(session, brand_category_url, query):
    """
    Discover the requested Deloox variant through Deloox's own taxonomy.

    Important difference from the old implementation:
    1. inspect the brand category;
    2. if the exact variant is not there, follow the best family/category
       link and inspect its category navigation;
    3. return the exact variant category when Deloox exposes one.

    This mirrors Deloox's real navigation: the Jean Paul Gaultier area can
    expose "Le Beau", and a Le Beau category can expose siblings such as
    "Le Beau Flower Edition", "Le Beau Le Parfum" and "Le Beau Narcisse".
    """
    response = _get(session, brand_category_url)
    if response is None:
        return None

    direct = _category_links_from_page(response.text)
    candidates = []

    for label, url in direct:
        if url.rstrip("/") == brand_category_url.rstrip("/"):
            continue
        score = _category_match_score(label, query)
        if score >= 900:
            candidates.append((score, url))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    # No exact variant in the brand page. Use the best family bridge.
    bridge_candidates = []
    for label, url in direct:
        if url.rstrip("/") == brand_category_url.rstrip("/"):
            continue
        score = _category_match_score(label, query)
        if score >= 500:
            bridge_candidates.append((score, url))

    bridge_candidates.sort(reverse=True)

    # Inspect only a few high-quality taxonomy bridges. This is deliberately
    # shallow so a normal perfume search does not explode into a crawler.
    for _, bridge_url in bridge_candidates[:3]:
        bridge_response = _get(session, bridge_url)
        if bridge_response is None:
            continue

        for label, url in _category_links_from_page(bridge_response.text):
            score = _category_match_score(label, query)
            if score >= 900:
                return url

    return None

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


def _extract_product_candidates(html, query):
    """
    Discover canonical product URLs without requiring the anchor text to be
    a perfect copy of the query.

    The anchor, title, aria-label, nearby headings and product card are all
    candidate identity signals. They are NOT authoritative. Every candidate
    is later opened and checked against the real product page.
    """
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

        values = [
            _clean(link.get_text(" ", strip=True)),
            _clean(link.get("title") or ""),
            _clean(link.get("aria-label") or ""),
        ]

        # Use the nearest compact product context only as a discovery signal.
        card = _find_product_card(link)
        card_text = _clean(card.get_text(" ", strip=True))
        if card_text:
            values.append(card_text)

        # Headings inside the same product context are often the cleanest
        # visible identity, especially when the anchor contains only an icon.
        for heading in card.find_all(["h2", "h3", "h4"], limit=3):
            value = _clean(heading.get_text(" ", strip=True))
            if value:
                values.append(value)

        values = [
            value for value in values
            if value and not SIZE_FULL_RE.fullmatch(value)
        ]
        if not values:
            continue

        # Prefer the shortest strong identity containing query terms. This
        # avoids using an entire card as the product name.
        ranked = []
        for value in values:
            tokens = set(_tokens(value))
            overlap = len(tokens & query_tokens)
            score = _match_score(value, query)
            if overlap:
                score += overlap * 0.25
            ranked.append((score, -len(value), value))

        ranked.sort(reverse=True)
        identity = ranked[0][2]

        # Discovery is intentionally permissive. A candidate only needs a
        # meaningful relationship to the query in the card/context. The real
        # product page is checked later.
        if query_tokens:
            context_tokens = set(_tokens(" ".join(values)))
            if not (query_tokens & context_tokens):
                # For a query like "Le Beau Narcisse", Deloox may expose only
                # "Narcisse" in the local label. Keep it if a strong single
                # variant token is present; page validation will decide.
                continue

        if any(word in card_text.lower() for word in SOLD_OUT):
            continue

        if product_url in seen:
            continue
        seen.add(product_url)

        results.append({
            "store": STORE,
            "name": identity,
            "price": _extract_price(card_text),
            "url": product_url,
            "available": True,
            "availability": "in_stock",
        })

    return results


def _extract_category(html, query):
    return _extract_product_candidates(html, query)

def _extract_brand_page(html, query):
    return _extract_product_candidates(html, query)

def _page_product_names(html):
    """Extract authoritative product identity fields from the product page."""
    soup = BeautifulSoup(html, "html.parser")
    names = []

    # H1 is the strongest visible product identity.
    for node in soup.find_all("h1"):
        value = _clean(node.get_text(" ", strip=True))
        if value:
            names.append(value)

    # Deloox exposes "product line" in the product-information section.
    # Keep it as an additional identity signal, not as a replacement for H1.
    body_text = _clean(soup.get_text(" ", strip=True))
    product_line_match = re.search(
        r"\bproduct\s+line\b\s*[:\-]?\s*([A-Za-z0-9&'’.\- ]{3,120})",
        body_text,
        flags=re.I,
    )
    if product_line_match:
        value = _clean(product_line_match.group(1))
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
    """
    Extract every size/price pair from the actual Deloox product page.

    Deloox renders size blocks sequentially. A block can contain both a
    crossed/retail price and the current selling price. We therefore parse the
    text between one size marker and the next and take the LAST EUR price in
    that block. This keeps 75 ml and 125 ml attached to their own prices.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_sizes = set()

    def prices_in(text_value):
        value = _clean(text_value)

        # Deloox prints the reference price immediately before the current
        # selling price, e.g.:
        #   Retail price: 106.00 € 68,99
        # If we feed that whole string to PRICE_RE, the regex can stop on
        # "106.00 €" and never see the real price. Remove every retail-price
        # fragment first, then parse what remains.
        value = re.sub(
            r"\bretail\s+price\b\s*:?\s*€?\s*"
            r"\d{1,4}(?:[,.]\d{2})?",
            " ",
            value,
            flags=re.I,
        )

        found = []
        for match in PRICE_RE.finditer(value):
            if match.group("euro_before"):
                found.append(
                    f"{match.group('euro_before')},{match.group('cents_before')} €"
                )
            elif match.group("euro_after"):
                found.append(
                    f"{match.group('euro_after')},{match.group('cents_after')} €"
                )
            elif match.group("integer_before"):
                found.append(f"{match.group('integer_before')},00 €")
            elif match.group("integer_after"):
                found.append(f"{match.group('integer_after')},00 €")
        return found

    def add_variant(size_label, price):
        if not price or size_label in seen_sizes:
            return
        seen_sizes.add(size_label)
        results.append({
            "store": STORE,
            "name": f"{product_name} {size_label}",
            "price": price,
            "url": product_url,
            "available": True,
            "availability": "in_stock",
            "size": size_label,
        })

    # Use the rendered text order, not a broad ancestor/card.
    strings = [_clean(value) for value in soup.stripped_strings if _clean(value)]
    size_positions = []

    for index, value in enumerate(strings):
        match = SIZE_FULL_RE.fullmatch(value)
        if match:
            size_positions.append((index, f"{match.group(1).replace(',', '.')} ml"))

    for position, (index, size_label) in enumerate(size_positions):
        next_index = (
            size_positions[position + 1][0]
            if position + 1 < len(size_positions)
            else len(strings)
        )

        segment = " ".join(strings[index + 1:next_index])

        # Do not cross an obvious availability boundary. The price for this
        # size must occur before the next size marker.
        prices = prices_in(segment)
        if prices:
            add_variant(size_label, prices[-1])

    # Fallback: some versions of the page expose the size as an anchor and
    # omit it from the normal text stream. Only inspect the small anchor
    # subtree in that case; never climb to the whole product card.
    if not results:
        for anchor in soup.find_all("a", href=True):
            label = _clean(anchor.get_text(" ", strip=True))
            match = SIZE_FULL_RE.fullmatch(label)
            if not match:
                continue

            size_label = f"{match.group(1).replace(',', '.')} ml"
            local_text = _clean(anchor.parent.get_text(" ", strip=True))
            prices = prices_in(local_text)
            if prices:
                add_variant(size_label, prices[-1])

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

        # Always supplement a dedicated variant category with the brand
        # category. Deloox can expose only one size or an incomplete subset
        # in a dedicated category, while the brand page can expose the same
        # canonical product with the complete variant set. The final
        # product-page identity check prevents unrelated products from
        # surviving this broader discovery.
        if brand_category_url.rstrip("/") not in {
            url.rstrip("/") for url in category_urls
        }:
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

            authoritative_names = _page_product_names(product_response.text)
            authoritative_name = authoritative_names[0] if authoritative_names else item["name"]

            variants = _extract_product_variants(
                product_response.text,
                authoritative_name,
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
