import re
import json
import html as html_lib
import unicodedata
from collections import deque
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qs

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7,it;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/fr/",
}

# Generic perfume/catalog entry points only.
# No perfume, brand, product or query-specific URL is seeded.
ROOTS = (
    BASE + "/fr/7-parfums-pour-homme",
    BASE + "/fr/31-fragrances-pour-homme",
    BASE + "/fr/6-parfums-pour-femme",
    BASE + "/fr/30-fragrances-pour-femme",
    BASE + "/fr/864-parfums-arabes-pour-femmes",
    BASE + "/fr/865-parfums-arabes-pour-hommes",
    BASE + "/fr/890-parfumerie-de-niche",
    BASE + "/fr/688-parfums-de-niche-pour-femme",
    BASE + "/fr/891-perfumes-nicho-unisex",
)

PRICE_RE = re.compile(
    r"(?<!\d)(\d{1,5}(?:[.,]\d{2}))\s*(?:€|EUR)\b?",
    re.I,
)

# Sabina product URLs observed in the site's generic catalog structure:
# /fr/<category>/<numeric-id>-<slug>.html
PRODUCT_PATH_RE = re.compile(
    r"^/fr/(?!"
    r"(?:content|search|recherche|login|mon-compte|panier|cart|contact|"
    r"faq|magasins|ordre-final|etat-de-la-commande)"
    r")"
    r".*/\d+[-/][^?#]*\.html$",
    re.I,
)

NON_PRODUCT_PATH_PARTS = (
    "/content/",
    "/search",
    "/recherche",
    "/login",
    "/mon-compte",
    "/panier",
    "/cart",
    "/contact",
    "/faq",
    "/magasins",
)

MAX_PAGES = 140
MAX_CANDIDATES = 30


def _clean(value):
    return re.sub(
        r"\s+",
        " ",
        html_lib.unescape(str(value or "")),
    ).strip()


def _norm(value):
    value = unicodedata.normalize("NFKD", _clean(value))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value).strip().lower()


def _tokens(query):
    return [
        token
        for token in re.split(r"[^a-z0-9]+", _norm(query))
        if len(token) > 1
    ]


def _score(query, text):
    tokens = _tokens(query)
    haystack = _norm(text)
    if not tokens:
        return 0.0
    return sum(token in haystack for token in tokens) / len(tokens)


def _clean_url(url):
    absolute = urljoin(BASE, str(url or ""))
    p = urlsplit(absolute)
    return urlunsplit(
        (
            p.scheme.lower(),
            p.netloc.lower(),
            p.path,
            p.query,
            "",
        )
    )


def _internal(url):
    try:
        return urlsplit(url).netloc.lower() in {
            "sabina.com",
            "www.sabina.com",
        }
    except Exception:
        return False


def _is_product_url(url):
    if not _internal(url):
        return False

    p = urlsplit(url)
    path = p.path.lower()

    if not path.startswith("/fr/"):
        return False

    if any(part in path for part in NON_PRODUCT_PATH_PARTS):
        return False

    return bool(PRODUCT_PATH_RE.match(path))


