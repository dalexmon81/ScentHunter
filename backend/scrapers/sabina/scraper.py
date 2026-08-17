import re
import json
import html as html_lib
import unicodedata
from collections import deque
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qs, urlencode, quote_plus

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 10

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

# Generic catalog fallbacks only. They are not product seeds.
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

MAX_SEARCH_PAGES = 12
MAX_FALLBACK_PAGES = 36
MAX_CANDIDATES = 40

PRICE_RE = re.compile(r"(?<!\d)(\d{1,5}(?:[.,]\d{2}))\s*(?:€|EUR)\b", re.I)

# Sabina product URLs have a numeric product id and a .html slug.
PRODUCT_RE = re.compile(
    r"^/[a-z]{2}/(?!content/|search|recherche|login|mon-compte|panier|cart|"
    r"contact|faq|magasins|ordre-final|etat-de-la-commande)"
    r".*/\d+-[^/?#]+\.html$",
    re.I,
)


def _clean(value):
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


def _norm(value):
    value = unicodedata.normalize("NFKD", _clean(value))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value).lower().strip()


def _tokens(query):
    return [x for x in re.split(r"[^a-z0-9]+", _norm(query)) if len(x) > 1]


def _score(query, text):
    tokens = _tokens(query)
    value = _norm(text)
    if not tokens:
        return 0.0
    return sum(token in value for token in tokens) / len(tokens)


def _clean_url(url):
    absolute = urljoin(BASE, str(url or ""))
    p = urlsplit(absolute)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, ""))


def _internal(url):
    try:
        return urlsplit(url).netloc.lower() in {"sabina.com", "www.sabina.com"}
    except Exception:
        return False


def _is_product_url(url):
    if not _internal(url):
        return False
    return bool(PRODUCT_RE.match(urlsplit(url).path))


def _price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".replace(".", ",") + " €"
    text = _clean(value)
    match = PRICE_RE.search(text)
    if not match:
        return None
    return match.group(1).replace(".", ",") + " €"


def _fetch(session, url):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        content_type = (response.headers.get("content-type") or "").lower()

        if response.status_code in (403, 429):
            print(f"SABINA: BLOCKED status={response.status_code} url={url}")
            response.close()
            return None, None

        if response.status_code != 200 or "text/html" not in content_type:
            response.close()
            return None, None

        final_url = response.url
        body = response.text
        response.close()
        return final_url, body

    except requests.RequestException as exc:
        print(f"SABINA: FETCH_ERROR url={url} error={type(exc).__name__}: {exc}")
        return None, None


def _product_name_from_link(link):
    for attr in ("title", "aria-label", "data-product-name", "data-name"):
        value = _clean(link.get(attr))
        if value:
            return value

    text = _clean(link.get_text(" ", strip=True))
    if text and text.lower() not in {
        "ajouter au panier", "acheter", "voir", "voir le produit"
    }:
        return text

    return ""


def _extract_product_links(soup, base_url):
    """
    Deliberately simple discovery:
    identify real product URLs first, then use only the anchor/product
    element itself for identity. Never score an entire ancestor/card.
    """
    rows = []
    seen = set()

    for link in soup.find_all("a", href=True):
        url = _clean_url(urljoin(base_url, link["href"]))
        if not _is_product_url(url):
            continue

        name = _product_name_from_link(link)

        # A small local container is used only for price extraction.
        # It is never used for query matching.
        price = None
        node = link
        for _ in range(5):
            node = getattr(node, "parent", None)
            if node is None:
                break
            local_text = _clean(node.get_text(" ", strip=True))
            if local_text and len(local_text) <= 1200:
                price = _price(local_text)
                if price:
                    break

        key = (url, name)
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "url": url,
            "name": name,
            "price": price,
        })

    return rows


def _extract_jsonld_products(soup, base_url):
    rows = []
    seen = set()

    def walk(value):
        if isinstance(value, dict):
            typ = value.get("@type")
            is_product = typ == "Product" or (
                isinstance(typ, list) and "Product" in typ
            )
            if is_product:
                url = value.get("url")
                name = _clean(value.get("name"))
                if isinstance(url, str):
                    url = _clean_url(urljoin(base_url, url))
                else:
                    url = ""

                offers = value.get("offers")
                price = None
                if isinstance(offers, dict):
                    price = _price(offers.get("price") or offers.get("lowPrice"))
                elif isinstance(offers, list):
                    for offer in offers:
                        if isinstance(offer, dict):
                            price = _price(
                                offer.get("price") or offer.get("lowPrice")
                            )
                            if price:
                                break

                if name and _is_product_url(url):
                    key = (url, name)
                    if key not in seen:
                        seen.add(key)
                        rows.append({
                            "url": url,
                            "name": name,
                            "price": price,
                        })

            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)

        elif isinstance(value, list):
            for child in value:
                walk(child)

    for script in soup.find_all(
        "script",
        type=lambda value: value and "ld+json" in value,
    ):
        try:
            walk(json.loads(script.get_text()))
        except Exception:
            continue

    return rows


