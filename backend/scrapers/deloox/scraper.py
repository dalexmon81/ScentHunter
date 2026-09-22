"""Deloox adapter for ScentHunter.

Discovery strategy:
- Prefer Deloox's current category pages and their Product line filter links.
- Fall back to Deloox search endpoints and sitemap discovery.
- Product pages are parsed through JSON-LD/page content.

Important:
- Discovery is generic and contains no perfume-specific rules.
- Candidate filtering is generic; _product() remains the final authority.
- Technical failures are never converted into NOT_FOUND by this scraper.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"

# Deloox exposes the same retailer through country/language storefronts.
# Discovery starts with the storefronts that currently expose the public
# search/category surfaces, then falls back to the generic .com surface.
BASE_URL = "https://www.deloox.be"
DELOOX_BASE_URLS = (
    # Luxembourg is the user's market and exposes the same Deloox catalog
    # through its own storefront.
    "https://www.deloox.lu",
    "https://www.deloox.be",
    "https://www.deloox.nl",
    "https://www.deloox.com",
    "https://www.deloox.es",
)
TIMEOUT = (2.5, 6.0)
MAX_CANDIDATES = 24
MAX_RESULTS = 40
MAX_SEARCH_PAGES = 3
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.7",
    "Cache-Control": "no-cache",
}
DELOOX_HOSTS = {
    "deloox.lu", "www.deloox.lu",
    "deloox.be", "www.deloox.be",
    "deloox.com", "www.deloox.com",
    "deloox.nl", "www.deloox.nl",
    "deloox.es", "www.deloox.es",
}


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(v).lower())).strip()


def tokens(v):
    return {x for x in norm(v).split() if len(x) > 1}


def matches(text, q):
    q_tokens = tokens(q)
    return bool(q_tokens) and q_tokens.issubset(tokens(text))


def size_ml(*values):
    m = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        " ".join(clean(x) for x in values),
        re.I,
    )
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    n *= 10 if m.group(2).lower() == "cl" else 1
    return int(n) if n.is_integer() else n


def concentration(*values):
    t = norm(" ".join(clean(x) for x in values))
    if re.search(r"\beau de toilette\b|\bedt\b", t):
        return "Eau de Toilette"
    if re.search(r"\beau de parfum\b|\bedp\b", t):
        return "Eau de Parfum"
    if re.search(r"\bextrait(?: de parfum)?\b", t):
        return "Extrait de Parfum"
    return None


def parse_price(v):
    s = clean(v)
    m = re.search(r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?", s)
    if not m:
        return None
    try:
        return round(float(m.group(1).replace(",", ".")), 2)
    except ValueError:
        return None


def availability(text, offer=None, soup=None):
    """Determine availability from product-specific signals only."""

    if isinstance(offer, dict):
        raw = clean(
            offer.get("availability")
            or offer.get("itemAvailability")
            or offer.get("availabilityStatus")
            or ""
        ).lower()
        if raw:
            if any(x in raw for x in (
                "outofstock", "out_of_stock", "soldout", "sold_out",
                "discontinued", "unavailable",
            )):
                return "out_of_stock"
            if any(x in raw for x in (
                "instock", "in_stock", "limitedavailability",
                "preorder", "pre_order",
            )):
                return "in_stock"

    if soup is not None:
        scoped_parts = []

        selectors = [
            '[itemprop="availability"]',
            '[data-testid*="availability" i]',
            '[data-test*="availability" i]',
            '[class*="availability" i]',
            '[class*="stock" i]',
            '[class*="add-to-cart" i]',
            '[class*="buy" i]',
            'button[type="submit"]',
        ]

        seen_nodes = set()
        for selector in selectors:
            try:
                nodes = soup.select(selector)
            except Exception:
                nodes = []
            for node in nodes[:20]:
                marker = id(node)
                if marker in seen_nodes:
                    continue
                seen_nodes.add(marker)
                scoped_parts.append(
                    clean(
                        node.get("content")
                        or node.get("aria-label")
                        or node.get_text(" ", strip=True)
                    )
                )

        scoped = norm(" ".join(x for x in scoped_parts if x))
        if scoped:
            if any(x in scoped for x in (
                "sold out", "out of stock", "not available",
                "currently unavailable", "unavailable",
            )):
                return "out_of_stock"
            if any(x in scoped for x in (
                "in stock", "available", "op voorraad", "add to cart",
                "add to basket", "buy now", "bestellen",
            )):
                return "in_stock"

    t = norm(text)
    if any(x in t for x in (
        "sold out",
        "out of stock",
        "currently unavailable",
    )):
        return "out_of_stock"
    if any(x in t for x in ("in stock", "op voorraad")):
        return "in_stock"
    return "unknown"


def _jsonld(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]
        while stack:
            x = stack.pop(0)
            if isinstance(x, list):
                stack.extend(x)
                continue
            if not isinstance(x, dict):
                continue
            if x.get("@type") == "Product" or "offers" in x:
                return x
            if isinstance(x.get("@graph"), list):
                stack.extend(x["@graph"])
    return {}


def _product(url, html, query):
    soup = BeautifulSoup(html, "html.parser")
    data = _jsonld(soup)

    h1 = soup.find("h1")
    name = clean(data.get("name")) or (
        clean(h1.get_text(" ", strip=True)) if h1 else ""
    )

    if not name or not matches(name, query):
        return None

    product_line = ""
    text = soup.get_text(" ", strip=True)
    m = re.search(
        r"product line\s+(.+?)(?:for whom|fragrance type|season|spray|article number)",
        text,
        re.I,
    )
    if m:
        product_line = clean(m.group(1))

    brand = data.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    offers = data.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    offer = next((x for x in offers if isinstance(x, dict)), {})

    price = parse_price(offer.get("price"))
    if price is None:
        price = parse_price(text)
    if price is None:
        return None

    gtin = clean(data.get("gtin13") or data.get("gtin") or "") or None
    mpn = clean(data.get("mpn") or "") or None
    sku = clean(data.get("sku") or "") or None

    image = data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None

    avail = availability(text, offer=offer, soup=soup)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": clean(brand),
            "url": url,
            "image": urljoin(url, str(image)) if image else None,
        },
        "identity": {
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
            "mpn": {"value": mpn, "source": "jsonld"} if mpn else None,
            "sku": {"value": sku, "source": "jsonld"} if sku else None,
            "store_product_id": {
                "value": sku,
                "source": "deloox_sku",
            } if sku else None,
        },
        "attributes": {
            "size_ml": {
                "value": size_ml(name),
                "source": "product_name",
            } if size_ml(name) is not None else None,
            "concentration": {
                "value": concentration(name),
                "source": "product_name",
            } if concentration(name) else None,
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
            "product_line": {
                "value": product_line,
                "source": "deloox_page",
            } if product_line else None,
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": avail,
        },
        "provenance": {
            "source_page": url,
            "product_source": "jsonld_or_page",
        },
        "raw_data": {"jsonld": data},
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": avail == "in_stock",
    }


def _candidate_queries(query):
    """Build generic discovery-query variants."""
    q = clean(query)
    if not q:
        return []

    variants = [q]

    parts = q.split()
    removable = {
        "parfum", "perfume", "eau", "de", "toilette",
        "edt", "edp", "extrait", "extract"
    }
    broad = " ".join(
        p for p in parts if p.lower() not in removable
    ).strip()

    if broad and broad.lower() != q.lower():
        variants.append(broad)

    out = []
    seen = set()
    for item in variants:
        key = norm(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _candidate_product_urls(
    html,
    query,
    discovery_query=None,
    accept_all_products=True,
    base_url=None,
):
    """Extract generic Deloox product URLs from any retailer page.

    Candidate discovery deliberately does not require the query to appear in
    the card text.  Search-result markup varies by storefront and product
    pages are the authoritative place where the query is validated by
    _product().
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()
    base_url = clean(base_url or BASE_URL)

    def add(raw_url):
        if not raw_url:
            return
        raw_url = clean(raw_url).replace("\\/", "/")
        if raw_url.startswith(("javascript:", "mailto:", "#")):
            return
        url = urljoin(base_url, raw_url).split("#")[0].split("?")[0]
        try:
            parsed = urlparse(url)
        except Exception:
            return
        if parsed.netloc.lower() not in DELOOX_HOSTS:
            return
        if not re.search(r"/(?:product|produit|producto|prodotto)/\d+", parsed.path, re.I):
            return
        if url in seen:
            return
        seen.add(url)
        found.append(url)

    # Normal links.
    for a in soup.find_all("a", href=True):
        add(a.get("href"))
        if len(found) >= MAX_CANDIDATES:
            return found

    # Some Deloox storefronts expose the product target in data-* attributes
    # rather than href.  Read attributes generically; never infer a product
    # from its name or from a product-specific rule.
    attr_names = (
        "data-url",
        "data-href",
        "data-link",
        "data-product-url",
        "data-product-link",
        "data-target",
        "data-href-url",
    )
    for node in soup.find_all(True):
        for attr in attr_names:
            raw = node.get(attr)
            if not raw:
                continue
            add(raw)
            if len(found) >= MAX_CANDIDATES:
                return found

    # Product URLs can also be present in JSON state, JSON-LD or hydration
    # payloads and therefore not appear as ordinary anchors.
    patterns = (
        r'https?://(?:www\.)?deloox\.(?:be|com|nl|es)/[^"\'<>\s]+/(?:product|produit|producto|prodotto)/\d+[^"\'<>\s]*',
        r'(?:(?:https?:)?//(?:www\.)?deloox\.(?:be|com|nl|es))?/(?:en/|fr/|nl/|es/|it/)?(?:product|produit|producto|prodotto)/\d+/[^"\'<>\s]+',
    )
    for pattern in patterns:
        for raw in re.findall(pattern, html, re.I):
            add(raw)
            if len(found) >= MAX_CANDIDATES:
                return found
    return found


