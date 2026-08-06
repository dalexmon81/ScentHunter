import json
import re
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-GB,en;q=0.9,it;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

PRICE_RE = re.compile(
    r"(?:€\s*\d{1,4}(?:[.,]\d{2})?|\d{1,4}(?:[.,]\d{2})?\s*€)"
)


def _clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _price(text):
    match = PRICE_RE.search(_clean(text))
    if not match:
        return None
    value = match.group(0).replace(" ", "")
    if value.startswith("€"):
        value = value[1:] + "€"
    return value


def _matches(name, query):
    name_words = set(re.findall(r"[a-z0-9]+", name.lower()))
    query_words = re.findall(r"[a-z0-9]+", query.lower())
    important = [w for w in query_words if len(w) > 2]
    return not important or all(w in name_words for w in important)


def _add(results, seen, name, price, url, query):
    name = _clean(name)
    price = _price(price)
    url = _clean(url)

    if not name or not price or not url:
        return
    if not _matches(name, query):
        return

    url = urljoin(BASE_URL, url)
    key = (name.lower(), price, url.split("?")[0])

    if key in seen:
        return

    seen.add(key)
    results.append({
        "store": STORE,
        "name": name,
        "price": price,
        "url": url,
    })


def _parse_jsonld(soup, query, results, seen):
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop()

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            if "@graph" in item:
                stack.append(item["@graph"])

            if "itemListElement" in item:
                stack.append(item["itemListElement"])

            if "item" in item and isinstance(item["item"], (dict, list)):
                stack.append(item["item"])

            typ = item.get("@type")
            if isinstance(typ, list):
                is_product = "Product" in typ
            else:
                is_product = typ == "Product"

            if not is_product:
                continue

            name = item.get("name", "")
            url = item.get("url", "")

            offers = item.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            price = ""
            if isinstance(offers, dict):
                price = offers.get("price", "")
                currency = offers.get("priceCurrency", "EUR")
                if price:
                    price = f"{price}€" if currency == "EUR" else str(price)

            _add(results, seen, name, price, url, query)


def _parse_html(soup, query, results, seen):
    selectors = [
        "[data-product]",
        "[data-product-id]",
        ".product",
        ".product-item",
        ".product-card",
        ".product-tile",
        "article",
        "li",
    ]

    nodes = []
    for selector in selectors:
        found = soup.select(selector)
        if found:
            nodes = found
            break

    for node in nodes:
        text = _clean(node.get_text(" ", strip=True))
        price = _price(text)
        if not price:
            continue

        link = node.find("a", href=True)
        if not link:
            continue

        href = link.get("href", "")
        if not href or href.startswith("#"):
            continue

        title_node = node.select_one(
            "[class*='name'], [class*='title'], h2, h3, h4"
        )
        name = (
            title_node.get_text(" ", strip=True)
            if title_node
            else link.get("title")
            or link.get_text(" ", strip=True)
        )

        _add(results, seen, name, price, href, query)


def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    # Deloox non usa in modo affidabile /search?q=...
    # La ricerca pubblica indicizza invece pagine categoria/prodotto.
    # Proviamo prima il motore interno tramite endpoint/percorsi noti,
    # poi ricaviamo eventuali link prodotto dalla risposta.
    candidates = [
        f"{BASE_URL}/search?search={quote_plus(query)}",
        f"{BASE_URL}/search?q={quote_plus(query)}",
        f"{BASE_URL}/search?query={quote_plus(query)}",
    ]

    results = []
    seen = set()

    for url in candidates:
        try:
            response = session.get(url, timeout=4, allow_redirects=True)
            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, "html.parser")

            # Parser normali
            _parse_jsonld(soup, query, results, seen)
            _parse_html(soup, query, results, seen)

            # Deloox: intercetta direttamente i link /product/<id>/<slug>.html
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if "/product/" not in href or not href.endswith(".html"):
                    continue

                name = _clean(a.get_text(" ", strip=True) or a.get("title", ""))
                if not name or not _matches(name, query):
                    continue

                product_url = urljoin(BASE_URL, href)
                try:
                    pr = session.get(product_url, timeout=4, allow_redirects=True)
                    if pr.status_code != 200:
                        continue
                    psoup = BeautifulSoup(pr.text, "html.parser")

                    # Nome prodotto
                    h1 = psoup.find("h1")
                    pname = _clean(h1.get_text(" ", strip=True)) if h1 else name

                    # Prezzo: Deloox spesso spezza € / interi / centesimi nel DOM.
                    ptext = _clean(psoup.get_text(" ", strip=True))
                    pm = re.search(
                        r"our price:\s*€\s*(\d{1,4})\s*,\s*(\d{2})",
                        ptext,
                        re.IGNORECASE,
                    )
                    if pm:
                        price = f"{pm.group(1)},{pm.group(2)}€"
                        _add(results, seen, pname, price, product_url, query)
                except requests.RequestException:
                    pass

            if results:
                break

        except requests.RequestException:
            continue

    return results


if __name__ == "__main__":
    test_query = "Rasasi Hawas Ice"
    found = search(test_query)

    print(f"RISULTATI: {len(found)}")
    for item in found[:10]:
        print(item)
