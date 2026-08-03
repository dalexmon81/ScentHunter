import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

STORE = "ParfumCity"
BASE_URL = "https://www.parfumcity.nl"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def _price(text):
    m = re.search(r"€\s*(\d{1,4}(?:[.,]\d{2})?)|(\d{1,4}(?:[.,]\d{2})?)\s*€", text or "")
    if not m:
        return ""
    value = (m.group(1) or m.group(2)).replace(".", ",")
    return value + "€"

def _matches(text, query):
    text = text.lower()
    words = [w.lower() for w in query.split() if len(w) > 1]
    return all(w in text for w in words)

def search(query):
    query = _clean(query)
    if not query:
        return []

    url = BASE_URL + "/search?q=" + quote_plus(query)

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        print("PARFUMCITY ERROR:", e)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if not href or href.startswith("#"):
            continue

        product_url = urljoin(BASE_URL, href)
        if "parfumcity.nl" not in product_url:
            continue

        node = link
        block_text = _clean(link.get_text(" ", strip=True))

        for _ in range(6):
            candidate = _clean(node.get_text(" ", strip=True))
            if "€" in candidate and _matches(candidate, query):
                block_text = candidate
                break
            if node.parent is None:
                break
            node = node.parent

        if not _matches(block_text, query):
            continue

        price = _price(block_text)
        if not price:
            continue

        name = _clean(link.get_text(" ", strip=True))
        if not _matches(name, query):
            # Prefer a heading inside the product card if the anchor itself is image-only.
            heading = node.find(["h1", "h2", "h3", "h4"])
            if heading:
                name = _clean(heading.get_text(" ", strip=True))
        if not _matches(name, query):
            name = query

        # Reject utility links and sample/decant/service products.
        low_url = product_url.lower()
        low_name = name.lower()
        low_text = block_text.lower()

        blocked_urls = [
            "/cart", "/account", "/wishlist", "/search?", "/login",
            "sample-service", "sample_service", "/sample", "/samples",
            "/decant", "/tester"
        ]
        blocked_text = [
            "sample service", "sample-service", "sample ", " samples",
            "decant", "tester service"
        ]

        if any(x in low_url for x in blocked_urls):
            continue
        if any(x in low_name or x in low_text for x in blocked_text):
            continue

        key = product_url.split("?")[0]
        if key in seen:
            continue
        seen.add(key)

        results.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": product_url,
        })

        if len(results) >= 10:
            break

    return results

if __name__ == "__main__":
    items = search("Hawas Ice")
    print("RISULTATI:", len(items))
    for item in items:
        print(item)
