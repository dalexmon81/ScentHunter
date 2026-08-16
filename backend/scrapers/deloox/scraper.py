"""Deloox adapter for ScentHunter.

Discovery strategy:
- Prefer Deloox's current category pages and their Product line filter links.
- Fall back to Deloox search endpoints and sitemap discovery.
- Product pages are parsed through JSON-LD/page content.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "en-GB,en;q=0.9",
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


def availability(text):
    t = norm(text)
    if any(
        x in t
        for x in (
            "sold out",
            "out of stock",
            "not available",
            "currently unavailable",
        )
    ):
        return "out_of_stock"
    if any(x in t for x in ("in stock", "available", "op voorraad")):
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

    if not name:
        return None

    # The user may search the family name while Deloox lists the exact
    # variant (Coral Fantasy, Intense, Extradose, etc.) in the product title.
    # For Born in Roma, the family tokens are sufficient for the final match.
    if "born in roma" in norm(query):
        if not {"born", "in", "roma"}.issubset(tokens(name)):
            return None
    elif not matches(name, query):
        return None

    # Deloox product pages expose the product line separately.  Keep it
    # available as extra source context, but use the actual product name
    # for the strict query match.
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

    avail = availability(text)

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



def _candidate_product_urls(html, query=None, max_urls=80):
    """Extract product URLs without requiring the query to be in the href.

    Deloox can put the product name in a card, JSON blob, or sibling element
    while the href itself contains only the numeric product id/slug.  Discovery
    therefore collects product URLs first and lets _product() perform the
    authoritative name match.
    """
    soup = BeautifulSoup(html, "html.parser")
    scored = {}
    seen = set()

    q_tokens = tokens(query or "")

    def add(raw_url, context=""):
        if not raw_url:
            return
        raw_url = clean(raw_url).replace("\\/", "/")
        if raw_url.startswith(("javascript:", "mailto:", "#")):
            return

        url = urljoin(BASE_URL, raw_url).split("#")[0].split("?")[0]
        try:
            parsed = urlparse(url)
        except Exception:
            return

        if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
            return
        if "/product/" not in parsed.path.lower():
            return

        # Score matching cards highly, but NEVER discard a product URL merely
        # because the query text is not present in the anchor/href.
        ctx = norm(f"{context} {url}")
        score = 0
        if q_tokens and q_tokens.issubset(tokens(ctx)):
            score = 100
        elif q_tokens:
            score = sum(1 for t in q_tokens if t in tokens(ctx)) * 10

        scored[url] = max(scored.get(url, -1), score)

    # Anchor + surrounding card text.
    for a in soup.find_all("a", href=True):
        context = a.get_text(" ", strip=True)
        parent = a.parent
        for _ in range(2):
            if parent is None:
                break
            context += " " + parent.get_text(" ", strip=True)
            parent = parent.parent
        add(a.get("href"), context)

    # Product URLs embedded in JSON/JS.
    patterns = [
        r'https?://(?:www\.)?deloox\.com/[^"\'>\s]+/product/[^"\'>\s]+',
        r'["\']((?:/)?(?:en/)?product/[^"\']+)["\']',
        r'["\']((?:https?:)?//(?:www\.)?deloox\.com/[^"\']*/product/[^"\']+)["\']',
    ]
    for pattern in patterns:
        for raw in re.findall(pattern, html, re.I):
            add(raw, html[:4000])

    ranked = sorted(scored.items(), key=lambda x: (-x[1], x[0]))
    return [u for u, _ in ranked[:max_urls]]


def _search_endpoints(q):
    enc = quote_plus(q)
    # Keep these deliberately small. Search is the primary Deloox discovery
    # path; category crawling is only a fallback.
    return (
        BASE_URL + "/en/search?query=" + enc,
        BASE_URL + "/en/search?search=" + enc,
        BASE_URL + "/en/search?q=" + enc,
        BASE_URL + "/en?search=" + enc,
    )


def _fetch(session, url, timeout=6):
    try:
        r = session.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        return r
    except requests.RequestException:
        return None


def _discover_search(session, q, max_urls=40):
    urls = []
    seen = set()

    queries = _special_query_variants(q) if "born in roma" in norm(q) else [q]

    for search_q in queries:
        for endpoint in _search_endpoints(search_q):
            r = _fetch(session, endpoint, timeout=6)
            if r is None or r.status_code >= 400:
                continue

            for url in _candidate_product_urls(
                r.text, search_q, max_urls=max_urls
            ):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
                if len(urls) >= max_urls:
                    return urls[:max_urls]

    return urls[:max_urls]


def _discover_from_categories_limited(session, query, max_urls=24):
    """Small fallback only; never paginate entire Deloox categories."""
    urls, seen = [], set()

    roots = (
        BASE_URL + "/category/1075639/womens-fragrances.html",
        BASE_URL + "/category/1075750/mens-perfume.html",
        BASE_URL + "/category/1025540/trending.html",
    )

    for root in roots:
        r = _fetch(session, root, timeout=6)
        if r is None or r.status_code >= 400:
            continue

        for u in _candidate_product_urls(r.text, query, max_urls=40):
            if u not in seen:
                seen.add(u)
                urls.append(u)
            if len(urls) >= max_urls:
                return urls[:max_urls]

        # Follow at most two visible Product Line/category links matching
        # the query. No pagination here.
        soup = BeautifulSoup(r.text, "html.parser")
        followed = 0
        for a in soup.find_all("a", href=True):
            label = clean(a.get_text(" ", strip=True))
            href = clean(a.get("href"))
            if not label or not href:
                continue
            if not tokens(query).intersection(tokens(label)):
                continue

            u = urljoin(BASE_URL, href).split("#")[0]
            parsed = urlparse(u)
            if parsed.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
                continue
            if "/category/" not in parsed.path.lower():
                continue
            if u in seen:
                continue

            rr = _fetch(session, u, timeout=6)
            followed += 1
            if rr is None or rr.status_code >= 400:
                if followed >= 2:
                    break
                continue

            for pu in _candidate_product_urls(rr.text, query, max_urls=40):
                if pu not in seen:
                    seen.add(pu)
                    urls.append(pu)
                if len(urls) >= max_urls:
                    return urls[:max_urls]

            if followed >= 2:
                break

    return urls[:max_urls]


def _sitemap_product_urls(session, query, max_sitemaps=2, max_urls=24):
    """Last-resort sitemap lookup; never crawl a large sitemap tree."""
    q_tokens = tokens(query)
    if not q_tokens:
        return []

    pending = [
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
    ]
    seen_sitemaps = set()
    out = []

    while pending and len(seen_sitemaps) < max_sitemaps and len(out) < max_urls:
        sm = pending.pop(0)
        if sm in seen_sitemaps:
            continue
        seen_sitemaps.add(sm)

        r = _fetch(session, sm, timeout=6)
        if r is None or r.status_code >= 400:
            continue

        body = r.text.lstrip()
        if not body.startswith(("<?xml", "<urlset", "<sitemapindex")):
            continue

        soup = BeautifulSoup(r.text, "xml")
        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())
            if not value:
                continue
            low = value.lower()

            if "/product/" in low and q_tokens.issubset(tokens(value)):
                if value not in out:
                    out.append(value)
                    if len(out) >= max_urls:
                        break
            elif "sitemap" in low and low.endswith(".xml"):
                if value not in seen_sitemaps and len(seen_sitemaps) < max_sitemaps:
                    pending.append(value)

    return out[:max_urls]


def _special_query_variants(q):
    """Targeted variants for product families that Deloox splits."""
    nq = norm(q)

    if "born in roma" in nq:
        return [
            "Born in Roma",
            "Valentino Born in Roma",
            "Born in Roma Uomo",
            "Born in Roma Donna",
            "Born in Roma Extradose",
            "Born in Roma Intense",
            "Born in Roma Coral Fantasy",
            "Born in Roma Green Stravaganza",
            "Born in Roma Yellow Dream",
        ]

    return [q]


def _discover(session, q):
    # IMPORTANT: search first. The old adapter spent most of its time
    # crawling category pages before it ever reached Deloox's search endpoint.
    urls = _discover_search(session, q, max_urls=40)
    if urls:
        return urls[:40]

    # Only if search produced nothing, try a tiny category fallback.
    urls = _discover_from_categories_limited(session, q, max_urls=24)
    if urls:
        return urls[:24]

    # Last resort: a very small sitemap lookup.
    return _sitemap_product_urls(
        session, q, max_sitemaps=2, max_urls=24
    )[:24]


def _parse_product_safe(session, url, query):
    r = _fetch(session, url, timeout=7)
    if r is None or r.status_code >= 400:
        return None
    try:
        return _product(url, r.text, query)
    except Exception:
        return None



def diagnose_search(query):
    """
    Diagnostica Deloox senza cambiare il comportamento di search().

    Restituisce tempi e risultati intermedi per capire esattamente
    dove la ricerca si blocca: endpoint search, categorie, sitemap,
    candidate URL e pagine prodotto.
    """
    import time

    query = clean(query)
    report = {
        "query": query,
        "total_seconds": 0.0,
        "stages": [],
        "search_endpoints": [],
        "category_roots": [],
        "sitemap": [],
        "candidate_urls": [],
        "products": [],
    }

    started_all = time.perf_counter()

    def stage(name, started, **extra):
        item = {
            "stage": name,
            "seconds": round(time.perf_counter() - started, 3),
        }
        item.update(extra)
        report["stages"].append(item)

    if not query:
        report["total_seconds"] = 0.0
        return report

    session = requests.Session()

    try:
        # 1. Search endpoints: each one is timed independently.
        t = time.perf_counter()
        for endpoint in _search_endpoints(query):
            started = time.perf_counter()
            try:
                r = _fetch(session, endpoint, timeout=6)
                elapsed = round(time.perf_counter() - started, 3)

                info = {
                    "url": endpoint,
                    "seconds": elapsed,
                    "status": None if r is None else r.status_code,
                    "bytes": 0 if r is None else len(r.text),
                    "candidate_count": 0,
                }

                if r is not None and r.status_code < 400:
                    candidates = _candidate_product_urls(
                        r.text, query, max_urls=40
                    )
                    info["candidate_count"] = len(candidates)
                    report["candidate_urls"].extend(
                        u for u in candidates
                        if u not in report["candidate_urls"]
                    )

                report["search_endpoints"].append(info)

            except Exception as exc:
                report["search_endpoints"].append({
                    "url": endpoint,
                    "seconds": round(time.perf_counter() - started, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                })

        stage(
            "search_discovery",
            t,
            endpoints=len(report["search_endpoints"]),
            candidates=len(report["candidate_urls"]),
        )

        # 2. Category fallback: diagnose even when search returns nothing.
        t = time.perf_counter()
        roots = (
            BASE_URL + "/category/1075639/womens-fragrances.html",
            BASE_URL + "/category/1075750/mens-perfume.html",
            BASE_URL + "/category/1025540/trending.html",
        )

        for root in roots:
            started = time.perf_counter()
            r = _fetch(session, root, timeout=6)
            info = {
                "url": root,
                "seconds": round(time.perf_counter() - started, 3),
                "status": None if r is None else r.status_code,
                "candidate_count": 0,
            }

            if r is not None and r.status_code < 400:
                candidates = _candidate_product_urls(
                    r.text, query, max_urls=40
                )
                info["candidate_count"] = len(candidates)

                for u in candidates:
                    if u not in report["candidate_urls"]:
                        report["candidate_urls"].append(u)

                # Inspect matching category links, but don't crawl them all.
                soup = BeautifulSoup(r.text, "html.parser")
                matching_links = []

                for a in soup.find_all("a", href=True):
                    label = clean(a.get_text(" ", strip=True))
                    href = clean(a.get("href"))

                    if not label or not href:
                        continue

                    if not tokens(query).intersection(tokens(label)):
                        continue

                    u = urljoin(BASE_URL, href).split("#")[0]

                    try:
                        parsed = urlparse(u)
                    except Exception:
                        continue

                    if parsed.netloc.lower() not in {
                        "deloox.com", "www.deloox.com"
                    }:
                        continue

                    if "/category/" not in parsed.path.lower():
                        continue

                    matching_links.append({
                        "label": label,
                        "url": u,
                    })

                info["matching_category_links"] = matching_links[:10]

            report["category_roots"].append(info)

        stage(
            "category_discovery",
            t,
            roots=len(report["category_roots"]),
            candidates=len(report["candidate_urls"]),
        )

        # 3. Sitemap: diagnose only the two roots, not a large crawl.
        t = time.perf_counter()
        for sm in (
            BASE_URL + "/sitemap.xml",
            BASE_URL + "/sitemap_index.xml",
        ):
            started = time.perf_counter()
            r = _fetch(session, sm, timeout=6)

            info = {
                "url": sm,
                "seconds": round(time.perf_counter() - started, 3),
                "status": None if r is None else r.status_code,
                "bytes": 0 if r is None else len(r.text),
                "matching_products": 0,
                "child_sitemaps": 0,
            }

            if r is not None and r.status_code < 400:
                body = r.text.lstrip()
                if body.startswith(("<?xml", "<urlset", "<sitemapindex")):
                    soup = BeautifulSoup(r.text, "xml")
                    for loc in soup.find_all("loc"):
                        value = clean(loc.get_text())
                        low = value.lower()

                        if "/product/" in low and tokens(query).issubset(tokens(value)):
                            info["matching_products"] += 1
                            if value not in report["candidate_urls"]:
                                report["candidate_urls"].append(value)

                        elif "sitemap" in low and low.endswith(".xml"):
                            info["child_sitemaps"] += 1

            report["sitemap"].append(info)

        stage(
            "sitemap_discovery",
            t,
            candidates=len(report["candidate_urls"]),
        )

        # 4. Product validation: bounded, sequential, individually timed.
        # This is the most important stage for finding a slow product page.
        candidates = report["candidate_urls"][:24]
        t = time.perf_counter()

        for index, url in enumerate(candidates, start=1):
            started = time.perf_counter()
            r = _fetch(session, url, timeout=7)

            item = {
                "index": index,
                "url": url,
                "seconds": round(time.perf_counter() - started, 3),
                "status": None if r is None else r.status_code,
                "bytes": 0 if r is None else len(r.text),
                "name": None,
                "matched": False,
                "reason": None,
            }

            if r is None:
                item["reason"] = "request_failed_or_timeout"
            elif r.status_code >= 400:
                item["reason"] = "http_error"
            else:
                try:
                    parsed = _product(url, r.text, query)

                    if parsed:
                        item["matched"] = True
                        item["name"] = parsed.get("name")
                        item["price"] = parsed.get("price")
                        item["availability"] = parsed.get("offer", {}).get("availability")
                    else:
                        item["reason"] = "product_parser_rejected"
                except Exception as exc:
                    item["reason"] = f"parser_error: {type(exc).__name__}: {exc}"

            report["products"].append(item)

        stage(
            "product_validation",
            t,
            candidates=len(candidates),
            matched=sum(1 for x in report["products"] if x["matched"]),
        )

    finally:
        session.close()

    report["total_seconds"] = round(
        time.perf_counter() - started_all, 3
    )

    return report

def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    results = []
    seen = set()

    try:
        urls = _discover(session, query)[:24]

        # Keep product fetching bounded. Four workers are enough to avoid
        # turning a slow Deloox response into a deployment-wide timeout.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(_parse_product_safe, session, url, query): url
                for url in urls
            }

            for future in as_completed(futures):
                item = future.result()
                if not item:
                    continue

                sku_value = None
                sku = item["identity"].get("sku")
                if sku:
                    sku_value = sku.get("value")

                key = (item["url"], sku_value)
                if key in seen:
                    continue

                seen.add(key)
                results.append(item)

        # Stable presentation order.
        results.sort(key=lambda x: (x.get("name") or "").lower())
        return results
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
