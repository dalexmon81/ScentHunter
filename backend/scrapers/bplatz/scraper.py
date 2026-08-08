import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET

STORE = "Bplatz"
BASE = "https://en.bplatz.de"
TIMEOUT = 5
MAX_RESULTS = 20
MAX_CANDIDATES = 16

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

EXCLUDED_WORDS = {
    "tester", "gift", "set", "bundle", "duo", "box", "discovery",
    "mini", "sample", "samples", "deodorant", "body", "shower",
    "lotion", "cream", "refill", "aftershave",
}


def _norm(value):
    value = str(value or "").lower()
    value = (
        value.replace("é", "e").replace("è", "e")
        .replace("ê", "e").replace("ë", "e")
        .replace("á", "a").replace("à", "a")
        .replace("ó", "o").replace("ö", "o")
        .replace("ü", "u")
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


def _tokens(value):
    return set(_norm(value).split())


def _is_excluded(name):
    return bool(_tokens(name) & EXCLUDED_WORDS)


def _score(name, query):
    nt = _tokens(name)
    qt = _tokens(query)
    if not qt or not qt.issubset(nt) or _is_excluded(name):
        return 0

    score = len(qt) * 10
    nq = _norm(query)
    nn = _norm(name)
    if nq and nq in nn:
        score += 40
    return score


def _format_price(value):
    if value is None:
        return None

    text = str(value).strip().replace("€", "").replace(" ", "")
    text = text.replace(",", ".")
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None

    if number <= 0:
        return None

    return f"{number:.2f}".replace(".", ",") + " €"


def _clean_url(url):
    if not url:
        return None
    return urljoin(BASE, str(url)).split("#")[0].split("?")[0]


def _product_url_from_slug(slug):
    slug = str(slug or "").strip()
    if not slug:
        return None
    return _clean_url("/products/" + slug)


def _parse_sitemap_locs(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    return [
        loc.text.strip()
        for loc in root.iter()
        if loc.tag.lower().endswith("loc") and loc.text
    ]


def _get_product_sitemaps(session):
    try:
        response = session.get(
            f"{BASE}/sitemap.xml",
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return []

    if response.status_code != 200 or not response.text:
        return []

    locs = _parse_sitemap_locs(response.text)
    return [
        loc for loc in locs
        if "sitemap_products_" in loc.lower()
    ]


def _candidate_urls_from_sitemap(xml_text, query):
    qt = _tokens(query)
    if not qt:
        return []

    urls = []
    seen = set()

    for loc in _parse_sitemap_locs(xml_text):
        low = loc.lower()
        if "/products/" not in low:
            continue

        slug = low.rsplit("/products/", 1)[-1]
        slug_tokens = _tokens(slug.replace("-", " "))

        if not qt.issubset(slug_tokens):
            continue

        clean = _clean_url(loc)
        if clean and clean not in seen:
            seen.add(clean)
            urls.append(clean)

    return urls


def _fetch_product_sitemap(session, sitemap_url):
    try:
        response = session.get(
            sitemap_url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return ""

    if response.status_code != 200:
        return ""
    return response.text or ""


def _find_candidates_from_html(session, query):
    """Fallback for Shopify stores where sitemap search misses translated/brand-prefixed handles."""
    q = quote_plus(query)

    urls = []
    seen = set()

    # Normal Shopify product search page.
    for endpoint in (
        f"{BASE}/search?q={q}&type=product",
        f"{BASE}/search?type=product&q={q}",
    ):
        try:
            response = session.get(
                endpoint,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if response.status_code != 200 or not response.text:
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "")
            if "/products/" not in href.lower():
                continue

            url = _clean_url(href)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        if urls:
            break

    return urls[:MAX_CANDIDATES]


def _find_candidates_from_predictive_search(session, query):
    q = quote_plus(query)

    try:
        response = session.get(
            f"{BASE}/search/suggest.json"
            f"?q={q}&resources[type]=product&resources[limit]=20",
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return []

    if response.status_code != 200:
        return []

    try:
        data = response.json()
    except (ValueError, TypeError, json.JSONDecodeError):
        return []

    resources = data.get("resources") or {}
    block = resources.get("results") or {}
    products = block.get("products") or []

    urls = []
    seen = set()

    for product in products:
        if not isinstance(product, dict):
            continue

        title = str(product.get("title") or "").strip()
        if not _score(title, query):
            continue

        handle = product.get("handle")
        url = _product_url_from_slug(handle)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    return urls[:MAX_CANDIDATES]


def _find_candidates(session, query):
    """Use sitemap first, then Shopify's normal search, then predictive search."""
    urls = []
    seen = set()

    # 1. Sitemap: fastest and most precise when the handle contains the query.
    sitemaps = _get_product_sitemaps(session)

    for sitemap_url in sitemaps[:4]:
        xml_text = _fetch_product_sitemap(session, sitemap_url)
        if not xml_text:
            continue

        for url in _candidate_urls_from_sitemap(xml_text, query):
            if url not in seen:
                seen.add(url)
                urls.append(url)

        if urls:
            return urls[:MAX_CANDIDATES]

    # 2. Normal Shopify search page.
    for url in _find_candidates_from_html(session, query):
        if url not in seen:
            seen.add(url)
            urls.append(url)

    if urls:
        return urls[:MAX_CANDIDATES]

    # 3. Shopify predictive search.
    for url in _find_candidates_from_predictive_search(session, query):
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls[:MAX_CANDIDATES]


def _extract_price_and_availability(soup):
    """
    Return the actual customer price, not the €/100ml reference price.
    Prefer an in-stock JSON-LD offer. If multiple offers exist, keep an
    available one instead of rejecting the whole product because one
    variant is out of stock.
    """
    found_available_price = None
    found_out_of_stock = False

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue

        objects = data if isinstance(data, list) else [data]

        for obj in objects:
            if not isinstance(obj, dict):
                continue

            offers = obj.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if not isinstance(offers, list):
                continue

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                availability = str(
                    offer.get("availability") or ""
                ).lower()

                if any(x in availability for x in (
                    "outofstock", "soldout", "unavailable"
                )):
                    found_out_of_stock = True
                    continue

                price = _format_price(
                    offer.get("price") or offer.get("lowPrice")
                )
                if price:
                    found_available_price = price

    if found_available_price:
        return found_available_price, True

    # Shopify product meta tags.
    amount = soup.find("meta", attrs={"property": "product:price:amount"})
    if amount and amount.get("content"):
        price = _format_price(amount.get("content"))
        if price:
            return price, True

    page_text = " ".join(soup.stripped_strings).strip().lower()

    if any(x in page_text for x in (
        "sold out", "out of stock", "not available"
    )):
        return None, False

    # Last price fallback. Never use €/100ml or €/l.
    for pattern in (
        r"(?:regular\s+price|retail\s+price)\s*€\s*"
        r"(\d{1,4}(?:[.,]\d{1,2})?)",
        r"(?<![/\w])€\s*(\d{1,4}(?:[.,]\d{1,2})?)(?!\s*/)",
    ):
        match = re.search(pattern, page_text, re.I)
        if match:
            price = _format_price(match.group(1))
            if price:
                return price, True

    return None, True


def _read_product(session, url, query):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None

    if response.status_code != 200 or not response.text:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = " ".join(h1.stripped_strings).strip()

    if not title:
        meta = soup.find("meta", property="og:title")
        if meta:
            title = str(meta.get("content") or "").strip()

    if not title:
        return None

    score = _score(title, query)

    # Bplatz can have a brand-prefixed/translated title while the URL slug
    # contains the searched words.
    if not score:
        slug = url.rsplit("/products/", 1)[-1]
        score = _score(slug.replace("-", " "), query)

    if not score or _is_excluded(title):
        return None

    price, available = _extract_price_and_availability(soup)

    if not available or not price:
        return None

    return {
        "store": STORE,
        "name": title,
        "price": price,
        "url": _clean_url(url),
        "_score": score,
    }


def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    urls = _find_candidates(session, query)

    if not urls:
        return []

    results = []

    with ThreadPoolExecutor(max_workers=min(6, len(urls))) as pool:
        futures = {
            pool.submit(_read_product, session, url, query): url
            for url in urls
        }

        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception:
                item = None

            if item:
                results.append(item)

    results.sort(
        key=lambda x: (
            -int(x.get("_score", 0)),
            len(_norm(x.get("name", ""))),
            _norm(x.get("name", "")),
        )
    )

    for item in results:
        item.pop("_score", None)

    return results[:MAX_RESULTS]


if __name__ == "__main__":
    for query in (
        "Liquid Brun",
        "Liquid Brun Limited Edition",
        "Rasasi Hawas",
        "Rasasi Hawas Ice",
        "Armaf Club de Nuit",
        "Afnan 9 PM",
        "French Avenue",
    ):
        print("\n" + "=" * 70)
        print("QUERY:", query)
        items = search(query)
        print("RISULTATI:", len(items))
        for item in items:
            print(item)