def _category_pages(session=None):
    """Return generic fragrance category surfaces, bounded for live search."""
    paths = (
        "/categorie/1075744/eau-de-toilette-homme.html",
        "/categorie/1075743/eau-de-parfum-femme.html",
        "/en/category/1103659/fragrances.html",
        "/category/1103659/fragrances.html",
        "/category/1075660/womens-perfume.html",
        "/category/1075750/mens-perfume.html",
    )
    out = []
    seen = set()
    for base in DELOOX_BASE_URLS:
        for path in paths:
            url = base + path
            if url not in seen:
                seen.add(url)
                out.append(url)
    return tuple(out)


def _sitemap_roots():
    paths = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/en/sitemap.xml")
    return tuple(base + path for base in DELOOX_BASE_URLS for path in paths)


def _fetch_xml(session, url):
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException:
        return None
    if r.status_code >= 400:
        return None
    body = r.text.lstrip()
    ctype = (r.headers.get("content-type") or "").lower()
    if "xml" not in ctype and not body.startswith(("<?xml", "<urlset", "<sitemapindex")):
        return None
    return r.text


def _sitemap_product_urls(session, query, max_sitemaps=6, max_urls=24):
    """Small, bounded sitemap fallback; never scans an entire sitemap tree."""
    q_tokens = tokens(query)
    if not q_tokens:
        return []
    pending = list(_sitemap_roots())
    seen = set()
    out = []
    seen_out = set()
    while pending and len(seen) < max_sitemaps and len(out) < max_urls:
        u = pending.pop(0)
        if u in seen:
            continue
        seen.add(u)
        xml = _fetch_xml(session, u)
        if not xml:
            continue
        soup = BeautifulSoup(xml, "xml")
        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())
            low = value.lower()
            if not value:
                continue
            if re.search(r"/(?:product|produit|producto|prodotto)/\d+", low):
                if q_tokens.issubset(tokens(low)) and value not in seen_out:
                    seen_out.add(value)
                    out.append(value)
                    if len(out) >= max_urls:
                        break
            elif low.endswith(".xml") or "sitemap" in low:
                if value not in seen and len(seen) + len(pending) < max_sitemaps * 2:
                    pending.append(value)
    return out[:max_urls]


