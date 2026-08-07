import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
HOME_URL = BASE_URL + "/en"
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
        ("jean", "paul", "gaultier"),
        "https://www.deloox.com/category/"
        "1072906/jean-paul-gaultier-fragrances.html",
    ),
    (
        ("le", "beau", "le", "parfum"),
        "https://www.deloox.com/category/"
        "1053446/le-beau.html",
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
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        _clean(value).lower(),
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
    """
    Supporta, tra gli altri, questi formati:

    € 71, ^69^
    € 71,69
    € 71.69
    71, ^69^ €
    71,69 €
    € 30
    30 €
    """
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
        phrase_length = len(phrase)

        for index in range(
            len(tokens) - phrase_length + 1
        ):
            current = tuple(
                tokens[index:index + phrase_length]
            )

            if current == phrase:
                return True

    return False


def _is_relevant_product(name, query):
    if not _matches_soft(
        name,
        query,
        minimum=0.55,
    ):
        return False

    if not _query_wants_non_fragrance(query):
        if _contains_non_fragrance_product(name):
            return False

    return True


def _find_brand_category(session, query):
    """
    Cerca prima le categorie note.
    Se non trova una corrispondenza, cerca le categorie
    presenti nella homepage Deloox.
    """
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

        if not category_tokens:
            continue

        overlap = len(
            category_tokens & query_tokens
        )

        if overlap == 0:
            continue

        coverage = overlap / len(category_tokens)

        candidates.append({
            "url": url,
            "overlap": overlap,
            "coverage": coverage,
            "token_count": len(category_tokens),
        })

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item["overlap"],
            item["coverage"],
            -item["token_count"],
        ),
        reverse=True,
    )

    return candidates[0]["url"]


def _find_product_card(link):
    """
    Trova il contenitore della card che contiene
    nome, formato, disponibilità e prezzo.
    """
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


def _extract_category(html, query):
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

        if not _is_relevant_product(
            card_text,
            query,
        ):
            continue

        price = _extract_price(card_text)

        if not price:
            continue

        # Il singolo link può contenere solo "75 ml"
        # o "125 ml". In quel caso non va usato come
        # nome del prodotto.
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

        result_key = (
            product_url,
            product_name,
        )

        if result_key in seen:
            continue

        seen.add(result_key)

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

            if _matches_soft(
                text,
                query,
                minimum=0.55,
            ):
                price = _extract_price(text)

                unavailable = any(
                    word in text.lower()
                    for word in SOLD_OUT
                )

                if price and not unavailable:
                    product_link = None
                    product_name = ""

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

                        candidate_name = _clean(
                            anchor.get_text(
                                " ",
                                strip=True,
                            )
                        )

                        if "/product/" in candidate_url.lower():
                            product_link = candidate_url

                            if (
                                candidate_name
                                and not SIZE_FULL_RE.fullmatch(
                                    candidate_name
                                )
                                and _matches_soft(
                                    candidate_name,
                                    query,
                                    minimum=0.55,
                                )
                            ):
                                product_name = candidate_name
                            else:
                                product_name = query

                            break

                    if (
                        product_link
                        and _is_relevant_product(
                            text,
                            query,
                        )
                        and product_link not in seen
                    ):
                        seen.add(product_link)

                        results.append({
                            "store": STORE,
                            "name": product_name or query,
                            "price": price,
                            "url": product_link,
                            "available": True,
                            "availability": "in_stock",
                        })

                break

            node = node.parent

    return results


def _extract_direct_products(html, query):
    """
    Fallback che cerca direttamente i link /product/.
    """
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
        href = _clean(
            link.get("href")
        )

        name = _clean(
            link.get_text(
                " ",
                strip=True,
            )
        )

        if not href:
            continue

        product_url = urljoin(
            BASE_URL,
            href,
        ).split("?")[0]

        if "/product/" not in product_url.lower():
            continue

        card = _find_product_card(link)

        card_text = _clean(
            card.get_text(
                " ",
                strip=True,
            )
        )

        if not _matches_soft(
            card_text,
            query,
            minimum=0.55,
        ):
            continue

        if any(
            word in card_text.lower()
            for word in SOLD_OUT
        ):
            continue

        price = _extract_price(card_text)

        if not price:
            continue

        if product_url in seen:
            continue

        seen.add(product_url)

        product_name = query

        if (
            name
            and not SIZE_FULL_RE.fullmatch(name)
            and _matches_soft(
                name,
                query,
                minimum=0.55,
            )
        ):
            product_name = name

        results.append({
            "store": STORE,
            "name": product_name,
            "price": price,
            "url": product_url,
            "available": True,
            "availability": "in_stock",
        })

    return results


def _extract_product_variants(
    html,
    product_name,
    product_url,
):
    """
    Estrae formato e prezzo dalla pagina prodotto.
    """
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
    """
    Fallback per formati e prezzi presenti nei JSON-LD.
    """
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

            offers = item.get(
                "offers",
                [],
            )

            if isinstance(offers, dict):
                offers = [offers]

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

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                price = offer.get("price")

                currency = str(
                    offer.get(
                        "priceCurrency",
                        "EUR",
                    )
                )

                availability = str(
                    offer.get(
                        "availability",
                        "",
                    )
                ).lower()

                if price is None:
                    continue

                if currency != "EUR":
                    continue

                if any(
                    word in availability
                    for word in (
                        "outofstock",
                        "soldout",
                    )
                ):
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

    response = _get(
        session,
        category_url,
    )

    if response is None:
        return []

    category_results = _extract_category(
        response.text,
        query,
    )

    if not category_results:
        category_results = _extract_brand_page(
            response.text,
            query,
        )

    if not category_results:
        category_results = _extract_direct_products(
            response.text,
            query,
        )

    candidates = []
    seen_urls = set()

    for item in category_results:
        name = item.get(
            "name",
            "",
        )

        url = item.get(
            "url",
            "",
        ).split("#")[0].split("?")[0]

        if not url or url in seen_urls:
            continue

        if not _is_relevant_product(
            name,
            query,
        ):
            continue

        seen_urls.add(url)

        candidates.append((
            _match_score(name, query),
            item,
        ))

    if not candidates:
        return []

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    best_score = candidates[0][0]
    minimum_score = best_score - 45

    final_results = []
    seen_variants = set()

    for score, item in candidates:
        if score < minimum_score:
            break

        clean_url = item["url"].split(
            "#"
        )[0].split("?")[0]

        product_response = _get(
            session,
            clean_url,
        )

        if product_response is None:
            continue

        variants = _extract_product_variants(
            product_response.text,
            item["name"],
            clean_url,
        )

        if not variants:
            variants = _extract_jsonld_variants(
                product_response.text,
                item["name"],
                clean_url,
            )

        for variant in variants:
            key = (
                _norm(item["name"]),
                _norm(
                    variant.get(
                        "size",
                        "",
                    )
                ),
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

    return [candidates[0][1]]


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
