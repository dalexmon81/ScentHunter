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
        €\s*(?P<before>\d{1,4}(?:[.,]\d{2})?)
        |
        (?P<after>\d{1,4}(?:[.,]\d{2})?)\s*€
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

SIZE_RE = re.compile(r"\b(\d{1,3}(?:[.,]\d+)?)\s*ml\b", re.I)
SIZE_FULL_RE = re.compile(r"^(\d{1,3}(?:[.,]\d+)?)\s*ml$", re.I)

NON_FRAGRANCE_TOKENS = {
    tuple(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())
    for value in NON_FRAGRANCE
}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _tokens(value):
    return [token for token in _norm(value).split() if len(token) > 1]


def _matches(text, query):
    text_tokens = set(_tokens(text))
    query_tokens = _tokens(query)
    return bool(query_tokens) and all(token in text_tokens for token in query_tokens)


def _matches_soft(text, query, minimum=0.70):
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
    found = sum(token in text_set for token in set(query_tokens))

    if found == 0:
        return -9999

    missing = len(set(query_tokens)) - found
    extras = [token for token in text_tokens if token not in query_tokens]

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

    value = match.group("before") or match.group("after")
    value = value.replace(".", ",")

    if "," not in value:
        value += ",00"

    return f"{value} €"


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


def _is_relevant_product(name, query):
    if not _matches_soft(name, query, minimum=0.70):
        return False

    if not _query_wants_non_fragrance(query):
        if _contains_non_fragrance_product(name):
            return False

    return True


def _find_brand_category(session, query):
    """
    Trova il link della categoria Deloox più specifico
    compatibile con il brand indicato nella query.
    """
    response = _get(session, HOME_URL)

    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    query_words = set(_tokens(query))
    candidates = []

    for link in soup.find_all("a", href=True):
        name = _clean(link.get_text(" ", strip=True))
        href = _clean(link.get("href"))

        if not name or not href:
            continue

        url = urljoin(BASE_URL, href)

        if "/category/" not in url.lower():
            continue

        brand_words = _tokens(name)

        if not brand_words:
            continue

        if all(word in query_words for word in brand_words):
            candidates.append((len(brand_words), len(name), url))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0], -item[1]))

    return candidates[0][2]


def _find_product_card(link):
    """
    Risale dai link al contenitore della card prodotto.
    Questo permette di cercare brand, nome, formato e prezzo
    nell'intero blocco invece che soltanto nel testo del link.
    """
    node = link

    for _ in range(8):
        if node is None:
            break

        text = _clean(node.get_text(" ", strip=True))

        if _extract_price(text) or SIZE_RE.search(text):
            return node

        node = node.parent

    return link


def _extract_category(html, query):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    query_tokens = set(_tokens(query))

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        product_url = urljoin(BASE_URL, href).split("?")[0]

        if "/product/" not in product_url.lower():
            continue

        card = _find_product_card(link)
        card_text = _clean(card.get_text(" ", strip=True))

        if any(word in card_text.lower() for word in SOLD_OUT):
            continue

        card_tokens = set(_tokens(card_text))

        if query_tokens and not query_tokens.issubset(card_tokens):
            if not _matches_soft(card_text, query, minimum=0.70):
                continue

        if not _is_relevant_product(card_text, query):
            continue

        price = _extract_price(card_text)

        if not price:
            continue

        product_name = _clean(link.get_text(" ", strip=True)) or query

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

            text = _clean(node.get_text(" ", strip=True))

            if _matches_soft(text, query, minimum=0.70):
                price = _extract_price(text)

                if price and not any(
                    word in text.lower() for word in SOLD_OUT
                ):
                    product_link = None
                    product_name = ""

                    for anchor in node.find_all("a", href=True):
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

                    if product_link and _is_relevant_product(text, query):
                        if not product_name:
                            product_name = query

                        if product_link not in seen:
                            seen.add(product_link)

                            results.append({
                                "store": STORE,
                                "name": product_name,
                                "price": price,
                                "url": product_link,
                                "available": True,
                                "availability": "in_stock",
                            })

                break

            node = node.parent

    return results


def _extract_product_variants(html, product_name, product_url):
    """
    Estrae le coppie formato/prezzo dalla pagina del prodotto.
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
        size_match = SIZE_FULL_RE.fullmatch(value)

        if not size_match:
            continue

        size = size_match.group(1).replace(",", ".")
        size_label = f"{size} ml"

        if size_label in seen_sizes:
            continue

        chunk = []
        sold_out = False

        for next_index in range(
            index + 1,
            min(index + 25, len(strings)),
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

        price = _extract_price(" ".join(chunk))

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


def _extract_jsonld_variants(html, product_name, product_url):
    """
    Fallback per prezzi e formati presenti nei blocchi JSON-LD.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        try:
            data = json.loads(
                script.string or script.get_text()
            )

        except (json.JSONDecodeError, TypeError):
            continue

        objects = data if isinstance(data, list) else [data]

        for item in objects:
            if not isinstance(item, dict):
                continue

            offers = item.get("offers", [])

            if isinstance(offers, dict):
                offers = [offers]

            item_text = " ".join([
                str(item.get("name", "")),
                str(item.get("description", "")),
            ])

            size_match = SIZE_RE.search(item_text)

            if not size_match:
                continue

            size = size_match.group(1).replace(",", ".")

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                price = offer.get("price")
                currency = str(
                    offer.get("priceCurrency", "EUR")
                )

                availability = str(
                    offer.get("availability", "")
                ).lower()

                if price is None or currency != "EUR":
                    continue

                if any(
                    word in availability
                    for word in ("outofstock", "soldout")
                ):
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

    brand_url = _find_brand_category(session, query)

    if not brand_url:
        return []

    response = _get(session, brand_url)

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

    candidates = []
    seen_urls = set()

    for item in category_results:
        name = item.get("name", "")
        url = item.get("url", "").split("#")[0].split("?")[0]

        if not url or url in seen_urls:
            continue

        if not _is_relevant_product(name, query):
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
    minimum_score = best_score - 20

    final_results = []
    seen_variants = set()

    for score, item in candidates:
        if score < minimum_score:
            break

        clean_url = item["url"].split("#")[0].split("?")[0]
        product_response = _get(session, clean_url)

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
                _norm(variant.get("size", "")),
                variant["price"],
            )

            if key in seen_variants:
                continue

            seen_variants.add(key)
            final_results.append(variant)

    if final_results:
        final_results.sort(key=_size_number)
        return final_results[:20]

    return [candidates[0][1]]


if __name__ == "__main__":
    queries = (
        "French Avenue Liquid Brun",
        "Miu Miu Miutine",
        "Rasasi Hawas Ice",
    )

    for query in queries:
        print(query, search(query))
