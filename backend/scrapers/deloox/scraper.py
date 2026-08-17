import json
import re
from collections import deque
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
HOME_URL = f"{BASE_URL}/en"
TIMEOUT = 10
DISCOVERY_TIMEOUT = 6

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

PRICE_RE = re.compile(
    r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?",
    re.I,
)
SIZE_RE = re.compile(r"\b(\d{1,3}(?:[.,]\d+)?)\s*ml\b", re.I)
SIZE_FULL_RE = re.compile(r"^(\d{1,3}(?:[.,]\d+)?)\s*ml$", re.I)

SOLD_OUT = (
    "sold out",
    "out of stock",
    "not available",
    "currently unavailable",
)

NON_FRAGRANCE = (
    "body mist", "body spray", "body lotion", "body cream", "body oil",
    "body wash", "shower gel", "shower oil", "hand and body", "hand cream",
    "deodorant", "after shave", "aftershave", "hair mist", "hair spray",
    "soap",
)
NON_FRAGRANCE_TOKENS = {
    tuple(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())
    for value in NON_FRAGRANCE
}

CATEGORY_ROOTS = (
    f"{BASE_URL}/category/1000003/fragrances.html",
    f"{BASE_URL}/category/1075639/womens-fragrances.html",
    f"{BASE_URL}/category/1075660/womens-perfume.html",
    f"{BASE_URL}/category/1000054/mens-fragrances.html",
    f"{BASE_URL}/category/1025540/trending.html",
)

SITEMAP_ROOTS = (
    f"{BASE_URL}/sitemap.xml",
    f"{BASE_URL}/sitemap_index.xml",
    f"{BASE_URL}/sitemap-index.xml",
    f"{BASE_URL}/en/sitemap.xml",
)

PRODUCT_RE = re.compile(
    r'https?://(?:www\.)?deloox\.com[^"\'<>\s]*/product/[^"\'<>\s]+'
    r'|(?<![A-Za-z0-9])(?:/|(?:en|it|nl)/)product/[^"\'<>\s]+',
    re.I,
)
CATEGORY_RE = re.compile(
    r'https?://(?:www\.)?deloox\.com(?:/(?:en|it|nl))?'
    r'/category/\d+/[^"\'<>\s]+\.html'
    r'|(?<![A-Za-z0-9])/(?:en|it|nl)/category/\d+/[^"\'<>\s]+\.html'
    r'|(?<![A-Za-z0-9])/category/\d+/[^"\'<>\s]+\.html',
    re.I,
)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _tokens(value):
    return {x for x in _norm(value).split() if len(x) > 1}


def _matches_soft(text, query, minimum=0.55):
    wanted = _tokens(query)
    actual = _tokens(text)
    if not wanted:
        return False
    return sum(x in actual for x in wanted) / len(wanted) >= minimum


def _matches_exact(text, query):
    wanted = _tokens(query)
    return bool(wanted) and wanted.issubset(_tokens(text))


def _match_score(text, query):
    wanted = _tokens(query)
    actual = _tokens(text)
    if not wanted:
        return -9999
    found = len(wanted & actual)
    if not found:
        return -9999
    return found * 100 - (len(wanted) - found) * 35 - abs(
        len(actual) - len(wanted)
    )


def _extract_price(text):
    match = PRICE_RE.search(_clean(text))
    if not match:
        return None
    value = match.group(1).replace(",", ".")
    try:
        number = float(value)
    except ValueError:
        return None
    return f"{number:.2f}".replace(".", ",") + " €"


def _get(session, url, timeout=TIMEOUT):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response
    except requests.RequestException as error:
        print(f"DELOOX ERROR: {error}")
        return None


def _query_wants_non_fragrance(query):
    wanted = _tokens(query)
    return any(set(phrase).issubset(wanted) for phrase in NON_FRAGRANCE_TOKENS)


def _contains_non_fragrance_product(text):
    actual = _norm(text)
    for phrase in NON_FRAGRANCE:
        normalized = _norm(phrase)
        if re.search(r"\b" + re.escape(normalized).replace(r"\ ", r"\s+") + r"\b", actual):
            return True
    return False


def _is_relevant_product(text, query):
    if not _matches_soft(text, query):
        return False
    return (
        _query_wants_non_fragrance(query)
        or not _contains_non_fragrance_product(text)
    )


