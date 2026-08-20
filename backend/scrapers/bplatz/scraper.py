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

NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "discovery set", "fragrance set", "perfume set",
    "parfum set", "coffret", "bundle", "pack", "travel set", "kit", "duo",
    "trio", "mystery box", "tester", "testeur", "sample", "shampoo",
    "shower gel", "body lotion", "body cream", "deodorant", "deo spray",
    "aftershave", "after shave", "makeup", "skin care", "skincare", "cosmetics",
    "cosmetici", "set",
}


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def contains_non_perfume_marker(name):
    text = norm(name)
    tokens = set(text.split())
    for marker in NON_PERFUME_MARKERS:
        marker_tokens = set(norm(marker).split())
        if marker_tokens and marker_tokens.issubset(tokens):
            return True
    return False


def query_matches(name, query):
    if contains_non_perfume_marker(name):
        return False
    ignored = {"eau", "de", "parfum", "perfume", "edp", "edt", "extrait", "spray", "ml", "for", "by"}
    query_tokens = [token for token in norm(query).split() if token not in ignored]
    name_tokens = set(norm(name).split())
    return bool(query_tokens) and all(token in name_tokens for token in query_tokens)


def money(value):
    if value in (None, ""):
        return ""
    try:
        return f"{float(str(value).replace(',', '.')):.2f}".replace(".", ",") + " €"
    except (ValueError, TypeError):
        return ""


def predictive_products(session, query):
    endpoint = BASE + "/search/suggest.json"
    params = {
        "q": query,
        "resources[type]": "product",
        "resources[limit]": "10",
        "resources[options][unavailable_products]": "show",
    }
    try:
        response = session.get(endpoint, params=params, headers=HEADERS, timeout=TIMEOUT)
        if not response.ok:
            return []
        data = response.json()
        return (((data or {}).get("resources") or {}).get("results") or {}).get("products") or []
    except (requests.RequestException, ValueError, TypeError):
        return []


def product_json(session, url):
    clean = url.split("?")[0].rstrip("/")
    try:
        response = session.get(clean + ".js", headers=HEADERS, timeout=TIMEOUT)
        if not response.ok:
            return None
        return response.json()
    except (requests.RequestException, ValueError):
        return None


def product_from_json(data, url):
    if not isinstance(data, dict):
        return None
    title = data.get("title") or ""
    if contains_non_perfume_marker(title):
        return None

    variants = data.get("variants") or []
    available = [variant for variant in variants if variant.get("available") is True]
    is_available = bool(available)
    prices = []
    for variant in available:
        price = variant.get("price")
        try:
            price = float(price)
            if price >= 100:
                price /= 100
            prices.append(price)
        except (ValueError, TypeError):
            continue

    return {
        "store": "Bplatz",
        "name": title,
        "price": f"{min(prices):.2f}".replace(".", ",") + " €" if is_available and prices else "",
        "url": url,
        "available": is_available,
    }


def search_html_urls(session, query):
    url = BASE + "/search?q=" + quote_plus(query) + "&type=product"
    try:
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        if not response.ok:
            return []
    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    urls = []
    seen = set()
    for anchor in soup.select('a[href*="/products/"]'):
        href = anchor.get("href") or ""
        absolute = urljoin(BASE, href).split("?")[0]
        path = urlparse(absolute).path.rstrip("/")
        if not path or path in seen:
            continue

        title = anchor.get("title") or anchor.get("aria-label") or anchor.get_text(" ", strip=True) or ""
        if not query_matches(title, query):
            card = anchor
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
    searches = [query]
    compact = re.sub(r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)", "", norm(query))
    if compact and compact != norm(query):
        searches.append(compact)

    # Token discovery is retained for numeric/compound product searches,
    # but every token result is title-filtered before it can be returned.
    for token in norm(query).split():
        if len(token) >= 3 and token not in searches:
            searches.append(token)

    urls = []
    seen = set()
    for search_query in searches:
        for product in predictive_products(session, search_query):
            product_title = product.get("title") or product.get("name") or ""
            if not query_matches(product_title, query):
                continue
            product_url = product.get("url")
            if not product_url:
                continue
            absolute = urljoin(BASE, product_url).split("?")[0]
            path = urlparse(absolute).path.rstrip("/")
            if "/products/" not in path or path in seen:
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
    urls = candidate_urls(session, query)
    for url in search_html_urls(session, query):
        if url not in urls:
            urls.append(url)

    for url in urls:
        item = product_from_json(product_json(session, url), url)
        if not item or not query_matches(item["name"], query):
            continue
        key = urlparse(item["url"]).path.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
    return results


if __name__ == "__main__":
    for query in ("9 PM", "Rayhaan Aquatica", "Turathi Blue"):
        print("\nQUERY:", query)
        for result in search(query):
            print(result)
