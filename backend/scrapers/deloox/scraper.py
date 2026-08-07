import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

SOLD_OUT = (
    "sold out",
    "out of stock",
    "not available",
    "currently unavailable",
)

SIZE_RE = re.compile(
    r"(\d{1,3}(?:[.,]\d+)?)\s*ml",
    re.I,
)

SIZE_FULL_RE = re.compile(
    r"^(\d{1,3}(?:[.,]\d+)?)\s*ml$",
    re.I,
)

PRICE_RE = re.compile(
    r"""
    (?:
        €\s*
        (?P<int1>\d{1,4})
        \s*(?:[,.\^]\s*)+
        (?P<dec1>\d{2})
        \s*\^*

        |

        (?P<int2>\d{1,4})
        \s*(?:[,.\^]\s*)+
        (?P<dec2>\d{2})
        \s*\^*\s*€

        |

        €\s*(?P<int3>\d{1,4})(?![\d.,])

        |

        (?P<int4>\d{1,4})\s*€
    )
    """,
    re.I | re.X,
)


DIRECT_PRODUCTS = (
    (
        ("le", "beau", "le", "parfum"),
        (
            "https://www.deloox.com/product/"
            "1241200/jean-paul-gaultier-le-beau-le-parfum-"
            "eau-de-parfum-intense-75-ml.html",

            "https://www.deloox.com/product/"
            "1241191/jean-paul-gaultier-le-beau-le-parfum-"
            "eau-de-parfum-intense-125-ml.html",
        ),
    ),
)


CATEGORIES = (
    (
        ("miu", "miu"),
        "https://www.deloox.com/category/"
        "1071574/miu-miu-fragrances.html",
    ),
    (
        ("jean", "paul", "gaultier"),
        "https://www.deloox.com/category/"
        "1072906/jean-paul-gaultier-fragrances.html",
    ),
)


def clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def norm(value):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        clean(value).lower(),
    ).strip()


def tokens(value):
    return {
        token
        for token in norm(value).split()
        if len(token) > 1
    }


def extract_price(text):
    match = PRICE_RE.search(clean(text))

    if not match:
        return None

    integer = (
        match.group("int1")
        or match.group("int2")
        or match.group("int3")
        or match.group("int4")
    )

    cents = (
        match.group("dec1")
        or match.group("dec2")
    )

    if cents:
        return f"{integer},{cents} €"

    return f"{integer},00 €"


def get(session, url):
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


def size_value(value):
    match = SIZE_RE.search(value or "")

    if not match:
        return 9999

    try:
        return float(
            match.group(1).replace(",", ".")
        )

    except ValueError:
        return 9999


def extract_price_near_size(
    soup,
    expected_size,
):
    strings = [
        clean(value)
        for value in soup.stripped_strings
        if clean(value)
    ]

    for index, value in enumerate(strings):
        size_match = SIZE_FULL_RE.fullmatch(value)

        if not size_match:
            continue

        current_size = size_match.group(1).replace(
            ",",
            ".",
        )

        if current_size != expected_size:
            continue

        chunk = []

        for next_index in range(
            index + 1,
            min(index + 25, len(strings)),
        ):
            next_value = strings[next_index]

            if SIZE_FULL_RE.fullmatch(next_value):
                break

            if any(
                word in next_value.lower()
                for word in SOLD_OUT
            ):
                return None

            chunk.append(next_value)

        price = extract_price(
            " ".join(chunk)
        )

        if price:
            return price

    return None


def search_direct(session, query, urls):
    results = []
    seen = set()

    for url in urls:
        response = get(session, url)

        if response is None:
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        page_text = clean(
            soup.get_text(
                " ",
                strip=True,
            )
        )

        if any(
            word in page_text.lower()
            for word in SOLD_OUT
        ):
            continue

        size_match = SIZE_RE.search(url)

        if not size_match:
            continue

        size = size_match.group(1).replace(
            ",",
            ".",
        )

        size_label = f"{size} ml"

        price = extract_price_near_size(
            soup,
            size,
        )

        if not price:
            price = extract_price(page_text)

        if not price:
            continue

        key = (
            url,
            size_label,
            price,
        )

        if key in seen:
            continue

        seen.add(key)

        results.append({
            "store": STORE,
            "name": f"{query} {size_label}",
            "price": price,
            "url": f"{url}#{size.replace('.', '-')}-ml",
            "available": True,
            "availability": "in_stock",
            "size": size_label,
        })

    results.sort(
        key=lambda item: size_value(
            item.get("size", "")
        )
    )

    return results


def find_category(session, query):
    query_tokens = tokens(query)

    for required, url in CATEGORIES:
        if set(required).issubset(query_tokens):
            return url

    response = get(
        session,
        BASE_URL + "/en",
    )

    if response is None:
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    best_url = None
    best_score = 0

    for link in soup.find_all(
        "a",
        href=True,
    ):
        name = clean(
            link.get_text(
                " ",
                strip=True,
            )
        )

        href = clean(
            link.get("href")
        )

        url = urljoin(
            BASE_URL,
            href,
        )

        if "/category/" not in url.lower():
            continue

        score = len(
            tokens(name) & query_tokens
        )

        if score > best_score:
            best_score = score
            best_url = url

    return best_url


def search_category(session, query, category_url):
    response = get(
        session,
        category_url,
    )

    if response is None:
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    query_tokens = tokens(query)
    results = []
    seen = set()

    for link in soup.find_all(
        "a",
        href=True,
    ):
        url = urljoin(
            BASE_URL,
            clean(link.get("href")),
        ).split("?")[0]

        if "/product/" not in url.lower():
            continue

        # Il nome richiesto deve comparire nello slug.
        if not query_tokens.issubset(tokens(url)):
            continue

        card = link
        text = ""

        for _ in range(8):
            if card is None:
                break

            text = clean(
                card.get_text(
                    " ",
                    strip=True,
                )
            )

            if extract_price(text):
                break

            card = card.parent

        if not text:
            continue

        if any(
            word in text.lower()
            for word in SOLD_OUT
        ):
            continue

        price = extract_price(text)

        if not price or url in seen:
            continue

        seen.add(url)

        results.append({
            "store": STORE,
            "name": query,
            "price": price,
            "url": url,
            "available": True,
            "availability": "in_stock",
        })

    return results


def search(query):
    query = clean(query)

    if not query:
        return []

    session = requests.Session()
    query_tokens = tokens(query)

    # Questo return è intenzionalmente immediato.
    # Se la query è Le Beau Le Parfum,
    # non deve mai passare alla categoria generale Le Beau.
    for required, urls in DIRECT_PRODUCTS:
        if set(required).issubset(query_tokens):
            return search_direct(
                session,
                query,
                urls,
            )

    category_url = find_category(
        session,
        query,
    )

    if not category_url:
        return []

    return search_category(
        session,
        query,
        category_url,
    )


if __name__ == "__main__":
    tests = (
        "Le Beau Le Parfum",
        "Miu Miu Miutine",
        "Jean Paul Gaultier Le Beau Le Parfum",
    )

    for query in tests:
        print("\nQUERY:", query)

        results = search(query)

        if not results:
            print("NESSUN RISULTATO")
        else:
            for result in results:
                print(result)