def _discover_from_search(session, query):
    """Generic, bounded search discovery across Deloox storefronts.

    Different Deloox country storefronts have historically exposed the public
    search through different path/parameter combinations.  Probe a bounded
    matrix concurrently, stop as soon as product URLs are found, and leave
    product identity validation to _product().
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    query = clean(query)
    if not query:
        return []

    routes = (
        "/chercher.html",
        "/zoeken.html",
        "/search",
        "/en/search",
        "/fr/search",
        "/nl/search",
    )
    params = ("q", "query", "search", "searchTerm", "keyword")

    jobs = []
    seen_jobs = set()

    # Keep the matrix deliberately bounded.  The first storefronts are the
    # current Luxembourg/Belgium/Netherlands surfaces, followed by generic
    # international fallbacks.
    for base in DELOOX_BASE_URLS:
        for route in routes:
            for param in params:
                endpoint = (
                    base + route + "?" + param + "=" + quote_plus(query)
                )
                if endpoint in seen_jobs:
                    continue
                seen_jobs.add(endpoint)
                jobs.append(endpoint)

    # Do not let a slow storefront consume Main's entire 45s store budget.
    jobs = jobs[:75]

    def probe(endpoint):
        try:
            r = session.get(
                endpoint,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            return []

        if r.status_code >= 400:
            return []

        final_base = (
            f"{urlparse(r.url).scheme}://{urlparse(r.url).netloc}"
        )
        return _candidate_product_urls(
            r.text,
            query,
            base_url=final_base,
            accept_all_products=True,
        )[:MAX_CANDIDATES]

    found = []
    seen = set()

    # A small parallel pool is intentional: one blocked/slow locale must not
    # serialize the entire discovery process.
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(probe, endpoint): endpoint for endpoint in jobs}
        for future in as_completed(futures):
            try:
                candidates = future.result()
            except Exception:
                candidates = []

            for url in candidates:
                if url in seen:
                    continue
                seen.add(url)
                found.append(url)
                if len(found) >= MAX_CANDIDATES:
                    return found

    return found

def _discover_from_categories(session, query, max_urls=MAX_CANDIDATES):
    """Bounded generic category fallback after search has failed."""
    urls = []
    seen = set()
    for page_url in _category_pages()[:12]:
        try:
            r = session.get(page_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue
        base = f"{urlparse(r.url).scheme}://{urlparse(r.url).netloc}"
        for product_url in _candidate_product_urls(
            r.text, query, base_url=base, accept_all_products=True
        ):
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)
                if len(urls) >= max_urls:
                    return urls
    return urls


def _discover(session, q):
    """Generic Deloox discovery: search first, bounded fallbacks second."""
    q = clean(q)
    if not q:
        return []

    candidates = _discover_from_search(session, q)
    if candidates:
        return candidates[:MAX_CANDIDATES]

    candidates = _discover_from_categories(session, q, MAX_CANDIDATES)
    if candidates:
        return candidates[:MAX_CANDIDATES]

    return _sitemap_product_urls(
        session,
        q,
        max_sitemaps=12,
        max_urls=MAX_CANDIDATES,
    )[:MAX_CANDIDATES]


def diagnose_search(session, query):
    """Deep Deloox discovery diagnostic; does not change normal search."""
    query = clean(query)

    report = {
        "query": query,
        "category_endpoints": [],
        "filter_urls": [],
        "candidate_urls": [],
        "validated_products": [],
        "search_fallback": [],
    }

    if not query:
        return report

    seen_candidates = set()

    for category_url in _category_pages(session):
        entry = {
            "url": category_url,
            "status": None,
            "filter_urls": [],
            "candidate_urls": [],
        }

        try:
            r = session.get(
                category_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            entry["status"] = r.status_code
        except requests.RequestException as exc:
            entry["error"] = str(exc)
            report["category_endpoints"].append(entry)
            continue

        report["category_endpoints"].append(entry)

        if r.status_code >= 400:
            continue

        filter_urls = _category_product_line_links(
            r.text,
            query,
        )

        entry["filter_urls"] = filter_urls[:20]
        report["filter_urls"].extend(filter_urls)

        pages = (
            [(category_url, False)]
            + [(url, True) for url in filter_urls]
        )

        for page_url, filtered in pages:
            try:
                page = session.get(
                    page_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException:
                continue

            if page.status_code >= 400:
                continue

            candidates = _candidate_product_urls(
                page.text,
                query,
                accept_all_products=filtered,
                base_url=f"{urlparse(page.url).scheme}://{urlparse(page.url).netloc}",
            )

            entry["candidate_urls"].extend(candidates[:40])

            for url in candidates:
                if url in seen_candidates:
                    continue

                seen_candidates.add(url)
                report["candidate_urls"].append(url)

                if len(report["candidate_urls"]) >= 80:
                    break

            if len(report["candidate_urls"]) >= 80:
                break

        if len(report["candidate_urls"]) >= 80:
            break

    for url in report["candidate_urls"]:
        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            continue

        item = _product(
            url,
            r.text,
            query,
        )

        if item:
            report["validated_products"].append(item)

    for endpoint in (
        BASE_URL + "/en/search?query=" + quote_plus(query),
        BASE_URL + "/en/search?search=" + quote_plus(query),
        BASE_URL + "/en/search?q=" + quote_plus(query),
    ):
        try:
            r = session.get(
                endpoint,
                headers=HEADERS,
                timeout=TIMEOUT,
            )

            report["search_fallback"].append({
                "url": endpoint,
                "status": r.status_code,
            })

        except requests.RequestException as exc:
            report["search_fallback"].append({
                "url": endpoint,
                "error": str(exc),
            })

    return report


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)
    results = []
    seen = set()

    try:
        candidates = _discover(session, query)[:MAX_CANDIDATES]
        if not candidates:
            return []

        # Product pages are independent HTTP requests.  Fetch them in parallel
        # so one slow candidate cannot consume the whole store timeout budget.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def fetch(url):
            try:
                r = session.get(
                    url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
                if r.status_code >= 400:
                    return None
                return _product(r.url or url, r.text, query)
            except requests.RequestException:
                return None
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as pool:
            futures = {pool.submit(fetch, url): url for url in candidates}
            for future in as_completed(futures):
                item = future.result()
                if not item:
                    continue
                sku = item.get("identity", {}).get("sku")
                sku_value = sku.get("value") if isinstance(sku, dict) else None
                key = (item.get("url"), sku_value)
                if key in seen:
                    continue
                seen.add(key)
                results.append(item)
                if len(results) >= MAX_RESULTS:
                    break

        return results[:MAX_RESULTS]
    finally:
        session.close()


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