def _normalize_product_url(raw_url):
    if not raw_url:
        return None
    url = urljoin(BASE_URL, _clean(raw_url).replace("\\/", "/"))
    url = url.split("#")[0].split("?")[0]
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
        return None
    return url if "/product/" in parsed.path.lower() else None


def _url_matches_query(product_url, query):
    """Discovery signal only: URL slug, never final validation."""
    wanted = _tokens(query)
    actual = _tokens(urlparse(product_url).path)
    if not wanted:
        return False
    return wanted.issubset(actual)


def _find_product_card(link):
    node = link
    for _ in range(8):
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if _extract_price(text) or SIZE_RE.search(text):
            return node
        node = node.parent
    return link


def _product_context(anchor, query):
    context = " ".join(
        _clean(x)
        for x in (
            anchor.get_text(" ", strip=True),
            anchor.get("aria-label"),
            anchor.get("title"),
            anchor.get("data-name"),
            anchor.get("data-product-name"),
        )
        if _clean(x)
    )
    if _matches_exact(context, query):
        return context

    card = _find_product_card(anchor)
    card_text = _clean(card.get_text(" ", strip=True))
    return card_text or context


def _extract_product_urls(html, query, allow_opaque=False):
    """Find candidate /product/ URLs without requiring card text."""
    soup = BeautifulSoup(html or "", "html.parser")
    found, seen = [], set()

    def add(raw_url, context=""):
        url = _normalize_product_url(raw_url)
        if not url or url in seen:
            return
        if not allow_opaque and not (
            _url_matches_query(url, query)
            or _matches_exact(context, query)
        ):
            return
        seen.add(url)
        found.append(url)

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        if "/product/" not in href.lower():
            continue
        add(href, _product_context(link, query))

    raw = (html or "").replace("\\\\/", "/").replace("\\/", "/")
    for match in PRODUCT_RE.finditer(raw):
        add(match.group(0))

    return found[:100]


def _product_urls_by_slug(html, query):
    """Independent URL-only discovery for pages with poor/missing card text."""
    return _extract_product_urls(html, query, allow_opaque=False)


def _absolute_category_url(raw_url):
    if not raw_url:
        return None
    url = urljoin(BASE_URL, _clean(raw_url).replace("\\/", "/"))
    url = url.split("#")[0].split("?")[0]
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
        return None
    if "/category/" not in parsed.path.lower():
        return None
    return url if parsed.path.lower().endswith(".html") else None


def _category_slug(url):
    value = urlparse(url).path.rsplit("/", 1)[-1]
    return value[:-5] if value.lower().endswith(".html") else value


def _category_score(url, label, query):
    wanted = _tokens(query)
    if not wanted:
        return 0
    slug = _tokens(_category_slug(url))
    label_tokens = _tokens(label)
    if wanted.issubset(slug) or wanted.issubset(label_tokens):
        return 200 + len(wanted) * 10
    return max(len(wanted & slug), len(wanted & label_tokens)) * 10


def _extract_category_links(html):
    soup = BeautifulSoup(html or "", "html.parser")
    found, seen = [], set()
    for link in soup.find_all("a", href=True):
        url = _absolute_category_url(link.get("href"))
        if url and url not in seen:
            seen.add(url)
            found.append((url, _clean(link.get_text(" ", strip=True))))
    return found


def _extract_category_links_from_html(html, query, source_url=""):
    raw = (html or "").replace("\\\\/", "/").replace("\\/", "/")
    soup = BeautifulSoup(raw, "html.parser")
    candidates = {}

    def add(raw_url, label=""):
        url = _absolute_category_url(raw_url)
        if not url:
            return
        score = _category_score(url, label, query)
        if score <= 0:
            return
        old = candidates.get(url)
        if old is None or score > old["score"]:
            candidates[url] = {
                "url": url,
                "label": _clean(label),
                "score": score,
            }

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        if "/category/" not in href.lower():
            continue
        label = " ".join(
            _clean(x)
            for x in (
                link.get_text(" ", strip=True),
                link.get("aria-label"),
                link.get("title"),
                link.get("data-name"),
                link.get("data-category-name"),
            )
            if _clean(x)
        )
        add(href, label)

    for match in CATEGORY_RE.finditer(raw):
        add(match.group(0))

    return sorted(
        candidates.values(),
        key=lambda item: (-item["score"], len(item["url"])),
    )


