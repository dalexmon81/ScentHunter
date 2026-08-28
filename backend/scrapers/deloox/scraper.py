"""
SCENTHUNTER - Deloox diagnostic
Standalone diagnostic only. DO NOT replace the production Deloox scraper with this file.

Run:
    python deloox_diagnostic.py "Liquid Brun"

It tests Deloox.be directly and compares:
1) homepage / HTTP access
2) generic search endpoints
3) category pages
4) sitemap endpoints
5) product URL discovery from raw HTML
6) product-page validation
7) the currently installed production scraper extractor/search, when importable

It does not contain product-specific seeds or exceptions.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import time
from collections import Counter
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE = "https://www.deloox.be"
ALT = "https://www.deloox.com"
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", clean(value).lower()),
    ).strip()


def tokens(value):
    return {
        x for x in norm(value).split()
        if len(x) > 1
    }


def matches(text, query):
    wanted = tokens(query)
    return bool(wanted) and wanted.issubset(tokens(text))


def fetch(session, url):
    started = time.perf_counter()
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        return {
            "requested": url,
            "final": response.url,
            "status": response.status_code,
            "ok": response.status_code < 400,
            "elapsed_ms": round(
                (time.perf_counter() - started) * 1000,
                1,
            ),
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(response.content),
            "html": response.text or "",
            "error": None,
        }
    except Exception as exc:
        return {
            "requested": url,
            "final": None,
            "status": None,
            "ok": False,
            "elapsed_ms": round(
                (time.perf_counter() - started) * 1000,
                1,
            ),
            "content_type": "",
            "bytes": 0,
            "html": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def extract_product_urls(html, base=BASE):
    soup = BeautifulSoup(html or "", "html.parser")
    found = []
    seen = set()

    def add(value):
        if not value:
            return

        value = clean(value).replace("\\/", "/")

        candidates = [value]

        candidates.extend(
            re.findall(
                r'https?://[^"\'<>\s]+/product/[^"\'<>\s]+',
                value,
                re.I,
            )
        )

        candidates.extend(
            re.findall(
                r'(?:(?:/)?(?:en/|it/|nl/)?product/[^"\'<>\s]+)',
                value,
                re.I,
            )
        )

        for candidate in candidates:
            candidate = clean(candidate).replace("\\/", "/")
            url = urljoin(base, candidate).split("#")[0]

            try:
                parsed = urlparse(url)
            except Exception:
                continue

            host = parsed.netloc.lower()
            if host not in {"deloox.be", "www.deloox.be"}:
                continue

            if "/product/" not in parsed.path.lower():
                continue

            if url not in seen:
                seen.add(url)
                found.append(url)

    for tag in soup.find_all("a", href=True):
        add(tag.get("href"))

    for tag in soup.find_all(True):
        for name, value in tag.attrs.items():
            if isinstance(value, str) and (
                name.startswith("data-")
                or name in {"href", "src"}
            ):
                add(value)

    raw = (html or "").replace("\\\\/", "/")

    patterns = [
        r'href\s*=\s*["\']((?:https?:)?//[^"\']+/product/[^"\']+)',
        r'["\']((?:/)?(?:en/|it/|nl/)?product/[^"\'\s<>]+)["\']',
        r'https?://[^"\'<>\s]+/product/[^"\'<>\s]+',
    ]

    for pattern in patterns:
        for value in re.findall(pattern, raw, re.I):
            add(value)

    return found


def url_summary(urls, query=None):
    hosts = Counter(urlparse(x).netloc.lower() for x in urls)

    if query:
        query_urls = [
            x for x in urls
            if matches(x, query)
        ]
    else:
        query_urls = []

    return {
        "total": len(urls),
        "hosts": dict(hosts),
        "query_in_url_count": len(query_urls),
        "sample": urls[:25],
        "query_sample": query_urls[:25],
    }


def test_endpoint(session, url, query):
    page = fetch(session, url)
    urls = extract_product_urls(page["html"])

    return {
        "requested": page["requested"],
        "final": page["final"],
        "status": page["status"],
        "ok": page["ok"],
        "elapsed_ms": page["elapsed_ms"],
        "content_type": page["content_type"],
        "bytes": page["bytes"],
        "product_marker_count": page["html"].lower().count("/product"),
        "products_marker_count": page["html"].lower().count("/products"),
        "products": url_summary(urls, query),
        "error": page["error"],
    }


def test_domain(session, base, query):
    endpoints = [
        f"{base}/",
        f"{base}/en/search?query={quote_plus(query)}",
        f"{base}/en/search?q={quote_plus(query)}",
        f"{base}/en/search?search={quote_plus(query)}",
        f"{base}/search?query={quote_plus(query)}",
        f"{base}/search?q={quote_plus(query)}",
        f"{base}/en?search={quote_plus(query)}",
        f"{base}/category/1000054/mens-fragrances.html",
        f"{base}/category/1075639/womens-fragrances.html",
    ]

    results = []
    for url in endpoints:
        results.append(test_endpoint(session, url, query))

    return results


def test_sitemaps(session, query):
    endpoints = [
        f"{BASE}/robots.txt",
        f"{BASE}/sitemap.xml",
        f"{BASE}/sitemap_index.xml",
        f"{BASE}/sitemap-index.xml",
        f"{BASE}/en/sitemap.xml",
    ]

    results = []

    for url in endpoints:
        page = fetch(session, url)
        locs = re.findall(
            r"<loc>\s*([^<]+?)\s*</loc>",
            page["html"],
            re.I,
        )

        product_locs = [
            clean(x)
            for x in locs
            if "/product" in x.lower()
        ]

        results.append(
            {
                "requested": url,
                "final": page["final"],
                "status": page["status"],
                "ok": page["ok"],
                "elapsed_ms": page["elapsed_ms"],
                "loc_count": len(locs),
                "product_loc_count": len(product_locs),
                "query_product_loc_count": sum(
                    matches(x, query)
                    for x in product_locs
                ),
                "product_sample": product_locs[:25],
                "query_product_sample": [
                    x for x in product_locs
                    if matches(x, query)
                ][:25],
                "error": page["error"],
            }
        )

    return results


def jsonld_products(soup):
    products = []

    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            data = json.loads(
                script.get_text(strip=True)
            )
        except Exception:
            continue

        queue = data if isinstance(data, list) else [data]

        while queue:
            item = queue.pop(0)

            if isinstance(item, list):
                queue.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            types = item.get("@type")
            if (
                types == "Product"
                or (
                    isinstance(types, list)
                    and "Product" in types
                )
                or "offers" in item
            ):
                products.append(item)

            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

    return products


def validate_product(session, url, query):
    page = fetch(session, url)
    soup = BeautifulSoup(page["html"], "html.parser")

    title = clean(
        soup.title.get_text(" ", strip=True)
    ) if soup.title else ""

    h1 = soup.find("h1")
    h1_text = clean(
        h1.get_text(" ", strip=True)
    ) if h1 else ""

    products = jsonld_products(soup)
    names = [
        clean(x.get("name"))
        for x in products
        if x.get("name")
    ]

    return {
        "url": url,
        "status": page["status"],
        "final": page["final"],
        "elapsed_ms": page["elapsed_ms"],
        "bytes": page["bytes"],
        "title": title,
        "h1": h1_text,
        "jsonld_product_count": len(products),
        "jsonld_names": names[:10],
        "query_matches_h1": matches(h1_text, query),
        "query_matches_jsonld": any(
            matches(name, query)
            for name in names
        ),
        "error": page["error"],
    }


def inspect_production_scraper(html, query):
    module_names = [
        "backend.scrapers.deloox.scraper",
        "scrapers.deloox.scraper",
    ]

    module = None
    import_error = None

    for name in module_names:
        try:
            module = importlib.import_module(name)
            break
        except Exception as exc:
            import_error = (
                f"{type(exc).__name__}: {exc}"
            )

    if module is None:
        return {
            "imported": False,
            "error": import_error,
        }

    report = {
        "imported": True,
        "module": module.__name__,
        "file": getattr(module, "__file__", None),
        "BASE_URL": getattr(module, "BASE_URL", None),
        "TIMEOUT": getattr(module, "TIMEOUT", None),
    }

    extractor = getattr(
        module,
        "_candidate_product_urls",
        None,
    )

    if callable(extractor):
        try:
            urls = extractor(html, query)
            report["candidate_extractor"] = {
                "count": len(urls or []),
                "sample": list(urls or [])[:25],
                "error": None,
            }
        except Exception as exc:
            report["candidate_extractor"] = {
                "count": None,
                "sample": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
    else:
        report["candidate_extractor"] = {
            "count": None,
            "sample": [],
            "error": "function not available",
        }

    search_fn = getattr(module, "search", None)

    if callable(search_fn):
        started = time.perf_counter()
        try:
            result = search_fn(query) or []
            report["real_search"] = {
                "count": len(result),
                "elapsed_ms": round(
                    (time.perf_counter() - started) * 1000,
                    1,
                ),
                "sample": result[:10],
                "error": None,
            }
        except Exception as exc:
            report["real_search"] = {
                "count": None,
                "elapsed_ms": round(
                    (time.perf_counter() - started) * 1000,
                    1,
                ),
                "sample": [],
                "error": f"{type(exc).__name__}: {exc}",
            }

    return report


def main():
    query = clean(
        " ".join(sys.argv[1:])
        or "Liquid Brun"
    )

    started = time.perf_counter()

    session = requests.Session()

    report = {
        "diagnostic": "Deloox REAL",
        "query": query,
        "canonical": {},
        "alternate": {},
        "sitemaps": [],
        "production_scraper": {},
        "verdict": {},
    }

    try:
        report["canonical"]["tests"] = test_domain(
            session,
            BASE,
            query,
        )

        report["alternate"]["tests"] = test_domain(
            session,
            ALT,
            query,
        )

        report["sitemaps"] = test_sitemaps(
            session,
            query,
        )

        canonical_urls = []

        for item in report["canonical"]["tests"]:
            canonical_urls.extend(
                item["products"]["sample"]
            )

        canonical_urls = list(
            dict.fromkeys(canonical_urls)
        )

        report["canonical"]["unique_product_urls"] = (
            len(canonical_urls)
        )

        report["canonical"]["validated_products"] = [
            validate_product(
                session,
                url,
                query,
            )
            for url in canonical_urls[:15]
        ]

        # Pick the first successful canonical page containing
        # product markers and inspect the production extractor
        # against the exact HTML that Deloox returned.
        html_for_scraper = None
        html_source = None

        for item in report["canonical"]["tests"]:
            if (
                item["ok"]
                and item["product_marker_count"] > 0
            ):
                page = fetch(
                    session,
                    item["final"] or item["requested"],
                )
                if page["ok"]:
                    html_for_scraper = page["html"]
                    html_source = page["final"]
                    break

        if html_for_scraper is not None:
            report["production_scraper"] = (
                inspect_production_scraper(
                    html_for_scraper,
                    query,
                )
            )
            report["production_scraper"][
                "html_source"
            ] = html_source
        else:
            report["production_scraper"] = {
                "error": (
                    "No canonical Deloox.be response "
                    "with product markers was available "
                    "for extractor comparison."
                )
            }

        be_live = sum(
            bool(x["ok"])
            for x in report["canonical"]["tests"]
        )
        be_products = sum(
            x["products"]["total"]
            for x in report["canonical"]["tests"]
        )
        com_live = sum(
            bool(x["ok"])
            for x in report["alternate"]["tests"]
        )

        scraper_base = (
            report["production_scraper"]
            .get("BASE_URL")
        )

        if (
            scraper_base
            and "deloox.be" not in str(scraper_base).lower()
            and be_products > 0
        ):
            report["verdict"] = {
                "code": "WRONG_SCRAPER_BASE_URL",
                "severity": "DEFINITIVE",
                "reason": (
                    "Deloox.be espone candidati prodotto, "
                    "ma lo scraper importato usa un dominio "
                    "diverso."
                ),
            }
        elif be_live > 0 and be_products == 0:
            report["verdict"] = {
                "code": "BE_RESPONDS_NO_PRODUCT_URLS",
                "severity": "DISCOVERY_FAILURE",
                "reason": (
                    "Deloox.be risponde ma i percorsi "
                    "testati non espongono URL prodotto "
                    "riconoscibili."
                ),
            }
        elif be_products > 0:
            real_search = report["production_scraper"].get(
                "real_search"
            )

            if (
                isinstance(real_search, dict)
                and real_search.get("count") == 0
            ):
                report["verdict"] = {
                    "code": "PRODUCTION_SCRAPER_DROPS_RESULTS",
                    "severity": "DEFINITIVE",
                    "reason": (
                        "Deloox.be espone e valida candidati, "
                        "ma la search reale dello scraper "
                        "restituisce zero."
                    ),
                }
            else:
                report["verdict"] = {
                    "code": "BE_DISCOVERY_REACHES_PRODUCTS",
                    "severity": "DISCOVERY_OK",
                    "reason": (
                        "La discovery diretta di Deloox.be "
                        "raggiunge URL prodotto. Il confronto "
                        "con lo scraper identifica il punto "
                        "successivo della catena."
                    ),
                }
        elif com_live > 0:
            report["verdict"] = {
                "code": "BE_ACCESS_PROBLEM",
                "severity": "DOMAIN_ACCESS",
                "reason": (
                    "Deloox.be non ha prodotto risposte utili "
                    "nei test mentre deloox.com risponde."
                ),
            }
        else:
            report["verdict"] = {
                "code": "UNRESOLVED",
                "severity": "UNRESOLVED",
                "reason": (
                    "I test non hanno ancora isolato una "
                    "causa unica."
                ),
            }

        report["elapsed_total_ms"] = round(
            (time.perf_counter() - started) * 1000,
            1,
        )

        print(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            )
        )

    finally:
        session.close()


if __name__ == "__main__":
    main()
