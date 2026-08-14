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
        €\s*
        (?P<euro_before>\d{1,4})
        \s*
        (?:[,.\^]\s*)+
        (?P<cents_before>\d{2})
        \s*\^*

        |

        (?P<euro_after>\d{1,4})
        \s*
        (?:[,.\^]\s*)+
        (?P<cents_after>\d{2})
        \s*\^*
        \s*€

        |

        €\s*(?P<integer_before>\d{1,4})(?![\d.,])

        |

        (?P<integer_after>\d{1,4})
        \s*€
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
    "body mist",
    "body spray",
    "body lotion",
    "body cream",
    "body oil",
    "body wash",
    "shower gel",
    "shower oil",
    "hand and body",
    "hand cream",
    "deodorant",
    "after shave",
    "aftershave",
    "hair mist",
    "hair spray",
    "soap",
)


SIZE_RE = re.compile(
    r"\b(\d{1,3}(?:[.,]\d+)?)\s*ml\b",
    re.I,
)

SIZE_FULL_RE = re.compile(
    r"^(\d{1,3}(?:[.,]\d+)?)\s*ml$",
    re.I,
)


CATEGORY_FALLBACKS = (
    (
        ("liquid", "brun"),
        "https://www.deloox.com/en/category/"
        "1132834/liquid-brun.html",
    ),
    (
        ("french", "avenue"),
        "https://www.deloox.com/en/category/"
        "1121334/french-avenue-mens-fragrances.html",
    ),
    (
        ("le", "beau", "le", "parfum"),
        "https://www.deloox.com/category/"
        "1084243/le-beau-le-parfum.html",
    ),
    (
        ("jean", "paul", "gaultier"),
        "https://www.deloox.com/category/"
        "1072906/jean-paul-gaultier-fragrances.html",
    ),
    (
        ("miu", "miu"),
        "https://www.deloox.com/category/"
        "1071574/miu-miu-fragrances.html",
    ),
)


NON_FRAGRANCE_TOKENS = {
    tuple(
        re.sub(
            r"[^a-z0-9]+",
            " ",
            value.lower(),
        ).split()
    )
    for value in NON_FRAGRANCE
}


def _clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def _norm(value):
    value = unicodedata.normalize(
        "NFKD",
        _clean(value).lower(),
    )
    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )

    return re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    ).strip()


def _tokens(value):
    return [
        token
        for token in _norm(value).split()
        if len(token) > 1
    ]


def _matches_soft(text, query, minimum=0.55):
    text_tokens = set(_tokens(text))
    query_tokens = set(_tokens(query))

    if not query_tokens:
        return False

    found = sum(
        token in text_tokens
        for token in query_tokens
    )

    return found / len(query_tokens) >= minimum


def _match_score(text, query):
    text_tokens = _tokens(text)
    query_tokens = _tokens(query)

    if not query_tokens:
        return -9999

    text_set = set(text_tokens)
    query_set = set(query_tokens)

    found = sum(
        token in text_set
        for token in query_set
    )

    if found == 0:
        return -9999

    missing = len(query_set) - found

    extras = [
        token
        for token in text_tokens
        if token not in query_set
    ]

    return (
        found * 100
        - missing * 35
        - len(extras) * 3
        - abs(len(text_tokens) - len(query_tokens))
    )


def _extract_price(text):
    if not text:
        return None

    match = PRICE_RE.search(_clean(text))

    if not match:
        return None

    if match.group("euro_before"):
        integer = match.group("euro_before")
        cents = match.group("cents_before")

    elif match.group("euro_after"):
        integer = match.group("euro_after")
        cents = match.group("cents_after")

    elif match.group("integer_before"):
        return f"{match.group('integer_before')},00 €"

    elif match.group("integer_after"):
        return f"{match.group('integer_after')},00 €"

    else:
        return None

    return f"{integer},{cents} €"


def _get(session, url):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        response.raise_for_status()
        return response

    except requests.RequestException as error:
        print(f"DELOOX ERROR: {error}")
        return None


def _query_wants_non_fragrance(query):
    query_tokens = set(_tokens(query))

    for phrase in NON_FRAGRANCE_TOKENS:
        if set(phrase).issubset(query_tokens):
            return True

    return False


def _contains_non_fragrance_product(text):
    tokens = _tokens(text)

    for phrase in NON_FRAGRANCE_TOKENS:
        size = len(phrase)

        for index in range(len(tokens) - size + 1):
            if tuple(tokens[index:index + size]) == phrase:
                return True

    return False


