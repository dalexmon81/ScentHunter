import re
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value):
    return re.findall(r"[a-z0-9]+", _clean(value).lower())


def _matches(name, query):
    name_tokens = _tokens(name)
    query_tokens = _tokens(query)

    if not query_tokens:
        return False

    return all(token in name_tokens for token in query_tokens)


def _price(text):
    text = _clean(text)

    patterns = [
        r"€\s*(\d{1,4})\s*,\s*(\d{2})",
        r"€\s*(\d{1,4})\s*,\s*(\d{1,2})",
        r"(\d{1,4})\s*,\s*(\d{2})\s*€",
        r"(\d{1,4})[.](\d{2})\s*€",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            cents = match.group(2).ljust(2, "0")
            return f"{match.group(1)},{cents}€"

    return None


def _extract_category(soup, query):
    results = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = _clean(a.get("href"))

        if not href:
            continue

        product_url = urljoin(BASE_URL, href)

        container = a

        for _ in range(8):
            if container.parent:
                container = container.parent

            text = _clean(container.get_text(" ", strip=True))

            if (
                _matches(text, query)
                and _price(text)
            ):
                break

        text = _clean(container.get_text(" ", strip=True))

        if not _matches(text, query):
            continue

        price = _price(text)

        if not price:
            continue

        # Cerca un nome leggibile
        name = ""

        selectors = [
            "h1",
            "h2",
            "h3",
            "h4",
            "[class*='product-name']",
            "[class*='product-title']",
            "[class*='title']",
            "[itemprop='name']",
        ]

        for selector in selectors:
            element = container.select_one(selector)

            if element:
                candidate = _clean(
                    element.get_text(" ", strip=True)
                )

                if _matches(candidate, query):
                    name = candidate
                    break

        if not name:
            name = query

        # Cerchiamo il link prodotto reale dentro la card
        product_link = None

        for pa in container.find_all("a", href=True):
            phref = _clean(pa.get("href"))

            if not phref:
                continue

            low = phref.lower()

            if (
                "/product/" in low
                or ".html" in low
            ):
                product_link = urljoin(BASE_URL, phref)
                break

        if product_link:
            product_url = product_link

        key = product_url.split("?")[0]

        if key in seen:
            continue

        seen.add(key)

        results.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": key,
            "available": True,
            "availability": "in_stock",
        })

    return results


def _extract_product_page(soup, url, query):
    text = _clean(soup.get_text(" ", strip=True))

    if not _matches(text, query):
        return []

    name = query

    h1 = soup.find("h1")

    if h1:
        h1_text = _clean(h1.get_text(" ", strip=True))

        if h1_text:
            name = h1_text

    # Se H1 è solo "Hawas Ice", aggiungiamo eventuale brand
    brand = ""

    brand_selectors = [
        "[class*='brand']",
        "[itemprop='brand']",
    ]

    for selector in brand_selectors:
        element = soup.select_one(selector)

        if element:
            brand = _clean(
                element.get_text(" ", strip=True)
            )

            if brand:
                break

    if brand and brand.lower() not in name.lower():
        name = f"{brand} {name}"

    price = _price(text)

    sold_out_words = [
        "sold out",
        "out of stock",
        "temporarily unavailable",
        "not available",
    ]

    sold_out = any(
        word in text.lower()
        for word in sold_out_words
    )

    if not price and not sold_out:
        return []

    return [{
        "store": STORE,
        "name": name,
        "price": price,
        "url": url.split("?")[0],
        "available": not sold_out,
        "availability": (
            "out_of_stock"
            if sold_out
            else "in_stock"
        ),
    }]


def search(query):
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    #
    # 1. Ricerca interna Deloox
    #
    search_urls = [
        f"{BASE_URL}/search?q={quote_plus(query)}",
        f"{BASE_URL}/search?query={quote_plus(query)}",
        f"{BASE_URL}/search/?q={quote_plus(query)}",
    ]

    for search_url in search_urls:
        try:
            response = session.get(
                search_url,
                timeout=8,
                allow_redirects=True,
            )

            if response.status_code != 200:
                continue

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            # Se Deloox redirige direttamente
            # alla pagina categoria/prodotto
            current_url = response.url

            if (
                "/category/" in current_url.lower()
                or "/product/" in current_url.lower()
            ):
                results = _extract_product_page(
                    soup,
                    current_url,
                    query,
                )

                if results:
                    return results

            results = _extract_category(
                soup,
                query
            )

            if results:
                return results

        except requests.RequestException:
            continue

    #
    # 2. Cerca dalla home i link categoria
    #
    try:
        response = session.get(
            BASE_URL,
            timeout=8,
            allow_redirects=True,
        )

        if response.status_code == 200:
            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            candidates = []

            for a in soup.find_all(
                "a",
                href=True
            ):
                text = _clean(
                    a.get_text(" ", strip=True)
                )

                href = _clean(
                    a.get("href")
                )

                if not href:
                    continue

                if _matches(text, query):
                    candidate = urljoin(
                        BASE_URL,
                        href
                    )

                    if candidate not in candidates:
                        candidates.append(candidate)

            for candidate in candidates[:10]:
                try:
                    response = session.get(
                        candidate,
                        timeout=8,
                        allow_redirects=True,
                    )

                    if response.status_code != 200:
                        continue

                    soup = BeautifulSoup(
                        response.text,
                        "html.parser"
                    )

                    results = _extract_category(
                        soup,
                        query
                    )

                    if results:
                        return results

                    results = _extract_product_page(
                        soup,
                        response.url,
                        query,
                    )

                    if results:
                        return results

                except requests.RequestException:
                    continue

    except requests.RequestException:
        pass

    #
    # 3. Fallback diretto conosciuto
    # Hawas Ice
    #
    normalized = " ".join(_tokens(query))

    known_categories = {
        "hawas ice":
            "https://www.deloox.com/category/1111563/hawas-ice.html",
        "rasasi hawas ice":
            "https://www.deloox.com/category/1111563/hawas-ice.html",
    }

    direct_url = known_categories.get(normalized)

    if direct_url:
        try:
            response = session.get(
                direct_url,
                timeout=8,
                allow_redirects=True,
            )

            if response.status_code == 200:
                soup = BeautifulSoup(
                    response.text,
                    "html.parser"
                )

                results = _extract_category(
                    soup,
                    query
                )

                if results:
                    return results

                results = _extract_product_page(
                    soup,
                    response.url,
                    query,
                )

                if results:
                    return results

        except requests.RequestException:
            pass

    return []


if __name__ == "__main__":
    print(search("Hawas Ice"))