def _extract_pagination(soup, base_url):
    pages = []
    seen = set()

    for link in soup.find_all("a", href=True):
        url = _clean_url(urljoin(base_url, link["href"]))
        if not _internal(url) or url in seen:
            continue

        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        page_value = None

        for key in ("p", "page"):
            values = query.get(key)
            if values and values[0].isdigit():
                page_value = int(values[0])
                break

        text = _norm(link.get_text(" ", strip=True))
        navigation = any(
            x in text
            for x in ("suivant", "next", "prochaine", "precedent", "précédent")
        )

        if page_value is not None or navigation:
            seen.add(url)
            pages.append(url)

    return pages


def _search_form_urls(soup, query):
    urls = []
    encoded = quote_plus(query)

    for form in soup.find_all("form"):
        action = _clean_url(urljoin(BASE, form.get("action") or "/fr/recherche"))
        method = (form.get("method") or "get").lower()

        if method != "get" or not _internal(action):
            continue

        inputs = form.find_all("input")
        names = {
            (item.get("name") or "").strip().lower()
            for item in inputs
        }

        # Search forms commonly use s, search_query or q.
        if not names.intersection({"s", "search_query", "q", "query"}):
            continue

        params = {}
        for item in inputs:
            name = (item.get("name") or "").strip()
            if name and item.get("value") is not None:
                params[name] = item.get("value")

        key = next(
            (x for x in ("s", "search_query", "q", "query") if x in names),
            "s",
        )
        params[key] = query

        separator = "&" if "?" in action else "?"
        urls.append(action + separator + urlencode(params))

    # Generic PrestaShop-style search fallbacks. These contain only the
    # current query; no product/brand URL is embedded.
    for path, params in (
        ("/fr/recherche", {"controller": "search", "s": query}),
        ("/fr/recherche", {"s": query}),
        ("/fr/search", {"s": query}),
    ):
        url = BASE + path + "?" + urlencode(params)
        if url not in urls:
            urls.append(url)

    return urls


def _discover_search_urls(session, query):
    # One homepage fetch is enough to learn the site's real search form.
    final_url, html = _fetch(session, BASE + "/fr/")
    if not html:
        return [
            BASE + "/fr/recherche?controller=search&" + urlencode({"s": query})
        ]

    soup = BeautifulSoup(html, "html.parser")
    urls = _search_form_urls(soup, query)

    print(f"SABINA: SEARCH_URLS={len(urls)}")
    for url in urls:
        print(f"SABINA: SEARCH_URL {url}")

    return urls


def _match_row(query, row):
    name = _norm(row.get("name"))
    path = urlsplit(row.get("url") or "").path
    slug = re.sub(r"[-_]+", " ", path.rsplit("/", 1)[-1])
    slug = re.sub(r"\.html$", "", slug, flags=re.I)

    # Identity matching is ONLY name + URL slug.
    name_score = _score(query, name)
    slug_score = _score(query, slug)

    return max(name_score, slug_score)


def _parse_page(html, base_url, query):
    soup = BeautifulSoup(html, "html.parser")

    rows = _extract_product_links(soup, base_url)
    jsonld = _extract_jsonld_products(soup, base_url)

    merged = []
    seen = set()

    for row in rows + jsonld:
        url = row.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(row)

    matches = []
    for row in merged:
        score = _match_row(query, row)
        if score >= 1.0:
            matches.append({**row, "score": score})

    return merged, matches, _extract_pagination(soup, base_url)


def _extract_product_title(soup):
    # Sabina's real product pages expose the product identity in h1.
    for selector in (
        "h1",
        "meta[property='og:title']",
        ".product-name",
        ".product-title",
        "title",
    ):
        element = soup.select_one(selector)
        if not element:
            continue

        value = (
            element.get("content")
            if element.name == "meta"
            else element.get_text(" ", strip=True)
        )
        value = _clean(value)
        if value:
            return value

    return ""