def _price(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".replace(".", ",") + " €"

    text = _clean(value)
    match = PRICE_RE.search(text)

    if not match:
        match = re.search(
            r"(?<!\d)(\d{1,5}(?:[.,]\d{2}))(?!\d)",
            text,
        )

    if not match:
        return None

    return match.group(1).replace(".", ",") + " €"


def _card_name(card):
    candidates = []

    for attr in ("title", "aria-label", "data-product-name", "data-name"):
        value = card.get(attr)
        if value:
            candidates.append(value)

    for selector in (
        ".product-name",
        ".product-title",
        ".name",
        ".product-meta",
        "h1",
        "h2",
        "h3",
        "h4",
    ):
        for element in card.select(selector):
            text = _clean(element.get_text(" ", strip=True))
            if text:
                candidates.append(text)

    for link in card.find_all("a", href=True):
        text = _clean(link.get_text(" ", strip=True))
        if text:
            candidates.append(text)

        for attr in ("title", "aria-label"):
            value = link.get(attr)
            if value:
                candidates.append(value)

    # Prefer the shortest meaningful candidate that is not just a price/UI label.
    cleaned = []
    for value in candidates:
        value = _clean(value)
        if not value:
            continue
        if PRICE_RE.fullmatch(value):
            continue
        if value.lower() in {
            "ajouter au panier",
            "acquista",
            "acheter",
            "voir",
            "voir le produit",
            "image",
        }:
            continue
        cleaned.append(value)

    if not cleaned:
        return ""

    # Product names are normally compact. Avoid returning the whole card text.
    cleaned.sort(key=lambda x: (len(x), x))
    return cleaned[0]


def _card_price(card):
    # First use explicit price-related attributes when available.
    for attr in (
        "data-price",
        "data-product-price",
        "data-final-price",
        "content",
    ):
        value = card.get(attr)
        price = _price(value)
        if price:
            return price

    text = _clean(card.get_text(" ", strip=True))
    return _price(text)


def _extract_product_cards(soup, base_url):
    """
    Extract product cards generically from Sabina's HTML.

    The parser does not depend on one specific CSS class. It recognizes
    product-card/container markers and then extracts product URLs, names
    and prices from the card itself.
    """
    cards = []
    seen = set()

    marker_re = re.compile(
        r"(?:product|produit|article|item|catalog|ajax_block_product|"
        r"go_click_product_link|product-container|product-meta)",
        re.I,
    )

    # Prefer actual semantic/product containers, then fall back to any
    # element carrying a product-related marker.
    for node in soup.find_all(["article", "li", "div"]):
        attrs = " ".join(
            str(node.get(attr, ""))
            for attr in (
                "id",
                "class",
                "data-product-id",
                "data-id",
                "data-product-url",
                "data-url",
                "data-href",
                "data-product-name",
            )
        )

        if not marker_re.search(attrs):
            continue

        product_urls = []

        for link in node.find_all("a", href=True):
            url = _clean_url(urljoin(base_url, link["href"]))
            if _is_product_url(url):
                product_urls.append(url)

        for attr in ("data-product-url", "data-url", "data-href"):
            value = node.get(attr)
            if value:
                url = _clean_url(urljoin(base_url, value))
                if _is_product_url(url):
                    product_urls.append(url)

        product_urls = list(dict.fromkeys(product_urls))

        if not product_urls:
            continue

        # Keep the smallest useful product container. Very large ancestors
        # can contain dozens of products and would produce false matches.
        text = _clean(node.get_text(" ", strip=True))
        if not text or len(text) > 2500:
            continue

        name = _card_name(node)
        price = _card_price(node)

        for product_url in product_urls:
            key = (product_url, name, price)
            if key in seen:
                continue
            seen.add(key)
            cards.append(
                {
                    "url": product_url,
                    "name": name,
                    "price": price,
                    "text": text,
                }
            )

    return cards


def _extract_anchor_products(soup, base_url):
    """
    Secondary generic extraction from normal anchors.

    This catches product links when Sabina changes its card wrappers.
    """
    rows = []
    seen = set()

    for link in soup.find_all("a", href=True):
        url = _clean_url(urljoin(base_url, link["href"]))
        if not _is_product_url(url):
            continue

        # Walk up only a limited number of levels to find the price/name
        # belonging to this product, without swallowing the whole page.
        container = link
        for _ in range(8):
            parent = getattr(container, "parent", None)
            if parent is None:
                break

            container = parent
            text = _clean(container.get_text(" ", strip=True))

            if PRICE_RE.search(text) and len(text) <= 1800:
                break

        text = _clean(container.get_text(" ", strip=True))
        price = _price(text)

        name_candidates = [
            link.get("title"),
            link.get("aria-label"),
            _clean(link.get_text(" ", strip=True)),
        ]

        for selector in (
            ".product-name",
            ".product-title",
            ".name",
            "h1",
            "h2",
            "h3",
            "h4",
        ):
            element = container.select_one(selector)
            if element:
                name_candidates.append(
                    _clean(element.get_text(" ", strip=True))
                )

        names = [
            value
            for value in (_clean(x) for x in name_candidates)
            if value
        ]

        name = min(names, key=len, default="")

        key = (url, name, price)
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            {
                "url": url,
                "name": name,
                "price": price,
                "text": text,
            }
        )

    return rows