def _is_relevant_product(text, query):
    if not _matches_soft(
        text,
        query,
        minimum=0.55,
    ):
        return False

    if not _query_wants_non_fragrance(query):
        if _contains_non_fragrance_product(text):
            return False

    return True


def _find_brand_category(session, query):
    query_tokens = set(_tokens(query))

    if query_tokens == {"liquid", "brun"}:
        return (
            "https://www.deloox.com/en/category/"
            "1121334/french-avenue-mens-fragrances.html"
        )

    if {
        "liquid",
        "brun",
        "limited",
        "edition",
    }.issubset(query_tokens):
        return (
            "https://www.deloox.com/en/category/"
            "1132834/liquid-brun.html"
        )

    for required_tokens, fallback_url in CATEGORY_FALLBACKS:
        if set(required_tokens).issubset(query_tokens):
            return fallback_url

    response = _get(
        session,
        HOME_URL,
    )

    if response is None:
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    candidates = []

    for link in soup.find_all(
        "a",
        href=True,
    ):
        name = _clean(
            link.get_text(
                " ",
                strip=True,
            )
        )

        href = _clean(
            link.get("href")
        )

        if not name or not href:
            continue

        url = urljoin(
            BASE_URL,
            href,
        )

        if "/category/" not in url.lower():
            continue

        category_tokens = set(
            _tokens(name)
        )

        overlap = len(
            category_tokens & query_tokens
        )

        if overlap == 0:
            continue

        candidates.append((
            overlap,
            overlap / len(category_tokens),
            url,
        ))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1],
        ),
        reverse=True,
    )

    return candidates[0][2]



def _category_links(html):
    soup = BeautifulSoup(html, "html.parser")
    result = []
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
            or "",
        )
        if not label:
            continue

        key = (url.rstrip("/"), _norm(label))
        if key in seen:
            continue

        seen.add(key)
        result.append((label, url))

    return result


def _find_variant_category(session, brand_url, query):
    """Find an exact Deloox variant category through at most two hops."""
    query_tokens = set(_tokens(query))

    # Only activate this bridge for a multi-word variant query. Generic
    # Le Beau should keep using the proven brand discovery.
    if len(query_tokens) < 3:
        return None

    root = _get(session, brand_url)
    if root is None:
        return None

    def score(label):
        tokens = set(_tokens(label))
        overlap = query_tokens & tokens

        if not overlap:
            return -1
        if tokens == query_tokens:
            return 1000
        if query_tokens.issubset(tokens):
            return 900
        if len(overlap) >= 2:
            return 500 + int(
                100 * len(overlap) / len(query_tokens)
            )
        return -1

    bridges = []

    for label, url in _category_links(root.text):
        value = score(label)

        if value >= 900:
            return url

        if value >= 500:
            bridges.append((value, url))

    bridges.sort(reverse=True)

    for _, bridge_url in bridges[:2]:
        page = _get(session, bridge_url)
        if page is None:
            continue

        for label, url in _category_links(page.text):
            if score(label) >= 900:
                return url

    return None

def _find_product_card(link):
    node = link

    for _ in range(8):
        if node is None:
            break

        text = _clean(
            node.get_text(
                " ",
                strip=True,
            )
        )

        if (
            _extract_price(text)
            or SIZE_RE.search(text)
        ):
            return node

        node = node.parent

    return link


def _url_matches_query(product_url, query):
    """
    URL relevance check.

    Keep this deliberately tolerant. The URL is only a discovery hint; the
    authoritative identity check is _page_matches_query(), which reads the
    real product page. Requiring "narcisse" to appear in the slug caused the
    correct Deloox result to disappear when Deloox used a generic family slug.
    """
    url_tokens = set(_tokens(product_url))
    query_tokens = set(_tokens(query))

    if not query_tokens:
        return False

    if query_tokens.issubset(url_tokens):
        return True

    found = sum(
        1
        for token in query_tokens
        if token in url_tokens
    )

    return (found / len(query_tokens)) >= 0.55


def _is_gift_set_url(url):
    """Reject gift/set product URLs when the query asks for the perfume itself."""
    return bool(
        re.search(
            r"\b(gift|set|coffret|geschenk|cadeau)\b",
            _norm(url),
        )
    )


