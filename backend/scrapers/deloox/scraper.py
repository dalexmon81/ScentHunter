import re
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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

    # Tutte le parole cercate devono comparire nel prodotto.
    return all(token in name_tokens for token in query_tokens)


def _price(text):
    text = _clean(text)

    patterns = [
        r"€\s*(\d{1,4})[.,](\d{2})",
        r"(\d{1,4})[.,](\d{2})\s*€",
        r"€\s*(\d{1,4})\s*[-–]\s*",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            if len(match.groups()) >= 2:
                return f"{match.group(1)},{match.group(2)}€"

            return f"{match.group(1)},00€"

    return None


def _product_name(node):
    selectors = [
        "h1",
        "h2",
        "h3",
        "[class*='product-name']",
        "[class*='product-title']",
        "[class*='title']",
        "[itemprop='name']",
    ]

    for selector in selectors:
        found = node.select_one(selector)

        if found:
            text = _clean(found.get_text(" ", strip=True))
            if text:
                return text

    return ""


def _extract_products(soup, query):
    results = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = _clean(a.get("href"))

        if not href:
            continue

        low = href.lower()

        if (
            "/product/" not in low
            and "/products/" not in low
            and ".html" not in low
        ):
            continue

        product_url = urljoin(BASE_URL, href)

        if product_url in seen:
            continue

        container = a

        for _ in range(6):
            if container.parent:
                container = container.parent

            text = _clean(container.get_text(" ", strip=True))

            if len(text) > 40:
                break

        name = _clean(
            a.get("title")
            or a.get("aria-label")
            or _product_name(container)
            or a.get_text(" ", strip=True)
        )

        if not _matches(name, query):
            continue

        price = _price(container.get_text(" ", strip=True))

        if not price:
            continue

        seen.add(product_url)

        results.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": product_url,
        })

    return results


def search(query):
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    search_urls = [
        f"{BASE_URL}/search?q={quote_plus(query)}",
        f"{BASE_URL}/search?query={quote_plus(query)}",
        f"{BASE_URL}/search/?q={quote_plus(query)}",
    ]

    for url in search_urls:
        try:
            response = session.get(
                url,
                timeout=10,
                allow_redirects=True
            )

            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, "html.parser")

            results = _extract_products(soup, query)

            if results:
                return results

        except requests.RequestException:
            continue

    # FALLBACK:
    # usa Google/Bing indicizzato tramite ricerca Deloox interna
    # partendo dalla home e dai link disponibili.

    try:
        response = session.get(
            BASE_URL,
            timeout=10,
            allow_redirects=True
        )

        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, "html.parser")

        candidates = []

        query_tokens = _tokens(query)

        for a in soup.find_all("a", href=True):
            text = _clean(a.get_text(" ", strip=True))
            href = _clean(a.get("href"))

            if not text or not href:
                continue

            text_tokens = _tokens(text)

            if any(token in text_tokens for token in query_tokens):
                candidates.append(urljoin(BASE_URL, href))

        for candidate in candidates[:10]:
            try:
                response = session.get(
                    candidate,
                    timeout=10,
                    allow_redirects=True
                )

                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")

                results = _extract_products(soup, query)

                if results:
                    return results

            except requests.RequestException:
                continue

    except requests.RequestException:
        pass

    return []


if __name__ == "__main__":
    print(search("Hawas Ice"))
