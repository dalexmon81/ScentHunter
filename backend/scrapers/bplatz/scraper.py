import json
import re
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://bplatz.de"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1",
    "Accept": "application/json,text/html,application/xhtml+xml",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
TIMEOUT = 20


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def query_matches(name, query):
    ignored = {"eau","de","parfum","perfume","edp","edt","extrait","spray","ml","for","by"}
    q = [t for t in norm(query).split() if t not in ignored]
    n = norm(name)
    return bool(q) and all(t in n for t in q)


def money(value):
    if value in (None, ""):
        return ""
    try:
        # Shopify JSON endpoints return price as decimal strings.
        return f"{float(str(value).replace(',', '.')):.2f}".replace(".", ",") + " €"
    except (ValueError, TypeError):
        return ""


def predictive_products(session, query):
    """Get canonical Shopify products. This endpoint already returns title,
    URL, price and availability data, avoiding fragile HTML price scraping."""
    endpoint = BASE + "/search/suggest.json"
    params = {
        "q": query,
        "resources[type]": "product",
        "resources[limit]": "10",
        "resources[options][unavailable_products]": "show",
    }
    try:
        r = session.get(endpoint, params=params, headers=HEADERS, timeout=TIMEOUT)
        if not r.ok:
            return []
        data = r.json()
        return (((data or {}).get("resources") or {}).get("results") or {}).get("products") or []
    except (requests.RequestException, ValueError, TypeError):
        return []


def product_json(session, url):
    """Shopify's canonical product .js endpoint is the cleanest source for
    variants, cents prices and availability."""
    clean = url.split("?")[0].rstrip("/")
    js_url = clean + ".js"
    try:
        r = session.get(js_url, headers=HEADERS, timeout=TIMEOUT)
        if not r.ok:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def product_from_json(data, url):
    if not isinstance(data, dict):
        return None
    title = data.get("title") or ""
    variants = data.get("variants") or []

    available = [v for v in variants if v.get("available") is True]
    is_available = any(v.get("available") is True for v in variants) if variants else False
    pool = available or variants

    prices = []
    for v in pool:
        p = v.get("price")
        if p is None:
            continue
        try:
            p = float(p)
            if p >= 100:
                p /= 100
            prices.append(p)
        except (ValueError, TypeError):
            pass

    price = ""
    if prices:
        price = f"{min(prices):.2f}".replace(".", ",") + " €"

    return {
        "store": "Bplatz",
        "name": title,
        "price": price,
        "url": url,
        "available": is_available,
    }


def search_html_urls(session, query):
    """Fallback to Bplatz's normal Shopify search when predictive search
    does not expose a matching product. This is generic and is not tied to
    any perfume name.
    """
    url = BASE + "/search?q=" + quote_plus(query) + "&type=product"
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        if not r.ok:
            return []
    except requests.RequestException:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    urls = []
    seen = set()

    for a in soup.select('a[href*="/products/"]'):
        href = a.get("href") or ""
        absolute = urljoin(BASE, href).split("?")[0]
        path = urlparse(absolute).path.rstrip("/")
        if not path or path in seen:
            continue

        title = (
            a.get("title")
            or a.get("aria-label")
            or a.get_text(" ", strip=True)
            or ""
        )

        if not query_matches(title, query):
            card = a
            for _ in range(5):
                if not card.parent:
                    break
                card = card.parent
                candidate = card.get_text(" ", strip=True)
                if query_matches(candidate, query):
                    title = candidate
                    break

        if not query_matches(title, query):
            continue

        seen.add(path)
        urls.append(absolute)

    return urls


def candidate_urls(session, query):
    """
    Ricerca generica multi-passaggio.

    Non conosce nomi di profumi o varianti specifiche.
    """
    searches = [query]

    normalized = norm(query)
    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )

    if compact and compact != normalized:
        searches.append(compact)

    tokens = [
        token
        for token in normalized.split()
        if token not in {
            "eau", "de", "parfum", "perfume",
            "edp", "edt", "extrait", "spray",
            "ml", "for", "by",
        }
    ]

    for token in tokens:
        if len(token) >= 3 and token not in searches:
            searches.append(token)

    urls = []
    seen = set()

    for search_query in searches:
        for product in predictive_products(
            session,
            search_query,
        ):
            if not isinstance(product, dict):
                continue

            product_url = product.get("url")

            if not product_url:
                continue

            absolute = (
                urljoin(BASE, product_url)
                .split("?")[0]
            )

            path = urlparse(
                absolute
            ).path.rstrip("/")

            if (
                "/products/" not in path
                or path in seen
            ):
                continue

            seen.add(path)
            urls.append(absolute)

    # Importante:
    # il fallback HTML viene eseguito per TUTTE le query
    # alternative, non soltanto per la query originale.
    for search_query in searches:
        for absolute in search_html_urls(
            session,
            search_query,
        ):
            path = urlparse(
                absolute
            ).path.rstrip("/")

            if (
                "/products/" not in path
                or path in seen
            ):
                continue

            seen.add(path)
            urls.append(absolute)

    return urls


def search(query):
    query = str(query or "").strip()

    if not query:
        return []

    session = requests.Session()

    results = []
    seen = set()

    urls = candidate_urls(
        session,
        query,
    )

    for url in urls:
        data = product_json(
            session,
            url,
        )

        item = product_from_json(
            data,
            url,
        )

        if not item:
            continue

        # Il controllo definitivo viene sempre fatto
        # sul titolo canonico restituito da Shopify.
        if not query_matches(
            item["name"],
            query,
        ):
            continue

        key = urlparse(
            item["url"]
        ).path.rstrip("/")

        if key in seen:
            continue

        seen.add(key)
        results.append(item)

    return results


if __name__ == "__main__":
    for q in (
        "9 PM",
        "Rayhaan Aquatica",
        "Turathi Blue",
    ):
        print("\\nQUERY:", q)

        for x in search(q):
            print(x)