def _extract_pagination(soup, base_url):
    """
    Follow Sabina's own pagination graph.

    Supports both ?p=N and ?page=N and navigation labels.
    """
    pages = []
    seen = set()

    for link in soup.find_all("a", href=True):
        url = _clean_url(urljoin(base_url, link["href"]))

        if not _internal(url) or url in seen:
            continue

        parsed = urlsplit(url)
        query = parse_qs(parsed.query)

        is_page = (
            any(key in query for key in ("p", "page"))
            and any(
                str(value[0]).isdigit()
                for key, value in query.items()
                if value
            )
        )

        text = _norm(link.get_text(" ", strip=True))
        is_navigation = any(
            marker in text
            for marker in (
                "suivant",
                "next",
                "siguiente",
                "prochaine",
                "precedent",
                "précédent",
            )
        )

        if is_page or is_navigation:
            seen.add(url)
            pages.append(url)

    return pages


def _extract_jsonld_products(soup, base_url):
    rows = []

    def walk(value):
        if isinstance(value, dict):
            typ = value.get("@type")
            is_product = (
                typ == "Product"
                or (
                    isinstance(typ, list)
                    and "Product" in typ
                )
            )

            if is_product:
                name = _clean(value.get("name"))
                url = value.get("url")
                if isinstance(url, str):
                    url = _clean_url(urljoin(base_url, url))

                offers = value.get("offers")
                price = None

                if isinstance(offers, dict):
                    price = _price(
                        offers.get("price")
                        or offers.get("lowPrice")
                    )
                elif isinstance(offers, list):
                    for offer in offers:
                        if isinstance(offer, dict):
                            price = _price(
                                offer.get("price")
                                or offer.get("lowPrice")
                            )
                            if price:
                                break

                if (
                    name
                    and isinstance(url, str)
                    and _is_product_url(url)
                ):
                    rows.append(
                        {
                            "url": url,
                            "name": name,
                            "price": price,
                            "text": name,
                        }
                    )

            for child in value.values():
                walk(child)

        elif isinstance(value, list):
            for child in value:
                walk(child)

    for script in soup.find_all(
        "script",
        type=lambda value: value and "ld+json" in value,
    ):
        try:
            data = json.loads(script.get_text())
        except Exception:
            continue
        walk(data)

    return rows


def _fetch(session, url):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        content_type = (
            response.headers.get("content-type") or ""
        ).lower()

        if response.status_code in (403, 429):
            print(
                f"SABINA: BLOCKED status={response.status_code} "
                f"url={url}"
            )
            response.close()
            return None, None

        if response.status_code != 200:
            response.close()
            return None, None

        if "text/html" not in content_type:
            response.close()
            return None, None

        final_url = response.url
        text = response.text
        response.close()
        return final_url, text

    except requests.RequestException as exc:
        print(
            f"SABINA: FETCH_ERROR url={url} "
            f"error={type(exc).__name__}: {exc}"
        )
        return None, None


def _parse_page(html, base_url, query):
    soup = BeautifulSoup(html, "html.parser")

    cards = _extract_product_cards(soup, base_url)
    anchors = _extract_anchor_products(soup, base_url)
    jsonld = _extract_jsonld_products(soup, base_url)
    pages = _extract_pagination(soup, base_url)

    # Merge evidence from all generic HTML structures.
    merged = []
    seen_urls = set()

    for row in cards + anchors + jsonld:
        url = row.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        merged.append(row)

    matching = []

    for row in merged:
        haystack = " ".join(
            [
                row.get("name") or "",
                row.get("text") or "",
                row.get("url") or "",
            ]
        )

        score = _score(query, haystack)

        if score >= 1.0:
            matching.append(
                {
                    **row,
                    "score": score,
                }
            )

    return merged, matching, pages


def _extract_product_title(soup):
    for selector in (
        "h1",
        ".product-name",
        ".product-title",
        "meta[property='og:title']",
        "title",
    ):
        element = soup.select_one(selector)
        if not element:
            continue

        if element.name == "meta":
            value = element.get("content")
        else:
            value = element.get_text(" ", strip=True)

        value = _clean(value)

        if value:
            return value

    return ""