def _find_brand_category(session, query):
    """Generic category discovery; no product-specific seed URLs."""
    response = _get(session, HOME_URL, DISCOVERY_TIMEOUT)
    if response is None:
        return None

    candidates = _extract_category_links_from_html(
        response.text,
        query,
        HOME_URL,
    )
    if not candidates:
        return None
    return candidates[0]["url"]


def _walk_sitemaps(session, query, product_only=True, max_sitemaps=64):
    """Traverse XML sitemaps, prioritizing product sitemap children."""
    pending = deque(SITEMAP_ROOTS)
    seen_sitemaps = set()
    product_urls, category_urls = [], []
    seen_products, seen_categories = set(), set()

    while pending and len(seen_sitemaps) < max_sitemaps:
        sitemap_url = pending.popleft()
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        response = _get(session, sitemap_url, DISCOVERY_TIMEOUT)
        if response is None:
            continue

        body = (response.text or "").lstrip()
        if not body.startswith(("<?xml", "<urlset", "<sitemapindex")):
            continue

        soup = BeautifulSoup(response.text, "xml")
        children = []

        for loc in soup.find_all("loc"):
            value = _clean(loc.get_text())
            if not value:
                continue

            low = value.lower()
            if "/product/" in low:
                url = _normalize_product_url(value)
                if (
                    url
                    and _url_matches_query(url, query)
                    and url not in seen_products
                ):
                    seen_products.add(url)
                    product_urls.append(url)
                continue

            if "/category/" in low and low.endswith(".html"):
                category = _absolute_category_url(value)
                if (
                    category
                    and _tokens(query).issubset(
                        _tokens(_category_slug(category))
                    )
                    and category not in seen_categories
                ):
                    seen_categories.add(category)
                    category_urls.append(category)
                continue

            if low.endswith(".xml") or "sitemap" in low:
                children.append(value)

        children.sort(
            key=lambda value: (
                0 if any(
                    word in value.lower()
                    for word in ("product", "products", "perfume", "fragrance")
                ) else 1,
                value.lower(),
            )
        )
        pending.extendleft(reversed(children))

        if product_only and product_urls:
            return product_urls, category_urls

    return product_urls, category_urls


def _sitemap_product_urls(session, query, max_sitemaps=64, max_urls=80):
    products, _ = _walk_sitemaps(
        session,
        query,
        product_only=False,
        max_sitemaps=max_sitemaps,
    )
    return products[:max_urls]


def _sitemap_category_urls(session, query, max_sitemaps=32, max_urls=100):
    _, categories = _walk_sitemaps(
        session,
        query,
        product_only=False,
        max_sitemaps=max_sitemaps,
    )
    return categories[:max_urls]


def _discover_from_categories(session, query, max_urls=80):
    urls, seen = [], set()
    for root in CATEGORY_ROOTS:
        response = _get(session, root, DISCOVERY_TIMEOUT)
        if response is None:
            continue

        candidates = _extract_product_urls(response.text, query)
        for url in candidates:
            if url not in seen:
                seen.add(url)
                urls.append(url)
                if len(urls) >= max_urls:
                    return urls
    return urls


def _discover(session, query):
    """Discovery is independent from Deloox's internal search."""
    urls, seen = [], set()

    def add_many(items):
        for url in items or []:
            url = _normalize_product_url(url)
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= 80:
                return True
        return False

    # 1. Matching Product Line/category, when Deloox exposes one.
    dedicated = _find_brand_category(session, query)
    if dedicated:
        response = _get(session, dedicated, DISCOVERY_TIMEOUT)
        if response is not None:
            candidates = _extract_product_urls(response.text, query)
            if add_many(candidates):
                return urls[:80]

    # 2. Product sitemap is a primary source, not a last fallback.
    if add_many(_sitemap_product_urls(session, query)):
        return urls[:80]

    # 3. Search endpoints are optional discovery sources.
    encoded = quote_plus(query)
    for endpoint in (
        f"{BASE_URL}/en/search?q={encoded}",
        f"{BASE_URL}/en/search?query={encoded}",
        f"{BASE_URL}/en/search?search={encoded}",
        f"{BASE_URL}/en/search?term={encoded}",
    ):
        response = _get(session, endpoint, DISCOVERY_TIMEOUT)
        if response is None:
            continue

        candidates = _extract_product_urls(response.text, query)
        if add_many(candidates):
            return urls[:80]

    # 4. Matching category sitemap pages.
    for category_url in _sitemap_category_urls(session, query):
        response = _get(session, category_url, DISCOVERY_TIMEOUT)
        if response is None:
            continue
        if add_many(_extract_product_urls(response.text, query)):
            return urls[:80]

    # 5. Broad categories remain the generic HTML fallback.
    add_many(_discover_from_categories(session, query))
    return urls[:80]