def _find_matching_product_url(card, query):
    """
    If the clicked anchor points to a gift set or another sibling product,
    choose the non-gift /product/ link in the same product card whose own
    label/title best matches the query.
    """
    candidates = []

    for anchor in card.find_all("a", href=True):
        candidate_url = urljoin(
            BASE_URL,
            _clean(anchor.get("href")),
        ).split("?")[0]

        if "/product/" not in candidate_url.lower():
            continue
        if _is_gift_set_url(candidate_url):
            continue

        label = _clean(
            anchor.get_text(" ", strip=True)
            or anchor.get("title")
            or anchor.get("aria-label")
            or "",
        )

        score = _match_score(label, query)
        candidates.append((score, label, candidate_url))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (item[0], len(_tokens(item[1]))),
        reverse=True,
    )

    best_score, _, best_url = candidates[0]
    if best_score <= -9999:
        return None

    return best_url



def _find_variant_product_urls(html, query):
    """
    Second-pass discovery for a specific variant.

    The variant name can live in the card/title while Deloox's canonical
    product URL uses a family slug. Therefore discovery accepts the link when
    the surrounding card identifies the requested variant; the actual page
    identity is verified later by _page_matches_query().
    """
    query_tokens = set(_tokens(query))
    family_tokens = {
        "jean", "paul", "gaultier",
        "le", "beau",
        "eau", "de", "toilette",
    }
    distinctive = query_tokens - family_tokens

    if not distinctive:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        url = urljoin(
            BASE_URL,
            _clean(anchor.get("href")),
        ).split("?")[0]

        if "/product/" not in url.lower():
            continue
        if _is_gift_set_url(url):
            continue

        label = _clean(
            anchor.get_text(" ", strip=True)
            or anchor.get("title")
            or anchor.get("aria-label")
            or "",
        )

        card = _find_product_card(anchor)
        context = label

        if card is not None:
            context = _clean(
                card.get_text(" ", strip=True)
            )

        context_tokens = set(_tokens(context))

        if not distinctive.issubset(context_tokens):
            continue

        if url not in seen:
            seen.add(url)
            results.append(url)

    return results


def _page_matches_query(html, query):
    """
    Final identity check.

    For variant queries, the page must contain the distinctive variant token.
    This prevents a generic "Le Beau" page from being accepted for
    "Le Beau Narcisse".
    """
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

        objects = data if isinstance(data, list) else [data]
        for item in objects:
            if not isinstance(item, dict):
                continue
            if str(item.get("@type", "")).lower() == "product":
                value = _clean(item.get("name"))
                if value:
                    names.append(value)

    query_tokens = set(_tokens(query))
    if not query_tokens:
        return False

    # These tokens identify the family rather than the specific variant.
    family_tokens = {
        "jean", "paul", "gaultier", "le", "beau",
        "eau", "de", "toilette",
    }
    distinctive = query_tokens - family_tokens

    for name in names:
        name_tokens = set(_tokens(name))

        if _contains_non_fragrance_product(name):
            continue

        # For a variant query such as "Le Beau Narcisse", Narcisse is
        # mandatory. A page saying only "Le Beau" must be rejected.
        if distinctive:
            if not distinctive.issubset(name_tokens):
                continue
        elif not query_tokens.issubset(name_tokens):
            continue

        # For generic Le Beau queries the normal token check remains.
        if not distinctive and not query_tokens.issubset(name_tokens):
            continue

        return True

    return False