def _extract_product_price(soup):
    # Prefer structured product/offer information.
    for script in soup.find_all(
        "script",
        type=lambda value: value and "ld+json" in value,
    ):
        try:
            data = json.loads(script.get_text())
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            value = stack.pop()

            if isinstance(value, list):
                stack.extend(value)
                continue

            if not isinstance(value, dict):
                continue

            typ = value.get("@type")
            if typ == "Product" or (
                isinstance(typ, list)
                and "Product" in typ
            ):
                offers = value.get("offers")

                if isinstance(offers, dict):
                    price = _price(
                        offers.get("price")
                        or offers.get("lowPrice")
                    )
                    if price:
                        return price

                if isinstance(offers, list):
                    for offer in offers:
                        if isinstance(offer, dict):
                            price = _price(
                                offer.get("price")
                                or offer.get("lowPrice")
                            )
                            if price:
                                return price

            for child in value.values():
                if isinstance(child, (dict, list)):
                    stack.append(child)

    # Generic visible-page fallback.
    text = _clean(soup.get_text(" ", strip=True))
    return _price(text)


def _verify_candidates(session, query, candidates):
    results = []
    seen = set()

    # Verify strongest candidates first.
    candidates = sorted(
        candidates,
        key=lambda row: (
            row.get("score", 0.0),
            bool(row.get("price")),
        ),
        reverse=True,
    )

    for candidate in candidates[:MAX_CANDIDATES]:
        url = candidate.get("url")
        if not url or url in seen:
            continue
        seen.add(url)

        final_url, html = _fetch(session, url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        title = _extract_product_title(soup)

        if not title:
            continue

        # Final validation is performed against the actual product title,
        # not the category/card text.
        score = _score(query, title)

        if score < 1.0:
            continue

        price = _extract_product_price(soup)
        if not price:
            price = _price(candidate.get("price"))

        if not price:
            continue

        results.append(
            {
                "store": STORE,
                "name": title,
                "price": price,
                "url": final_url,
            }
        )

    return _dedupe(results, query)


def _dedupe(rows, query):
    tokens = _tokens(query)
    out = []
    seen = set()

    for row in rows:
        name = _clean(row.get("name"))
        url = _clean_url(row.get("url"))
        price = _price(row.get("price"))

        if not name or not url or not price:
            continue

        # Final generic name validation.
        normalized_name = _norm(name)
        if tokens and not all(
            token in normalized_name
            for token in tokens
        ):
            continue

        key = (
            normalized_name,
            urlsplit(url).path.lower(),
        )

        if key in seen:
            continue

        seen.add(key)

        out.append(
            {
                "store": STORE,
                "name": name,
                "price": price,
                "url": url.split("#")[0],
            }
        )

    return out


def search(query):
    query = _clean(query)

    if not query:
        return []

    print(f"SABINA: START query={query!r}")

    session = requests.Session()
    session.headers.update(HEADERS)

    queue = deque(ROOTS)
    queued = set(ROOTS)
    visited = set()
    candidates = []

    try:
        # Generic category discovery. No product-specific seed is used.
        while queue and len(visited) < MAX_PAGES:
            url = queue.popleft()

            if url in visited:
                continue

            visited.add(url)

            final_url, html = _fetch(session, url)
            if not html:
                continue

            rows, matching, pages = _parse_page(
                html,
                final_url,
                query,
            )

            if rows:
                print(
                    f"SABINA: PAGE visited={len(visited)} "
                    f"products={len(rows)} "
                    f"matches={len(matching)} "
                    f"pagination={len(pages)} "
                    f"url={final_url}"
                )

            for candidate in matching:
                if not any(
                    existing.get("url") == candidate.get("url")
                    for existing in candidates
                ):
                    candidates.append(candidate)

            # Keep following the site's own pagination graph.
            for page in pages:
                if (
                    page not in visited
                    and page not in queued
                ):
                    queued.add(page)
                    queue.append(page)

            # Once we have matching product cards, verification is enough.
            # We do not continue crawling unrelated pages unnecessarily.
            if candidates:
                break

        print(
            f"SABINA: DISCOVERY_DONE visited={len(visited)} "
            f"queued={len(queue)} candidates={len(candidates)}"
        )

        results = _verify_candidates(
            session,
            query,
            candidates,
        )

        print(
            f"SABINA: VERIFIED_RESULTS={len(results)}"
        )

        return results

    finally:
        session.close()


# Compatibility aliases used by ScentHunter.
def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]).strip() or "Dior"
    data = search(q)
    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
    )
