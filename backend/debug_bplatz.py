import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin

STORE = "Bplatz"
BASE = "https://en.bplatz.de"
CATALOG_URL = BASE + "/collections/produkte"
TIMEOUT = 5
CATALOG_PAGE_SIZE = 250
MAX_CATALOG_PAGES = 20
MAX_RESULTS = 50
CATALOG_WORKERS = 8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

STOPWORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait", "spray",
    "for", "by", "pour", "ml", "cl", "men", "man", "women", "woman",
    "male", "female", "homme", "femme", "herren", "damen",
}


def _norm(value):
    value = str(value or "").lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _query_tokens(query):
    tokens = []
    for token in _norm(query).split():
        if token in STOPWORDS or re.fullmatch(r"\d+(?:[.,]\d+)?", token):
            continue
        tokens.append(token)
    return tokens


def _match(text, query):
    wanted = _query_tokens(query)
    if not wanted:
        return False
    hay = set(_norm(text).split())
    return all(token in hay for token in wanted)


def _price(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number >= 100:
            number /= 100.0
        return f"{number:.2f}".replace(".", ",") + " €"

    text = str(value)
    patterns = (
        r"retail\s+price\s*€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"sale\s+price\s*€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"(\d{1,4}(?:[.,]\d{2})?)\s*€",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            number = float(match.group(1).replace(",", "."))
            if number > 0:
                return f"{number:.2f}".replace(".", ",") + " €"
    return None


def _absolute_product_url(value):
    value = str(value or "").strip()
    if not value:
        return ""
    return urljoin(BASE + "/", value).split("#")[0].split("?")[0].rstrip("/")


def _product_js_url(url):
    url = url.rstrip("/")
    return url if url.endswith(".js") else url + ".js"


def _get(session, url, params=None, accept=None):
    try:
        return session.get(
            url,
            params=params,
            headers={**HEADERS, **({"Accept": accept} if accept else {})},
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None


def _product_urls_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        url = _absolute_product_url(anchor.get("href"))
        if "/products/" not in url.lower() or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _catalog_json_page(session, page):
    response = _get(
        session,
        CATALOG_URL + "/products.json",
        {
            "limit": CATALOG_PAGE_SIZE,
            "page": page,
        },
        accept="application/json,text/plain,*/*",
    )
    if not response or response.status_code != 200:
        return None
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    products = payload.get("products") if isinstance(payload, dict) else None
    return products if isinstance(products, list) else None


def _catalog_html_page(session, page):
    response = _get(session, CATALOG_URL, {"page": page})
    if not response or response.status_code != 200:
        return []
    return _product_urls_from_html(response.text)


def _candidate_from_catalog_product(product):
    if not isinstance(product, dict):
        return None
    url = _absolute_product_url(
        product.get("handle") or product.get("url") or ""
    )
    if not url:
        return None
    title = str(product.get("title") or "").strip()
    vendor = str(product.get("vendor") or "").strip()
    if not title:
        return None
    return {
        "url": url,
        "title": title,
        "vendor": vendor,
        "raw": product,
    }


def _discover_catalog(query, session):
    """
    Discover candidates from the store catalog, never from product-specific
    rules. Shopify's public collection product feed is attempted first because
    it returns many products per request. The public collection HTML is the
    generic fallback when that feed is unavailable.
    """
    candidates = {}
    query = str(query or "").strip()

    first = _catalog_json_page(session, 1)
    if first is not None:
        for product in first:
            candidate = _candidate_from_catalog_product(product)
            if not candidate:
                continue
            if _match(
                f"{candidate['title']} {candidate['vendor']} {candidate['url']}",
                query,
            ):
                candidates[candidate["url"]] = candidate

        # Continue through the public Shopify product feed until it is empty
        # or the bounded catalog limit is reached.
        for page in range(2, MAX_CATALOG_PAGES + 1):
            products = _catalog_json_page(session, page)
            if products is None or not products:
                break
            for product in products:
                candidate = _candidate_from_catalog_product(product)
                if not candidate:
                    continue
                if _match(
                    f"{candidate['title']} {candidate['vendor']} {candidate['url']}",
                    query,
                ):
                    candidates[candidate["url"]] = candidate
            if len(products) < CATALOG_PAGE_SIZE:
                break

        if candidates:
            return list(candidates.values())

    # Generic HTML catalog fallback.
    page_urls = {}
    first_urls = _catalog_html_page(session, 1)
    page_urls[1] = first_urls

    # The first collection page publishes its pagination links. Follow only
    # those links instead of inventing a product-specific page range.
    response = _get(session, CATALOG_URL, {"page": 1})
    if response and response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = urljoin(BASE, anchor.get("href", "")).split("#")[0]
            match = re.search(r"[?&]page=(\d+)", href, re.I)
            if match:
                page = int(match.group(1))
                if 1 <= page <= MAX_CATALOG_PAGES:
                    page_urls.setdefault(page, [])

    def fetch(page):
        return page, _catalog_html_page(session, page)

    with ThreadPoolExecutor(
        max_workers=min(CATALOG_WORKERS, max(1, len(page_urls)))
    ) as pool:
        futures = [pool.submit(fetch, page) for page in sorted(page_urls)]
        for future in as_completed(futures):
            _, urls = future.result()
            for url in urls:
                if _match(url, query):
                    candidates[url] = {
                        "url": url,
                        "title": "",
                        "vendor": "",
                        "raw": None,
                    }
    return list(candidates.values())


def _product_worker(candidate, query):
    url = candidate["url"]
    session = requests.Session()
    try:
        response = _get(
            session,
            _product_js_url(url),
            accept="application/json,text/plain,*/*",
        )
        if not response or response.status_code != 200:
            return []

        try:
            product = response.json()
        except (ValueError, TypeError):
            return []
        if not isinstance(product, dict):
            return []

        title = str(product.get("title") or candidate.get("title") or "").strip()
        vendor = str(
            product.get("vendor") or candidate.get("vendor") or ""
        ).strip()

        if not title or not _match(f"{title} {vendor} {url}", query):
            return []

        image = product.get("featured_image")
        if isinstance(image, dict):
            image = image.get("src") or image.get("url")
        if not image:
            images = product.get("images") or []
            image = images[0] if images else None

        rows = []
        variants = product.get("variants") or []
        if not isinstance(variants, list):
            return []

        for variant in variants:
            if not isinstance(variant, dict):
                continue
            if variant.get("available") is False:
                continue
            price = _price(variant.get("price"))
            if not price:
                continue

            variant_title = str(variant.get("title") or "").strip()
            rows.append({
                "store": STORE,
                "name": title,
                "price": price,
                "url": url,
                "brand": vendor or None,
                "variant": (
                    variant_title
                    if variant_title.lower() not in {"default title", "default"}
                    else None
                ),
                "available": variant.get("available"),
                "image": _absolute_product_url(image) if image else None,
                "size_ml": _size_ml(variant_title, title),
            })
        return rows
    finally:
        session.close()


def _size_ml(*values):
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        " ".join(str(v or "") for v in values),
        re.I,
    )
    if not match:
        return None
    number = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        number *= 10
    return int(number) if number.is_integer() else number


def search_stream(query, emit):
    query = str(query or "").strip()
    if not query:
        return None

    session = requests.Session()
    try:
        candidates = _discover_catalog(query, session)
    finally:
        session.close()

    if not candidates:
        return None

    with ThreadPoolExecutor(
        max_workers=min(CATALOG_WORKERS, len(candidates))
    ) as pool:
        futures = [
            pool.submit(_product_worker, candidate, query)
            for candidate in candidates
        ]
        for future in as_completed(futures):
            try:
                rows = future.result() or []
            except Exception:
                continue
            for row in rows:
                if isinstance(row, dict):
                    emit(row)
    return None


def search(query):
    results = []
    seen = set()

    def emit(row):
        key = (
            row.get("url"),
            row.get("variant"),
            row.get("price"),
        )
        if key in seen:
            return
        seen.add(key)
        results.append(row)

    search_stream(query, emit)
    return results[:MAX_RESULTS]


def scrape(query):
    return search(query)


def diagnose(query):
    query = str(query or "").strip()
    if not query:
        return {"diagnostic": True, "query": query, "candidate_count": 0, "candidates": []}

    session = requests.Session()
    try:
        candidates = _discover_catalog(query, session)
        return {
            "diagnostic": True,
            "query": query,
            "candidate_count": len(candidates),
            "candidates": [c["url"] for c in candidates[:100]],
        }
    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()

    print(json.dumps(
        diagnose(args.query) if args.diagnose else search(args.query),
        ensure_ascii=False,
        indent=2,
    ))