def _extract_product_variants(html, product_name, product_url):
    soup = BeautifulSoup(html, "html.parser")
    strings = [_clean(value) for value in soup.stripped_strings if _clean(value)]
    results, seen_sizes = [], set()

    for index, value in enumerate(strings):
        match = SIZE_FULL_RE.fullmatch(value)
        if not match:
            continue

        size = match.group(1).replace(",", ".")
        size_label = f"{size} ml"
        if size_label in seen_sizes:
            continue

        chunk, sold_out = [], False
        for next_value in strings[index + 1:index + 31]:
            if SIZE_FULL_RE.fullmatch(next_value):
                break
            chunk.append(next_value)
            if any(word in next_value.lower() for word in SOLD_OUT):
                sold_out = True
                break

        if sold_out:
            continue

        price = _extract_price(" ".join(chunk))
        if not price:
            continue

        seen_sizes.add(size_label)
        slug = re.sub(r"[^a-z0-9]+", "-", size_label.lower()).strip("-")
        results.append({
            "store": STORE,
            "name": f"{product_name} {size_label}",
            "price": price,
            "url": f"{product_url}#{slug}",
            "available": True,
            "availability": "in_stock",
            "size": size_label,
        })

    return results


def _extract_jsonld_variants(html, product_name, product_url):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue

        objects = data if isinstance(data, list) else [data]
        for item in objects:
            if not isinstance(item, dict):
                continue

            item_text = f"{item.get('name', '')} {item.get('description', '')}"
            size_match = SIZE_RE.search(item_text)
            if not size_match:
                continue

            size = size_match.group(1).replace(",", ".")
            offers = item.get("offers", [])
            offers = offers if isinstance(offers, list) else [offers]

            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                price = offer.get("price")
                if price is None:
                    continue
                if str(offer.get("priceCurrency", "EUR")) != "EUR":
                    continue
                availability = str(offer.get("availability", "")).lower()
                if "outofstock" in availability:
                    continue

                price_text = str(price).replace(".", ",")
                if "," not in price_text:
                    price_text += ",00"

                results.append({
                    "store": STORE,
                    "name": f"{product_name} {size} ml",
                    "price": f"{price_text} €",
                    "url": product_url,
                    "available": True,
                    "availability": "in_stock",
                    "size": f"{size} ml",
                })

    return results


def _size_number(item):
    match = SIZE_RE.search(item.get("size", ""))
    if not match:
        return 9999
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return 9999


def _product_page_is_relevant(html, query):
    """Final validation happens after discovery, on the real product page."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    h1_text = _clean(h1.get_text(" ", strip=True)) if h1 else ""

    jsonld_names = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except Exception:
            continue
        objects = data if isinstance(data, list) else [data]
        for item in objects:
            if isinstance(item, dict) and item.get("name"):
                jsonld_names.append(str(item["name"]))

    candidates = [h1_text] + jsonld_names
    return any(
        _matches_exact(name, query) or _matches_soft(name, query, 0.55)
        for name in candidates
        if _clean(name)
    )


def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    try:
        discovered = _discover(session, query)
        if not discovered:
            return []

        final_results = []
        seen_variants = set()

        for product_url in discovered:
            response = _get(session, product_url)
            if response is None:
                continue

            # Candidate discovery is deliberately permissive; validation is here.
            if not _product_page_is_relevant(response.text, query):
                continue

            variants = _extract_product_variants(
                response.text,
                query,
                product_url,
            )
            if not variants:
                variants = _extract_jsonld_variants(
                    response.text,
                    query,
                    product_url,
                )

            for variant in variants:
                key = (
                    variant["url"],
                    variant.get("size", ""),
                    variant["price"],
                )
                if key in seen_variants:
                    continue
                seen_variants.add(key)
                final_results.append(variant)

        final_results.sort(key=_size_number)
        return final_results[:20]
    finally:
        session.close()


def scrape(query):
    return search(query)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