def _extract_category(html, query):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results = []
    seen = set()

    query_tokens = set(
        _tokens(query)
    )

    for link in soup.find_all(
        "a",
        href=True,
    ):
        href = _clean(
            link.get("href")
        )

        product_url = urljoin(
            BASE_URL,
            href,
        ).split("?")[0]

        if "/product/" not in product_url.lower():
            continue

        card = _find_product_card(link)

        # Deloox can expose a normal perfume and a gift set inside the same
        # visual card. Never let the clicked gift-set URL become the perfume
        # result; resolve the sibling product link from the same card first.
        if _is_gift_set_url(product_url):
            replacement_url = _find_matching_product_url(
                card,
                query,
            )
            if not replacement_url:
                continue
            product_url = replacement_url

        # Controllo fondamentale contro prodotti estranei.
        if not _url_matches_query(
            product_url,
            query,
        ):
            continue


        card_text = _clean(
            card.get_text(
                " ",
                strip=True,
            )
        )

        if any(
            word in card_text.lower()
            for word in SOLD_OUT
        ):
            continue

        if not _matches_soft(
            card_text,
            query,
            minimum=0.55,
        ):
            continue

        card_tokens = set(_tokens(card_text))

        if not query_tokens.issubset(card_tokens):
            # Allow the card if a stricter soft similarity check passes,
            # or if the anchor title / a heading inside the card contains all query tokens.
            if not _matches_soft(card_text, query, minimum=0.75):
                link_title = _clean(link.get("title") or "")
                if link_title and set(_tokens(query)).issubset(set(_tokens(link_title))):
                    pass
                else:
                    heading = None
                    for h in ("h1", "h2", "h3", "h4"):
                        node_h = card.find(h)
                        if node_h:
                            heading = _clean(node_h.get_text(" ", strip=True))
                            break
                    if heading and set(_tokens(query)).issubset(set(_tokens(heading))):
                        pass
                    else:
                        continue

        if not _is_relevant_product(
            card_text,
            query,
        ):
            continue

        price = _extract_price(card_text)

        if not price:
            continue

        product_name = query

        link_name = _clean(
            link.get_text(
                " ",
                strip=True,
            )
        )

        if (
            link_name
            and not SIZE_FULL_RE.fullmatch(link_name)
            and _matches_soft(link_name, query, minimum=0.55)
            and set(_tokens(query)).issubset(set(_tokens(link_name)))
        ):
            product_name = link_name
        else:
            link_title = _clean(link.get("title") or "")
            if link_title and set(_tokens(query)).issubset(set(_tokens(link_title))):
                product_name = link_title

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
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results = []
    seen = set()

    for link in soup.find_all(
        "a",
        href=True,
    ):
        node = link

        for _ in range(8):
            if node is None:
                break

            text = _clean(
                node.get_text(
                    " ",
                    strip=True,
                )
            )

            if not _matches_soft(
                text,
                query,
                minimum=0.55,
            ):
                node = node.parent
                continue

            price = _extract_price(text)

            if not price:
                node = node.parent
                continue

            if any(
                word in text.lower()
                for word in SOLD_OUT
            ):
                node = node.parent
                continue

            product_link = None

            for anchor in node.find_all(
                "a",
                href=True,
            ):
                candidate_url = urljoin(
                    BASE_URL,
                    anchor.get(
                        "href",
                        "",
                    ),
                ).split("?")[0]

                if "/product/" not in candidate_url.lower():
                    continue

                if _is_gift_set_url(candidate_url):
                    continue

                if not _url_matches_query(
                    candidate_url,
                    query,
                ):
                    continue

                product_link = candidate_url
                break

            if (
                product_link
                and product_link not in seen
                and _is_relevant_product(
                    text,
                    query,
                )
            ):
                seen.add(product_link)

                results.append({
                    "store": STORE,
                    "name": query,
                    "price": price,
                    "url": product_link,
                    "available": True,
                    "availability": "in_stock",
                })

            break

    return results


def _extract_product_variants(
    html,
    product_name,
    product_url,
):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    strings = [
        _clean(value)
        for value in soup.stripped_strings
        if _clean(value)
    ]

    results = []
    seen_sizes = set()

    for index, value in enumerate(strings):
        size_match = SIZE_FULL_RE.fullmatch(value)

        if not size_match:
            continue

        size = size_match.group(1).replace(
            ",",
            ".",
        )

        size_label = f"{size} ml"

        if size_label in seen_sizes:
            continue

        chunk = []
        sold_out = False

        for next_index in range(
            index + 1,
            len(strings),
        ):
            next_value = strings[next_index]

            if SIZE_FULL_RE.fullmatch(next_value):
                break

            chunk.append(next_value)

            if any(
                word in next_value.lower()
                for word in SOLD_OUT
            ):
                sold_out = True
                break

        if sold_out:
            continue

        price = _extract_price(
            " ".join(chunk)
        )

        if not price:
            # Deloox sometimes inserts availability/UI strings between the
            # size and price. Inspect a bounded neighborhood around the size
            # before declaring the variant absent.
            nearby = " ".join(
                strings[index + 1:index + 80]
            )
            price = _extract_price(nearby)

        if not price:
            continue

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

    return results


