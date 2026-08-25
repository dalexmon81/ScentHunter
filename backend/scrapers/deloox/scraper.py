import json
import re
import unicodedata
from urllib.parse import urljoin, quote_plus, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
HOME_URL = f"{BASE_URL}/en"
TIMEOUT = 10
DISCOVERY_TIMEOUT = 5
MAX_DISCOVERY_CANDIDATES = 40
MAX_PRODUCT_FETCHES = 24

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

PRICE_RE = re.compile(
    r"(?:€\s*)?(\d{1,4}(?:[,.]\d{2})?)(?:\s*€)?",
    re.I,
)

SOLD_OUT = (
    "sold out",
    "out of stock",
    "not available",
    "currently unavailable",
)

NON_FRAGRANCE = (
    "body mist", "body spray", "body lotion", "body cream",
    "body oil", "body wash", "shower gel", "shower oil",
    "hand and body", "hand cream", "deodorant", "after shave",
    "aftershave", "hair mist", "hair spray", "soap",
)

SIZE_RE = re.compile(r"\b(\d{1,3}(?:[.,]\d+)?)\s*ml\b", re.I)
SIZE_FULL_RE = re.compile(r"^(\d{1,3}(?:[.,]\d+)?)\s*ml$", re.I)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    value = unicodedata.normalize("NFKD", _clean(value).lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _tokens(value):
    return [x for x in _norm(value).split() if len(x) > 1]


def _token_set(value):
    return set(_tokens(value))


def _overlap_score(text, query):
    q = _token_set(query)
    t = _token_set(text)
    if not q:
        return 0.0
    return sum(x in t for x in q) / len(q)


def _match_score(text, query):
    q = _token_set(query)
    t = _token_set(text)
    if not q or not t:
        return -9999
    found = len(q & t)
    if not found:
        return -9999
    return found * 100 - (len(q) - found) * 35 - max(0, len(t) - len(q)) * 2


def _extract_price(text):
    text = _clean(text)
    if not text:
        return None

    # Prefer values that visibly contain the euro symbol.
    euro = re.search(r"€\s*(\d{1,4}(?:[,.]\d{2})?)|(\d{1,4}(?:[,.]\d{2})?)\s*€", text)
    if euro:
        value = euro.group(1) or euro.group(2)
    else:
        match = PRICE_RE.search(text)
        if not match:
            return None
        value = match.group(1)

    value = value.replace(",", ".")
    try:
        number = float(value)
    except ValueError:
        return None
    if number <= 0 or number > 10000:
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
        print(f"DELOOX ERROR url={url} error={error}")
        return None


def _is_product_url(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
        return False
    return "/product/" in parsed.path.lower()


def _canonical_url(url):
    return urljoin(BASE_URL, url).split("#")[0].split("?")[0]


def _query_wants_non_fragrance(query):
    q = _token_set(query)
    for phrase in NON_FRAGRANCE:
        if set(_tokens(phrase)).issubset(q):
            return True
    return False


def _contains_non_fragrance(text):
    tokens = _tokens(text)
    for phrase in NON_FRAGRANCE:
        p = _tokens(phrase)
        n = len(p)
        for i in range(len(tokens) - n + 1):
            if tokens[i:i + n] == p:
                return True
    return False


def _is_relevant_product(text, query):
    if _overlap_score(text, query) < 0.50:
        return False
    if not _query_wants_non_fragrance(query) and _contains_non_fragrance(text):
        return False
    return True


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


def _local_link_context(link):
    parts = [
        link.get_text(" ", strip=True),
        link.get("title", ""),
        link.get("aria-label", ""),
        link.get("data-name", ""),
        link.get("data-product-name", ""),
    ]
    context = " ".join(_clean(x) for x in parts if _clean(x))
    if not context:
        card = _find_product_card(link)
        context = _clean(card.get_text(" ", strip=True))
    return context


def _extract_product_links(html, query):
    """
    Generic product discovery.

    Crucially, the query is evaluated against the LOCAL product/card context,
    never against the complete page. This prevents a page-level occurrence of
    a query from authorizing unrelated product URLs.

    We do not require query tokens to exist in the URL slug: Deloox can expose
    the correct product behind numeric product URLs.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    seen = set()

    for link in soup.find_all("a", href=True):
        url = _canonical_url(link.get("href"))
        if not _is_product_url(url) or url in seen:
            continue

        context = _local_link_context(link)
        title = _clean(link.get("title", ""))
        card = _find_product_card(link)
        card_text = _clean(card.get_text(" ", strip=True))

        combined = " ".join(x for x in (context, title, card_text) if x)

        score = _match_score(combined, query)
        if score <= -100:
            continue

        if any(x in card_text.lower() for x in SOLD_OUT):
            continue

        # A product/card is considered a discovery candidate when at least
        # half the query tokens are locally present. Final validation is done
        # by fetching the actual product page.
        if _overlap_score(combined, query) < 0.50:
            continue

        if not _is_relevant_product(combined, query):
            continue

        seen.add(url)
        candidates.append((score, url, context, card_text))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates


def _extract_category_links(html, query):
    soup = BeautifulSoup(html, "html.parser")
    q = _token_set(query)
    candidates = []
    seen = set()

    for link in soup.find_all("a", href=True):
        url = _canonical_url(link.get("href"))
        if "/category/" not in url.lower():
            continue
        text = _clean(
            " ".join(
                (
                    link.get_text(" ", strip=True),
                    link.get("title", ""),
                    link.get("aria-label", ""),
                )
            )
        )
        if not text:
            continue
        overlap = len(q & _token_set(text))
        if overlap == 0:
            continue
        if url in seen:
            continue
        seen.add(url)
        candidates.append(
            (overlap / max(1, len(q)), overlap, url, text)
        )

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates


def _extract_navigation_links(html):
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    seen = set()
    for link in soup.find_all("a", href=True):
        url = _canonical_url(link.get("href"))
        if not url.startswith(BASE_URL):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(
            (
                url,
                _clean(
                    " ".join(
                        (
                            link.get_text(" ", strip=True),
                            link.get("title", ""),
                            link.get("aria-label", ""),
                        )
                    )
                ),
            )
        )
    return urls


def _sitemap_urls(session):
    """
    Generic sitemap discovery from robots.txt. No store/product-specific URL.
    """
    found = []
    seen = set()

    robots = _get(session, f"{BASE_URL}/robots.txt", timeout=DISCOVERY_TIMEOUT)
    if robots:
        for line in robots.text.splitlines():
            if line.lower().startswith("sitemap:"):
                sitemap = line.split(":", 1)[1].strip()
                if sitemap and sitemap not in seen:
                    seen.add(sitemap)
                    found.append(sitemap)

    # Generic fallbacks only for the standard sitemap conventions.
    for candidate in (
        f"{BASE_URL}/sitemap.xml",
        f"{BASE_URL}/sitemap_index.xml",
        f"{BASE_URL}/en/sitemap.xml",
    ):
        if candidate not in seen:
            found.append(candidate)
            seen.add(candidate)

    return found[:8]


def _parse_sitemap_locs(text):
    try:
        root = ET.fromstring(text)
    except Exception:
        return []
    locs = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag == "loc" and element.text:
            locs.append(_clean(element.text))
    return locs


def _discover_from_sitemaps(session, query):
    """
    Generic sitemap route. It first inspects sitemap indexes, then only
    product URLs whose own URL contains a meaningful query token. Product
    pages are still validated later, so sitemap matching is discovery only.
    """
    q = _token_set(query)
    if not q:
        return []

    queue = list(_sitemap_urls(session))
    visited = set()
    candidates = []

    while queue and len(visited) < 12 and len(candidates) < MAX_DISCOVERY_CANDIDATES:
        sitemap = queue.pop(0)
        if sitemap in visited:
            continue
        visited.add(sitemap)

        response = _get(session, sitemap, timeout=DISCOVERY_TIMEOUT)
        if response is None:
            continue

        locs = _parse_sitemap_locs(response.text)
        if not locs:
            continue

        child_sitemaps = [
            loc for loc in locs
            if loc.lower().endswith(".xml") or "sitemap" in loc.lower()
        ]
        product_locs = [
            loc for loc in locs
            if _is_product_url(loc)
        ]

        for child in child_sitemaps:
            if child not in visited and child not in queue:
                queue.append(child)

        for loc in product_locs:
            url_tokens = _token_set(loc)
            overlap = len(q & url_tokens)
            if overlap == 0:
                continue
            score = overlap * 50
            candidates.append((score, _canonical_url(loc), "", ""))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            if len(candidates) >= MAX_DISCOVERY_CANDIDATES:
                break

    deduped = []
    seen = set()
    for item in sorted(candidates, key=lambda x: x[0], reverse=True):
        if item[1] in seen:
            continue
        seen.add(item[1])
        deduped.append(item)
    return deduped[:MAX_DISCOVERY_CANDIDATES]


def _discover(session, query):
    """
    Generic discovery pipeline.

    Order:
      1. generic site search endpoints;
      2. homepage/category navigation;
      3. sitemap discovery.

    No product name, brand, category id, or product URL is hard-coded.
    """
    discovered = []
    seen = set()

    def add(items):
        for item in items:
            url = item[1]
            if url in seen:
                continue
            seen.add(url)
            discovered.append(item)

    encoded = quote_plus(query)
    search_urls = (
        f"{BASE_URL}/en/search?q={encoded}",
        f"{BASE_URL}/en/search?query={encoded}",
        f"{BASE_URL}/search?q={encoded}",
    )

    for search_url in search_urls:
        response = _get(session, search_url, timeout=DISCOVERY_TIMEOUT)
        if response is None:
            continue
        local = _extract_product_links(response.text, query)
        if local:
            print(
                f"DELOOX DISCOVERY search url={search_url} candidates={len(local)}"
            )
            add(local)
            if len(discovered) >= MAX_DISCOVERY_CANDIDATES:
                return discovered[:MAX_DISCOVERY_CANDIDATES]

    home = _get(session, HOME_URL)
    if home:
        direct = _extract_product_links(home.text, query)
        if direct:
            print(f"DELOOX DISCOVERY home direct={len(direct)}")
            add(direct)

        categories = _extract_category_links(home.text, query)
        print(f"DELOOX DISCOVERY home categories={len(categories)}")

        # Fetch relevant navigation categories. We deliberately use the
        # category text discovered from the site, never a hard-coded category.
        for _, _, category_url, _ in categories[:8]:
            page = _get(session, category_url, timeout=DISCOVERY_TIMEOUT)
            if page is None:
                continue
            local = _extract_product_links(page.text, query)
            if local:
                print(
                    f"DELOOX DISCOVERY category={category_url} candidates={len(local)}"
                )
                add(local)
            if len(discovered) >= MAX_DISCOVERY_CANDIDATES:
                return discovered[:MAX_DISCOVERY_CANDIDATES]

        # A product can belong to a brand/product-line category whose name
        # does not contain the exact query. We therefore inspect navigation
        # links in a bounded, generic way and score their visible labels.
        nav = _extract_navigation_links(home.text)
        nav_scored = []
        for url, label in nav:
            if not label or url in seen:
                continue
            if "/category/" not in url.lower():
                continue
            score = _overlap_score(label, query)
            if score > 0:
                nav_scored.append((score, url, label))

        nav_scored.sort(reverse=True)
        for _, category_url, _ in nav_scored[:12]:
            page = _get(session, category_url, timeout=DISCOVERY_TIMEOUT)
            if page is None:
                continue
            local = _extract_product_links(page.text, query)
            add(local)
            if len(discovered) >= MAX_DISCOVERY_CANDIDATES:
                return discovered[:MAX_DISCOVERY_CANDIDATES]

    sitemap_items = _discover_from_sitemaps(session, query)
    if sitemap_items:
        print(
            f"DELOOX DISCOVERY sitemap candidates={len(sitemap_items)}"
        )
        add(sitemap_items)

    return discovered[:MAX_DISCOVERY_CANDIDATES]


def _jsonld_objects(soup):
    objects = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        stack = list(data) if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if not isinstance(item, dict):
                continue
            objects.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
    return objects


def _product_name(soup):
    h1 = soup.find("h1")
    if h1:
        value = _clean(h1.get_text(" ", strip=True))
        if value:
            return value

    for item in _jsonld_objects(soup):
        item_type = item.get("@type")
        if item_type == "Product" or (
            isinstance(item_type, list) and "Product" in item_type
        ):
            value = _clean(item.get("name"))
            if value:
                return value
    return ""


def _product_price(soup):
    for item in _jsonld_objects(soup):
        item_type = item.get("@type")
        if item_type != "Product" and not (
            isinstance(item_type, list) and "Product" in item_type
        ):
            continue
        offers = item.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        if isinstance(offers, list):
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                currency = str(offer.get("priceCurrency", "EUR")).upper()
                if currency != "EUR":
                    continue
                price = offer.get("price")
                if price is not None:
                    return _extract_price(str(price) + " €")

    # Fallback: only visible product page text, never another page.
    return _extract_price(soup.get_text(" ", strip=True))


def _product_available(soup):
    # Prefer structured offer availability. A product page can expose several
    # offers/variants: one out-of-stock offer must NOT make the whole product
    # unavailable when another offer is explicitly in stock.
    structured_oos = False
    structured_in = False

    for item in _jsonld_objects(soup):
        offers = item.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        if not isinstance(offers, list):
            continue

        for offer in offers:
            if not isinstance(offer, dict):
                continue

            value = _norm(
                offer.get("availability")
                or offer.get("stock")
                or ""
            )

            if "outofstock" in value or "soldout" in value:
                structured_oos = True
            elif "instock" in value or "available" in value:
                structured_in = True

    if structured_in:
        return True
    if structured_oos:
        return False

    # Explicit stock metadata. Apply the same rule: explicit in-stock wins
    # over a different out-of-stock variant on the same product page.
    metadata_oos = False
    metadata_in = False

    for node in soup.select(
        '[itemprop="availability"], '
        'meta[property="product:availability"], '
        'meta[name="availability"]'
    ):
        value = _norm(node.get("content") or node.get_text(" ", strip=True))
        if "outofstock" in value or "soldout" in value:
            metadata_oos = True
        elif "instock" in value or "available" in value:
            metadata_in = True

    if metadata_in:
        return True
    if metadata_oos:
        return False

    return True


def _selected_size(soup, name):
    match = SIZE_RE.search(name or "")
    if match:
        return f"{match.group(1).replace(',', '.')} ml"

    for selector in (
        'input[type="radio"][checked]',
        'input[checked][name*="size" i]',
        'option[selected]',
        '[aria-selected="true"]',
    ):
        for node in soup.select(selector):
            blob = " ".join(
                (
                    node.get("value", ""),
                    node.get("aria-label", ""),
                    node.get("data-size", ""),
                    node.get_text(" ", strip=True),
                )
            )
            match = SIZE_RE.search(blob)
            if match:
                return f"{match.group(1).replace(',', '.')} ml"
    return ""


def _extract_jsonld_variants(soup, product_name, product_url):
    results = []
    seen = set()

    for item in _jsonld_objects(soup):
        item_type = item.get("@type")
        if item_type != "Product" and not (
            isinstance(item_type, list) and "Product" in item_type
        ):
            continue

        name = _clean(item.get("name"))
        size_match = SIZE_RE.search(name)
        if not size_match:
            continue

        size = size_match.group(1).replace(",", ".")
        offers = item.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        if not isinstance(offers, list):
            continue

        for offer in offers:
            if not isinstance(offer, dict):
                continue
            if str(offer.get("priceCurrency", "EUR")).upper() != "EUR":
                continue
            availability = _norm(offer.get("availability", ""))
            if "outofstock" in availability or "soldout" in availability:
                continue
            price = offer.get("price")
            if price is None:
                continue
            price_text = _extract_price(str(price) + " €")
            if not price_text:
                continue
            key = (size, price_text)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "store": STORE,
                    "name": f"{product_name} {size} ml",
                    "price": price_text,
                    "url": product_url,
                    "available": True,
                    "availability": "in_stock",
                    "size": f"{size} ml",
                }
            )
    return results


def _extract_product_variants(soup, product_name, product_url):
    """
    Local DOM variant extraction. Size and price must belong to the same
    reasonably small DOM block.
    """
    results = []
    seen = set()

    selectors = (
        "[class*='variant'], [class*='Variant'], "
        "[class*='option'], [class*='Option'], "
        "[class*='volume'], [class*='Volume'], "
        "[class*='size'], [class*='Size']"
    )

    for node in soup.select(selectors):
        text = _clean(node.get_text(" ", strip=True))
        if not text or len(text) > 700:
            continue

        sizes = SIZE_FULL_RE.findall(text)
        price = _extract_price(text)
        if not sizes or not price:
            continue

        for size in sizes:
            size = size.replace(",", ".")
            key = (size, price)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "store": STORE,
                    "name": f"{product_name} {size} ml",
                    "price": price,
                    "url": product_url,
                    "available": True,
                    "availability": "in_stock",
                    "size": f"{size} ml",
                }
            )

    if results:
        return results

    # Conservative fallback: start from an exact "X ml" text node and walk
    # only a few local parents, rejecting huge containers.
    for text_node in soup.find_all(string=SIZE_FULL_RE):
        value = _clean(text_node)
        match = SIZE_FULL_RE.fullmatch(value)
        if not match:
            continue

        size = match.group(1).replace(",", ".")
        parent = text_node.parent

        for _ in range(5):
            if parent is None:
                break
            block = _clean(parent.get_text(" ", strip=True))
            if len(block) <= 500:
                price = _extract_price(block)
                if price:
                    key = (size, price)
                    if key not in seen:
                        seen.add(key)
                        results.append(
                            {
                                "store": STORE,
                                "name": f"{product_name} {size} ml",
                                "price": price,
                                "url": product_url,
                                "available": True,
                                "availability": "in_stock",
                                "size": f"{size} ml",
                            }
                        )
                    break
            parent = parent.parent

    return results


def _validate_product(session, url, query):
    response = _get(session, url)
    if response is None:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    name = _product_name(soup)
    if not name:
        print(f"DELOOX VALIDATE_REJECT url={url} reason=no_name")
        return []

    score = _match_score(name, query)
    print(
        f"DELOOX VALIDATE url={url} name={name!r} score={score}"
    )

    # Final validation is deliberately strict: every significant query token
    # must be represented in the actual product name. This is the last gate,
    # after generic discovery.
    q_tokens = _token_set(query)
    name_tokens = _token_set(name)
    if not q_tokens or not q_tokens.issubset(name_tokens):
        print(
            f"DELOOX VALIDATE_REJECT url={url} reason=name_mismatch"
        )
        return []

    if not _is_relevant_product(name, query):
        print(
            f"DELOOX VALIDATE_REJECT url={url} reason=non_fragrance"
        )
        return []

    available = _product_available(soup)
    if not available:
        print(
            f"DELOOX VALIDATE_REJECT url={url} reason=out_of_stock"
        )
        return []

    variants = _extract_product_variants(
        soup, name, url
    )

    if not variants:
        variants = _extract_jsonld_variants(
            soup, name, url
        )

    if variants:
        print(
            f"DELOOX VALIDATED url={url} name={name!r} variants={len(variants)}"
        )
        return variants

    price = _product_price(soup)
    if not price:
        print(
            f"DELOOX VALIDATE_REJECT url={url} reason=no_price"
        )
        return []

    size = _selected_size(soup, name)
    result = {
        "store": STORE,
        "name": name,
        "price": price,
        "url": url,
        "available": True,
        "availability": "in_stock",
    }
    if size:
        result["size"] = size

    print(
        f"DELOOX VALIDATED url={url} name={name!r} price={price}"
    )
    return [result]


def _size_number(item):
    match = SIZE_RE.search(item.get("size", ""))
    if not match:
        return 9999
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return 9999


def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()

    print(f"DELOOX SEARCH_START query={query!r}")

    candidates = _discover(session, query)

    # Deduplicate while retaining discovery score/order.
    unique = []
    seen = set()
    for score, url, context, card in candidates:
        if url in seen:
            continue
        seen.add(url)
        unique.append((score, url, context, card))

    print(
        f"DELOOX DISCOVERY candidates={len(unique)}"
    )

    # Stronger candidates first. We do not throw away candidates merely
    # because their slug lacks the query: the page name is authoritative.
    unique.sort(key=lambda x: x[0], reverse=True)

    final = []
    seen_results = set()

    for score, url, context, card in unique[:MAX_PRODUCT_FETCHES]:
        validated = _validate_product(
            session,
            url,
            query,
        )
        for item in validated:
            key = (
                item.get("url", ""),
                item.get("size", ""),
                item.get("price", ""),
            )
            if key in seen_results:
                continue
            seen_results.add(key)
            final.append(item)

    final.sort(
        key=lambda item: (
            _size_number(item),
            item.get("price", ""),
        )
    )

    print(
        f"DELOOX SEARCH_COMPLETE found_total={len(final)}"
    )

    for index, item in enumerate(final[:20], 1):
        print(
            f"DELOOX RESULT {index}: "
            f"{item.get('name')!r} | "
            f"{item.get('price')} | "
            f"{item.get('url')}"
        )

    return final[:20]


if __name__ == "__main__":
    for query in ("sample perfume query",):
        print("\nQUERY:", query)
        results = search(query)
        if not results:
            print("NESSUN RISULTATO")
        else:
            for result in results:
                print(result)
