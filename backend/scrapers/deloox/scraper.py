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

NON_FRAGRANCE_TOKENS = {
    tuple(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())
    for value in NON_FRAGRANCE
}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


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
    Riconosce anche i prezzi Deloox nella forma:

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

    text = _clean(text)
    match = PRICE_RE.search(text)

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
    if not _matches_soft(name, query, minimum=0.55):
        return False

    if not _query_wants_non_fragrance(query):
        if _contains_non_fragrance_product(name):
            return False

    return True


def _find_brand_category(session, query):
    """
    Cerca la categoria Deloox più compatibile con la query.
    """
    response = _get(session, HOME_URL)

    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    query_tokens = set(_tokens(query))
    candidates = []

    for link in soup.find_all("a", href=True):
        name = _clean(
            link.get_text(" ", strip=True)
        )
        href = _clean(link.get("href"))

        if not name or not href:
            continue

        url = urljoin(BASE_URL, href)

        if "/category/" not in url.lower():
            continue

        category_tokens = set(_tokens(name))

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
            "name": name,
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
    Risale dal link al contenitore della card prodotto.
    """
    node = link

    for _ in range(8):
        if node is None:
            break

        text = _clean(
            node.get_text(" ", strip=True)
        )

        if _extract_price(text) or SIZE_RE.search(text):
            return node

        node = node.parent

    return link


def _extract_category(html, query):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        product_url = urljoin(
            BASE_URL,
            href,
        ).split("?")[0]

        if "/product/" not in product_url.lower():
            continue

        card = _find_product_card(link)
        card_text = _clean(
            card.get_text(" ", strip=True)
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

        product_name = _clean(
            link.get_text(" ", strip=True)
        )

        if not product_name:
            product_name = query

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
        node = link

        for _ in range(8):
            if node is None:
                break

            text = _clean(
                node.get_text(" ", strip=True)
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
                            anchor.get("href", ""),
                        ).split("?")[0]

                        candidate_name = _clean(
                            anchor.get_text(" ", strip=True)
                        )

                        if "/product/" in candidate_url.lower():
                            product_link = candidate_url

                            if candidate_name:
                                product_name = candidate_name

                            break

                    if (
                        product_link
                        and _is_relevant_product(text, query)
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
    Fallback: cerca direttamente i link /product/
    nella pagina ricevuta.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        name = _clean(
            link.get_text(" ", strip=True)
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
            card.get_text(" ", strip=True)
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

        results.append({
            "store": STORE,
            "name": name or query,
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
    Estrae le coppie formato/prezzo dalla pagina prodotto.
    """
    soup = BeautifulSoup(html, "html.parser")

    strings = [
        _clean(value)
        for value in soup.stripped_strings
        if _clean(value)
    ]

    results = []
    seen_sizes = set()

    for index, value in enumerate(strings):