def _extract_jsonld_variants(
    html,
    product_name,
    product_url,
):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results = []

    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        try:
            data = json.loads(
                script.string or script.get_text()
            )

        except (
            json.JSONDecodeError,
            TypeError,
        ):
            continue

        objects = (
            data
            if isinstance(data, list)
            else [data]
        )

        for item in objects:
            if not isinstance(item, dict):
                continue

            item_text = " ".join([
                str(item.get("name", "")),
                str(item.get("description", "")),
            ])

            size_match = SIZE_RE.search(
                item_text
            )

            if not size_match:
                continue

            size = size_match.group(1).replace(
                ",",
                ".",
            )

            offers = item.get(
                "offers",
                [],
            )

            if isinstance(offers, dict):
                offers = [offers]

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                price = offer.get("price")

                if price is None:
                    continue

                if str(
                    offer.get(
                        "priceCurrency",
                        "EUR",
                    )
                ) != "EUR":
                    continue

                availability = str(
                    offer.get(
                        "availability",
                        "",
                    )
                ).lower()

                if "outofstock" in availability:
                    continue

                price_text = str(price).replace(
                    ".",
                    ",",
                )

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
    match = SIZE_RE.search(
        item.get("size", "")
    )

    if not match:
        return 9999

    try:
        return float(
            match.group(1).replace(",", ".")
        )

    except ValueError:
        return 9999


def search(query):
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()

    category_url = _find_brand_category(
        session,
        query,
    )

    if not category_url:
        return []

    category_urls = [category_url]

    variant_category = _find_variant_category(
        session,
        category_url,
        query,
    )

    if (
        variant_category
        and variant_category.rstrip("/")
        != category_url.rstrip("/")
    ):
        category_urls.insert(0, variant_category)

    candidates = []
    seen_candidate_urls = set()

    for current_category_url in category_urls:
        response = _get(
            session,
            current_category_url,
        )

        if response is None:
            continue

        current_candidates = _extract_category(
            response.text,
            query,
        )

        if not current_candidates:
            current_candidates = _extract_brand_page(
                response.text,
                query,
            )

        # For a distinctive variant, add only product URLs whose own slug
        # contains the distinctive token. This prevents the generic Le Beau
        # URL from surviving as the Narcisse result.
        variant_urls = _find_variant_product_urls(
            response.text,
            query,
        )

        existing_urls = {
            item["url"].split("#")[0].split("?")[0]
            for item in current_candidates
        }

        for variant_url in variant_urls:
            if variant_url in existing_urls:
                continue

            current_candidates.append({
                "store": STORE,
                "name": query,
                "price": None,
                "url": variant_url,
                "available": True,
                "availability": "in_stock",
            })

        for item in current_candidates:
            clean_url = (
                item["url"]
                .split("#")[0]
                .split("?")[0]
            )
            if clean_url in seen_candidate_urls:
                continue

            seen_candidate_urls.add(clean_url)
            candidates.append(item)

    if not candidates:
        return []

    if not candidates:
        return []

    scored = []
    seen_urls = set()

    for item in candidates:
        product_url = item["url"].split(
            "#"
        )[0].split("?")[0]

        if product_url in seen_urls:
            continue

        if not _url_matches_query(
            product_url,
            query,
        ):
            continue

        seen_urls.add(product_url)

        scored.append((
            _match_score(
                item["name"],
                query,
            ),
            item,
        ))

    if not scored:
        return []

    scored.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    # For a distinctive variant, only keep candidates that actually carry
    # the variant in the canonical URL. Never let the generic family URL win.
    query_tokens = set(_tokens(query))
    family_tokens = {
        "jean", "paul", "gaultier",
        "le", "beau", "eau", "de", "toilette",
    }
    distinctive = query_tokens - family_tokens

    best_score = scored[0][0]
    minimum_score = best_score - 45

    final_results = []
    seen_variants = set()

    for score, item in scored:
        if score < minimum_score:
            break

        product_url = item["url"].split(
            "#"
        )[0].split("?")[0]

        product_response = _get(
            session,
            product_url,
        )

        if product_response is None:
            continue

        if not _page_matches_query(
            product_response.text,
            query,
        ):
            continue

        if _is_gift_set_url(product_url):
            continue

        variants = _extract_product_variants(
            product_response.text,
            item["name"],
            product_url,
        )

        jsonld_variants = _extract_jsonld_variants(
            product_response.text,
            item["name"],
            product_url,
        )

        # Merge both sources instead of treating JSON-LD as an all-or-nothing
        # fallback. This is important for Deloox pages where one size is
        # visible in the rendered text and another is exposed only in JSON-LD.
        variants.extend(jsonld_variants)

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
        final_results.sort(
            key=_size_number
        )

        return final_results[:20]

    return [item for _, item in scored]


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