def _extract_product_price(soup):
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
                isinstance(typ, list) and "Product" in typ
            ):
                offers = value.get("offers")
                if isinstance(offers, dict):
                    price = _price(
                        offers.get("price") or offers.get("lowPrice")
                    )
                    if price:
                        return price
                elif isinstance(offers, list):
                    for offer in offers:
                        if isinstance(offer, dict):
                            price = _price(
                                offer.get("price") or offer.get("lowPrice")
                            )
                            if price:
                                return price

            for child in value.values():
                if isinstance(child, (dict, list)):
                    stack.append(child)

    # Product pages contain a visible current price. This is only a
    # verification fallback; it is never used for query matching.
    return _price(soup.get_text(" ", strip=True))


def _verify_candidates(session, query, candidates):
    results = []
    seen = set()

    for candidate in sorted(
        candidates,
        key=lambda x: (x.get("score", 0), bool(x.get("price"))),
        reverse=True,
    )[:MAX_CANDIDATES]:

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

        # Final decision uses the real product title.
        if _score(query, title) < 1.0:
            continue

        price = _extract_product_price(soup) or _price(candidate.get("price"))
        if not price:
            continue

        results.append({
            "store": STORE,
            "name": title,
            "price": price,
            "url": final_url,
        })

    return _dedupe(results, query)


def _dedupe(rows, query):
    tokens = _tokens(query)
    output = []
    seen = set()

    for row in rows:
        name = _clean(row.get("name"))
        url = _clean_url(row.get("url"))
        price = _price(row.get("price"))

        if not name or not url or not price:
            continue

        normalized = _norm(name)
        if tokens and not all(token in normalized for token in tokens):
            continue

        key = (normalized, urlsplit(url).path.lower())
        if key in seen:
            continue
        seen.add(key)

        output.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": url.split("#")[0],
        })

    return output


def _search_direct(session, query):
    candidates = []
    visited = set()
    queue = deque(_discover_search_urls(session, query))

    while queue and len(visited) < MAX_SEARCH_PAGES:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        final_url, html = _fetch(session, url)
        if not html:
            continue

        rows, matches, pages = _parse_page(html, final_url, query)
        print(
            f"SABINA: SEARCH_PAGE {len(visited)}/{MAX_SEARCH_PAGES} "
            f"products={len(rows)} matches={len(matches)} "
            f"pagination={len(pages)} url={final_url}"
        )

        for row in matches:
            if not any(x.get("url") == row.get("url") for x in candidates):
                candidates.append(row)

        # Follow only pagination belonging to the search result graph.
        for page in pages:
            if page not in visited and page not in queue:
                queue.append(page)

        # A real full-token match is enough to move immediately to product
        # verification. We do not crawl unrelated search pages after that.
        if candidates:
            break

    return candidates


def _search_catalog_fallback(session, query):
    """
    Last-resort generic discovery. This exists only for sites where the
    search endpoint is unavailable. It is deliberately bounded and follows
    the site's own pagination; it does not seed any product.
    """
    queue = deque(ROOTS)
    visited = set()
    candidates = []

    while queue and len(visited) < MAX_FALLBACK_PAGES:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        final_url, html = _fetch(session, url)
        if not html:
            continue

        rows, matches, pages = _parse_page(html, final_url, query)

        if rows or matches:
            print(
                f"SABINA: FALLBACK_PAGE {len(visited)}/{MAX_FALLBACK_PAGES} "
                f"products={len(rows)} matches={len(matches)} url={final_url}"
            )

        for row in matches:
            if not any(x.get("url") == row.get("url") for x in candidates):
                candidates.append(row)

        for page in pages:
            if page not in visited and page not in queue:
                queue.append(page)

        if candidates:
            break

    return candidates


def search(query):
    query = _clean(query)
    if not query:
        return []

    print(f"SABINA: START query={query!r}")
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # Same high-level philosophy as the working scrapers:
        # discovery first, verification second.
        candidates = _search_direct(session, query)
        print(f"SABINA: DIRECT_DISCOVERY candidates={len(candidates)}")

        if not candidates:
            candidates = _search_catalog_fallback(session, query)
            print(f"SABINA: FALLBACK_DISCOVERY candidates={len(candidates)}")

        results = _verify_candidates(session, query, candidates)
        print(f"SABINA: VERIFIED_RESULTS={len(results)}")
        return results

    finally:
        session.close()


def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]).strip() or "Dior"
    print(json.dumps(search(query), ensure_ascii=False, indent=2))
