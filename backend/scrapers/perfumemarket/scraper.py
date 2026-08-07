import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin

BASE_URL = "https://www.perfumemarket.nl"
PRICE_RE = re.compile(r"€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€")


def _extract_price(text):
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return value.replace(".", ",") + " €"


def _matches(text, query):
    text = (text or "").lower()
    query_tokens = [t.lower() for t in query.split() if t.strip()]
    return bool(query_tokens) and all(token in text for token in query_tokens)


def _soft_matches(text, query):
    """
    Match più permissivo per siblings:
    basta che ALMENO un token della query sia presente nel testo.
    Questo aiuta a catturare link come '50 ml', '100 ml', ecc.,
    collegati alla stessa fragranza.
    """
    text = (text or "").lower()
    query_tokens = [t.lower() for t in query.split() if t.strip()]
    if not query_tokens:
        return False
    return any(token in text for token in query_tokens)


def _extract_product_page(session, product_url, query):
    try:
        response = session.get(product_url, timeout=15)
        response.raise_for_status()
    except requests.RequestException:
        return None, []

    soup = BeautifulSoup(response.text, "html.parser")

    h1 = soup.find("h1")
    name = h1.get_text(" ", strip=True) if h1 else ""

    if not name or not _matches(name, query):
        title = soup.find("title")
        title_text = title.get_text(" ", strip=True) if title else ""
        if _matches(title_text, query):
            name = title_text

    if not name:
        return None, []

    # Prefer price elements on the product page instead of the whole page.
    price = None
    price_selectors = [
        "[class*='price']",
        "[id*='price']",
        "[data-product-price]",
        "[itemprop='price']",
    ]

    for selector in price_selectors:
        for element in soup.select(selector):
            price = _extract_price(element.get_text(" ", strip=True))
            if price:
                break
        if price:
            break

    if not price:
        price = _extract_price(soup.get_text(" ", strip=True))

    item = None
    if price:
        item = {
            "store": "PerfumeMarket",
            "name": name,
            "price": price,
            "url": product_url.split("?")[0]
        }

    # Collect sibling product URLs shown on the same product page.
    siblings = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = urljoin(BASE_URL, link.get("href", "")).split("?")[0]
        text = link.get_text(" ", strip=True)
        title = link.get("title", "")
        img = link.find("img")
        alt = img.get("alt", "") if img else ""

        candidate_text = " ".join(x for x in (text, title, alt) if x)

        if (
            "/products/" in href.lower()
            and href != product_url.split("?")[0]
            and _soft_matches(candidate_text, query)  # <--- qui
            and href not in seen
        ):
            seen.add(href)
            siblings.append(href)

    return item, siblings


def search(query):
    url = BASE_URL + "/search?q=" + quote(query)

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    session = requests.Session()
    session.headers.update(headers)

    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"PERFUMEMARKET ERROR: {error}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()
    product_urls = []

    query_tokens = [t.lower() for t in query.split() if t.strip()]

    # Logica originale: raccoglie tutti i prodotti visibili nella ricerca.
    for link in soup.find_all("a", href=True):
        name = link.get_text(" ", strip=True)
        href = link.get("href", "")

        if not name or not href:
            continue

        name_lower = name.lower()
        if not all(token in name_lower for token in query_tokens):
            continue

        node = link
        price = None

        for _ in range(5):
            if node is None:
                break

            text = node.get_text(" ", strip=True)
            price = _extract_price(text)

            if price:
                break

            node = node.parent

        product_url = urljoin(BASE_URL, href).split("?")[0]

        if "/products/" not in product_url.lower():
            continue

        if product_url not in product_urls:
            product_urls.append(product_url)

        if not price or product_url in seen:
            continue

        seen.add(product_url)

        results.append({
            "store": "PerfumeMarket",
            "name": name,
            "price": price,
            "url": product_url
        })

    # Secondo passaggio: apriamo i prodotti trovati e recuperiamo eventuali
    # altri formati dello stesso profumo (30 ml, 50 ml, 100 ml, ecc.).
    queue = list(product_urls)
    checked = set()

    while queue and len(checked) < 25:  # <--- 12 -> 25
        product_url = queue.pop(0)

        if product_url in checked:
            continue

        checked.add(product_url)

        item, siblings = _extract_product_page(
            session,
            product_url,
            query
        )

        if item and item["url"] not in seen:
            seen.add(item["url"])
            results.append(item)

        for sibling in siblings:
            if sibling not in checked and sibling not in queue:
                queue.append(sibling)

    return results


if __name__ == "__main__":
    results = search("Neroli Portofino Tom Ford")

    print("RISULTATI:", len(results))

    for product in results[:20]:
        print(product)
