from __future__ import annotations

import json
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,es-ES;q=0.8,en;q=0.7",
    "Accept": (
        "text/html,application/xhtml+xml,application/json;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
}

PRODUCT_PATH_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl|pt)/[^/]+/(\d+)-[^/]+\.html$",
    re.I,
)
PRICE_RE = re.compile(
    r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*€"
)
IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "for", "by", "ml", "pour",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = clean(value).lower()
    value = re.sub(r"[^a-z0-9à-ÿ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def query_tokens(query):
    return [
        token
        for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS
    ]


def query_matches(text, query):
    normalized = norm(text)
    tokens = query_tokens(query)
    return bool(tokens) and all(token in normalized for token in tokens)


def normalise_url(url, base_url=BASE_URL):
    if not url:
        return None

    absolute = urljoin(base_url, clean(url))
    parsed = urlparse(absolute)

    if parsed.scheme not in {"http", "https"}:
        return None

    if parsed.netloc.lower() not in {
        "sabina.com",
        "www.sabina.com",
    }:
        return None

    return (
        f"{parsed.scheme}://{parsed.netloc}"
        f"{parsed.path.rstrip('/')}"
    )


def is_product_url(url):
    if not url:
        return False
    return bool(
        PRODUCT_PATH_RE.match(urlparse(url).path)
    )


def extract_price(text):
    matches = list(
        PRICE_RE.finditer(clean(text))
    )
    if not matches:
        return ""
    return matches[-1].group(1).replace(".", ",") + " €"


def _search_urls(query):
    q = quote_plus(query)
    return [
        f"{BASE_URL}/it/ricerca?search_query={q}",
        f"{BASE_URL}/it/ricerca_old?s={q}",
        f"{BASE_URL}/it/ricerca_old?search_query={q}",
        f"{BASE_URL}/es/buscar?search_query={q}",
        f"{BASE_URL}/fr/recherche?search_query={q}",
    ]


def _name_from_card(anchor, container, query):
    candidates = [
        anchor.get("title"),
        anchor.get("aria-label"),
        anchor.get_text(" ", strip=True),
    ]

    for selector in (
        "h1", "h2", "h3", "h4",
        ".name", ".product-name", ".product-title",
    ):
        for element in container.select(selector):
            candidates.append(
                element.get_text(" ", strip=True)
            )

    cleaned = [
        clean(PRICE_RE.sub(" ", str(value)))
        for value in candidates
        if clean(value)
    ]

    # Prefer the actual link/title/heading text. Do not select the
    # longest parent-card text, which can contain neighbouring products.
    for value in cleaned:
        if (
            query_matches(value, query)
            and len(value) <= 250
            and value.lower() not in {"vedi", "vedi tutto", "acquista", "immagine"}
        ):
            return value

    return ""


def _parse_html(html, query):
    soup = BeautifulSoup(
        html or "",
        "html.parser",
    )
    rows = []

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        url = normalise_url(
            anchor.get("href")
        )

        if not is_product_url(url):
            continue

        container = anchor

        for _ in range(10):
            parent = getattr(
                container,
                "parent",
                None,
            )
            if not parent:
                break

            container = parent
            block = clean(
                container.get_text(
                    " ",
                    strip=True,
                )
            )

            if "€" in block and len(block) < 2200:
                break

        text_block = clean(
            container.get_text(
                " ",
                strip=True,
            )
        )

        price = (
            extract_price(anchor.get_text(" ", strip=True))
            or extract_price(text_block)
        )
        if not price:
            continue

        name = _name_from_card(
            anchor,
            container,
            query,
        )

        if not name:
            continue

        rows.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": url,
        })

    return rows


def _parse_json(value, query):
    rows = []

    def walk(obj):
        if isinstance(obj, dict):
            lowered = {
                str(k).lower(): v
                for k, v in obj.items()
            }

            name = next(
                (
                    lowered[key]
                    for key in (
                        "name",
                        "product_name",
                        "productname",
                        "title",
                        "label",
                    )
                    if key in lowered
                    and isinstance(
                        lowered[key],
                        (str, int, float),
                    )
                ),
                None,
            )

            url = next(
                (
                    lowered[key]
                    for key in (
                        "url",
                        "link",
                        "product_url",
                        "producturl",
                        "href",
                    )
                    if key in lowered
                    and isinstance(
                        lowered[key],
                        str,
                    )
                ),
                None,
            )

            price = next(
                (
                    lowered[key]
                    for key in (
                        "price",
                        "final_price",
                        "finalprice",
                        "sale_price",
                        "saleprice",
                        "price_amount",
                        "priceamount",
                    )
                    if key in lowered
                ),
                None,
            )

            url = normalise_url(url)

            if (
                name
                and url
                and is_product_url(url)
                and query_matches(name, query)
            ):
                price_text = extract_price(
                    str(price or "")
                )
                if price_text:
                    rows.append({
                        "store": STORE,
                        "name": clean(name),
                        "price": price_text,
                        "url": url,
                    })

            for child in obj.values():
                walk(child)

        elif isinstance(obj, list):
            for child in obj:
                walk(child)

    walk(value)
    return rows


def _dedupe(rows, query):
    output = []
    seen = set()

    for row in rows:
        name = clean(row.get("name"))
        url = normalise_url(row.get("url"))
        price = extract_price(row.get("price"))

        if not name or not url or not price:
            continue

        if not query_matches(name, query):
            continue

        key = (
            norm(name),
            url,
        )

        if key in seen:
            continue

        seen.add(key)

        output.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": url,
        })

    return output


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    results = []

    try:
        # Try every generic search endpoint instead of stopping after
        # the first partial response.
        for url in _search_urls(query):
            try:
                response = session.get(
                    url,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
                response.raise_for_status()
            except requests.RequestException:
                continue

            text = response.text or ""

            try:
                data = response.json()
            except Exception:
                data = None

            if data is not None:
                results.extend(
                    _parse_json(data, query)
                )

            results.extend(
                _parse_html(text, query)
            )

        return _dedupe(results, query)

    finally:
        session.close()


def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
