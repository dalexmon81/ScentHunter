from __future__ import annotations

import html
import json
import re
import unicodedata
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin

import requests

STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}


def _clean(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        html.unescape(str(value or "")),
    ).strip()


def _norm(value: Any) -> str:
    value = unicodedata.normalize("NFKD", _clean(value).lower())
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(query: str) -> List[str]:
    return [x for x in _norm(query).split() if len(x) > 1]


def _matches(text: str, query: str) -> bool:
    normalized = _norm(text)
    tokens = _tokens(query)
    return bool(tokens) and all(token in normalized for token in tokens)


def _price(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Shopify product JSON commonly exposes cents as integer values.
        if float(value) >= 100:
            return round(float(value) / 100.0, 2)
        return round(float(value), 2)

    match = re.search(
        r"(\d+(?:[.,]\d{1,2})?)",
        _clean(value).replace("€", ""),
    )
    if not match:
        return None

    try:
        amount = float(match.group(1).replace(",", "."))
    except ValueError:
        return None

    return round(amount, 2) if amount > 0 else None


def _format_price(value: Any) -> str:
    amount = _price(value)
    return (
        f"{amount:.2f}".replace(".", ",") + " €"
        if amount is not None
        else ""
    )


def _product_url(value: Any) -> str:
    url = urljoin(BASE_URL, _clean(value))
    return url.split("?")[0].rstrip("/")


def _availability(value: Any) -> str:
    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"

    text = _norm(value)
    if any(
        marker in text
        for marker in (
            "out of stock",
            "sold out",
            "unavailable",
            "ausverkauft",
            "nicht auf lager",
            "rupture de stock",
        )
    ):
        return "out_of_stock"

    if any(
        marker in text
        for marker in (
            "in stock",
            "available",
            "disponible",
            "auf lager",
        )
    ):
        return "in_stock"

    return "unknown"


def _request_json(
    session: requests.Session,
    url: str,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if not response.ok:
            return None
        return response.json()
    except (
        requests.RequestException,
        ValueError,
        TypeError,
    ):
        return None


def _product_json(
    session: requests.Session,
    url: str,
) -> Optional[Dict[str, Any]]:
    clean_url = _product_url(url)
    data = _request_json(
        session,
        clean_url + ".js",
    )
    return data if isinstance(data, dict) else None


def _discovery_queries(query: str) -> List[str]:
    tokens = _tokens(query)
    queries: List[str] = []
    seen = set()

    def add(value: str):
        value = _clean(value)
        key = _norm(value)
        if key and key not in seen:
            seen.add(key)
            queries.append(value)

    add(query)
    if len(tokens) > 1:
        add(" ".join(reversed(tokens)))
        for token in tokens:
            if len(token) >= 3:
                add(token)

    return queries[:6]


def _collect_urls_from_suggest(
    session: requests.Session,
    query: str,
) -> List[str]:
    data = _request_json(
        session,
        BASE_URL + "/search/suggest.json",
        params={
            "q": query,
            "resources[type]": "product",
            "resources[limit]": 50,
            "resources[options][unavailable_products]": "show",
        },
    )

    products = (
        ((data or {}).get("resources") or {})
        .get("results", {})
        .get("products", [])
    )

    urls = []
    seen = set()

    for product in products:
        if not isinstance(product, dict):
            continue

        title = _clean(product.get("title"))
        vendor = _clean(product.get("vendor"))
        url = _product_url(product.get("url"))

        if "/products/" not in url:
            continue

        # Discovery is deliberately broad. Final identity validation uses
        # the original user query after the product page is fetched.
        if not _matches(
            f"{title} {vendor} {url}",
            query,
        ):
            continue

        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


def _collect_urls_from_search_json(
    session: requests.Session,
    query: str,
) -> List[str]:
    data = _request_json(
        session,
        BASE_URL + "/search.json",
        params={
            "q": query,
            "type": "product",
            "limit": 50,
        },
    )

    urls = []
    seen = set()

    for product in (data or {}).get("products", []):
        if not isinstance(product, dict):
            continue

        title = _clean(product.get("title"))
        vendor = _clean(product.get("vendor"))
        url = _product_url(product.get("url"))

        if (
            "/products/" in url
            and _matches(f"{title} {vendor} {url}", query)
            and url not in seen
        ):
            seen.add(url)
            urls.append(url)

    return urls


def _collect_urls_from_html(
    session: requests.Session,
    query: str,
) -> List[str]:
    try:
        response = session.get(
            BASE_URL + "/search",
            params={"q": query, "type": "product"},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if not response.ok:
            return []
    except requests.RequestException:
        return []

    # Avoid a hard BeautifulSoup dependency for the URL discovery fallback.
    urls = []
    seen = set()

    for match in re.finditer(
        r'href=["\']([^"\']*/products/[^"\']+)["\']',
        response.text or "",
        re.I,
    ):
        url = _product_url(match.group(1))
        if "/products/" not in url or url in seen:
            continue

        context = _clean(
            (response.text or "")[
                max(0, match.start() - 300):
                match.end() + 300
            ]
        )
        if not _matches(context, query):
            continue

        seen.add(url)
        urls.append(url)

    return urls


def _discover(
    session: requests.Session,
    query: str,
) -> List[str]:
    found = []
    seen = set()

    for discovery_query in _discovery_queries(query):
        sources = (
            _collect_urls_from_suggest(
                session,
                discovery_query,
            ),
            _collect_urls_from_search_json(
                session,
                discovery_query,
            ),
            _collect_urls_from_html(
                session,
                discovery_query,
            ),
        )

        for urls in sources:
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    found.append(url)

    return found


def _variant_size(*values) -> Optional[float]:
    text = " ".join(_clean(v) for v in values)
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:ml|cl)\b",
        text,
        re.I,
    )
    if not match:
        return None

    amount = float(match.group(1).replace(",", "."))
    if match.group(0).lower().endswith("cl"):
        amount *= 10
    return int(amount) if amount.is_integer() else amount


def _concentration(*values) -> Optional[str]:
    text = _norm(" ".join(_clean(v) for v in values))
    rules = (
        ("Extrait de Parfum", r"\bextrait(?: de)? parfum\b"),
        ("Eau de Parfum", r"\beau de parfum\b|\bedp\b"),
        ("Eau de Toilette", r"\beau de toilette\b|\bedt\b"),
        ("Eau de Cologne", r"\beau de cologne\b|\bedc\b"),
        ("Parfum", r"\bparfum\b"),
    )
    for label, pattern in rules:
        if re.search(pattern, text, re.I):
            return label
    return None


def _result_from_product(
    product: Dict[str, Any],
    url: str,
    query: str,
) -> List[Dict[str, Any]]:
    title = _clean(product.get("title"))
    vendor = _clean(product.get("vendor"))

    if not _matches(
        f"{title} {vendor} {url}",
        query,
    ):
        return []

    variants = product.get("variants") or []
    if not isinstance(variants, list):
        variants = []

    output = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue

        variant_title = _clean(variant.get("title"))
        source_name = (
            f"{title} {variant_title}".strip()
            if variant_title and variant_title != "Default Title"
            else title
        )

        # Final validation is against the ORIGINAL query, not the broad
        # discovery query.
        if not _matches(
            f"{source_name} {vendor} {url}",
            query,
        ):
            continue

        amount = _price(variant.get("price"))
        if amount is None:
            continue

        available = variant.get("available")
        if available is True:
            stock = "in_stock"
        elif available is False:
            stock = "out_of_stock"
        else:
            stock = "unknown"

        output.append({
            "store": STORE,
            "name": source_name,
            "price": _format_price(amount),
            "url": url,
            "available": available,
            "availability": stock,
            "stock_status": stock,
            "attributes": {
                "size_ml": {
                    "value": _variant_size(
                        variant_title,
                        title,
                    ),
                    "source": "shopify_variant",
                },
                "concentration": {
                    "value": _concentration(
                        variant_title,
                        title,
                    ),
                    "source": "product_text",
                },
            },
        })

    return output


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        urls = _discover(session, query)

        results = []
        seen = set()

        for url in urls:
            product = _product_json(session, url)
            if not product:
                continue

            for row in _result_from_product(
                product,
                url,
                query,
            ):
                key = (
                    row["url"].lower(),
                    _norm(row["name"]),
                )
                if key in seen:
                    continue

                seen.add(key)
                results.append(row)

        return results

    finally:
        session.close()


scrape = search


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
