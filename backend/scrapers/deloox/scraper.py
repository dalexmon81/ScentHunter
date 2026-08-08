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
    url_tokens = set(
        _tokens(product_url)
    )

    query_tokens = set(
        _tokens(query)
    )

    return query_tokens.issubset(url_tokens)


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

        # Controllo fondamentale contro prodotti estranei.
        if not _url_matches_query(
            product_url,
            query,
        ):
            continue

        card = _find_product_card(link)

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

        card_tokens = set(
            _tokens(card_text)
        )

        if not query_tokens.issubset(card_tokens):
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
            and _matches_soft(
                link_name,
                query,
                minimum=0.55,
            )
        ):
            product_name = link_name

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
            min(index + 30, len(strings)),
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
            continue

        seen_sizes.add(size_label)

        slug = re.sub(
            r"[^a-z0-9]+",
            "-",
            size_label.lower(),
        ).strip("-")

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


def _search_limited_edition(session, category_html, query):
    """
    Dedicated resolver for Limited Edition variants.

    Deloox places the Limited Edition inside the Liquid Brun category, while
    the product URL/card can omit the words "limited edition". Therefore:
      1) collect every Liquid Brun product link from the category;
      2) open each real product page;
      3) identify the Limited Edition from the complete page text;
      4) use the existing variant extractor for the final offer.
    Normal Deloox searches never enter this function.
    """
    query_tokens = set(
        _tokens(query)
    )

    base_tokens = query_tokens - {
        "limited",
        "edition",
    }

    soup = BeautifulSoup(
        category_html,
        "html.parser",
    )

    candidates = []
    seen = set()

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

        if product_url in seen:
            continue

        seen.add(product_url)

        card = _find_product_card(link)

        parts = [
            _clean(
                link.get_text(
                    " ",
                    strip=True,
                )
            ),
            _clean(
                link.get("title")
            ),
            _clean(
                link.get("aria-label")
            ),
            _clean(
                link.get("data-product-name")
            ),
            _clean(
                link.get("data-name")
            ),
            _clean(
                card.get_text(
                    " ",
                    strip=True,
                )
            ),
        ]

        node = link
        for _ in range(8):
            if node is None:
                break

            parts.append(
                _clean(
                    node.get_text(
                        " ",
                        strip=True,
                    )
                )
            )

            node = node.parent

        context = _clean(
            " ".join(
                part
                for part in parts
                if part
            )
        )

        context_tokens = set(
            _tokens(context)
        )

        # Candidate only needs to be the requested base perfume.
        if not base_tokens.issubset(
            context_tokens
        ):
            continue

        candidates.append(
            (
                product_url,
                context,
            )
        )

    if not candidates:
        return []

    results = []
    seen_results = set()

    for product_url, context in candidates:
        product_response = _get(
            session,
            product_url,
        )

        if product_response is None:
            continue

        page_text = _clean(
            BeautifulSoup(
                product_response.text,
                "html.parser",
            ).get_text(
                " ",
                strip=True,
            )
        )

        page_text_normalized = _norm(
            page_text
        )

        # The decisive test is the complete product page, not its URL.
        if not {
            "limited",
            "edition",
        }.issubset(
            set(page_text_normalized.split())
        ):
            # Also accept an exact marker in the raw HTML after accent
            # normalization, in case it is inside structured data/metadata.
            raw_normalized = _norm(
                product_response.text
            )

            if not {
                "limited",
                "edition",
            }.issubset(
                set(raw_normalized.split())
            ):
                continue

        variants = _extract_product_variants(
            product_response.text,
            query,
            product_url,
        )

        if not variants:
            variants = _extract_jsonld_variants(
                product_response.text,
                query,
                product_url,
            )

        if variants:
            for variant in variants:
                key = (
                    variant.get("url", ""),
                    variant.get("size", ""),
                    variant.get("price", ""),
                )

                if key in seen_results:
                    continue

                seen_results.add(key)
                results.append(variant)

            continue

        # Last-resort offer from the category/product page itself.
        # This is still only used after the page has positively identified
        # Limited Edition.
        price = _extract_price(
            page_text
        )

        if not price:
            price = _extract_price(
                context
            )

        if price:
            results.append({
                "store": STORE,
                "name": "Liquid Brun Limited Edition",
                "price": price,
                "url": product_url,
                "available": True,
                "availability": "in_stock",
            })

    return results


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

    response = _get(
        session,
        category_url,
    )

    if response is None:
        return []

    limited_query = {
        "limited",
        "edition",
    }.issubset(
        set(_tokens(query))
    )

    if limited_query:
        limited_results = _search_limited_edition(
            session,
            response.text,
            query,
        )

        if limited_results:
            return limited_results[:20]

        return []

    candidates = _extract_category(
        response.text,
        query,
    )

    if not candidates:
        candidates = _extract_brand_page(
            response.text,
            query,
        )

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
