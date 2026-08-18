import json
import os
import re
import time
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = Exception
    sync_playwright = None


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
TIMEOUT = int(os.getenv("SABINA_DIAGNOSTIC_TIMEOUT_S", "20"))
BROWSER_TIMEOUT_MS = int(os.getenv("SABINA_DIAGNOSTIC_BROWSER_TIMEOUT_MS", "30000"))
MAX_PRODUCT_CHECKS = int(os.getenv("SABINA_DIAGNOSTIC_MAX_PRODUCTS", "30"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

# This diagnostic intentionally does not contain any product-specific URL,
# brand, SKU, seed, or exception. It discovers how Sabina exposes search
# results and then validates whatever product URLs are discovered.

PRODUCT_PATH_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl)/[^/]+/(\d+)-[^/]+\.html$",
    re.I,
)

NON_PRODUCT_TERMS = {
    "gift set", "set regalo", "coffret", "bundle", "kit",
    "deodorant", "deo spray", "shower gel", "body lotion",
    "after shave", "aftershave", "travel set", "discovery set",
    "body mist", "hand cream", "handcreme",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = clean(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def query_tokens(query):
    return [x for x in norm(query).split() if len(x) > 1]


def query_matches(text, query):
    normalized = norm(text)
    wanted = query_tokens(query)
    return bool(wanted) and all(token in normalized for token in wanted)


def same_host(url):
    try:
        host = urlparse(url).netloc.lower()
        return host == "sabina.com" or host.endswith(".sabina.com")
    except Exception:
        return False


def normalise_url(href, base=BASE_URL):
    if not href:
        return None

    href = clean(href)
    href = href.replace("\\/", "/").replace("\\u002F", "/")

    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(base, href)

    parsed = urlparse(href)

    if parsed.scheme not in {"http", "https"}:
        return None

    if not same_host(href):
        return None

    path = parsed.path.rstrip("/")

    if not path or path == "/":
        return None

    return f"{parsed.scheme}://{parsed.netloc}{path}"


def is_product_url(url):
    try:
        return bool(PRODUCT_PATH_RE.match(urlparse(url).path))
    except Exception:
        return False


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def fetch(session, url, params=None):
    started = time.monotonic()

    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        return {
            "ok": response.status_code < 400,
            "status": response.status_code,
            "requested_url": url,
            "final_url": response.url,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(response.content),
            "elapsed": round(time.monotonic() - started, 3),
            "html": response.text,
            "error": None,
        }

    except requests.RequestException as exc:
        return {
            "ok": False,
            "status": None,
            "requested_url": url,
            "final_url": None,
            "content_type": "",
            "bytes": 0,
            "elapsed": round(time.monotonic() - started, 3),
            "html": "",
            "error": repr(exc),
        }


def query_hits_in_html(html, query):
    raw = norm(html)
    visible = norm(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    hits = {}
    for token in query_tokens(query):
        hits[token] = {
            "raw_html": token in raw,
            "visible_text": token in visible,
        }
    return hits


def extract_product_urls_from_anchors(soup, query):
    found = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        url = normalise_url(anchor.get("href"))
        if not url or not is_product_url(url):
            continue

        text = clean(
            " ".join(
                value for value in (
                    anchor.get("title"),
                    anchor.get("aria-label"),
                    anchor.get_text(" ", strip=True),
                )
                if value
            )
        )

        image = anchor.find("img")
        if image:
            text = clean(
                " ".join(
                    value for value in (
                        text,
                        image.get("alt"),
                        image.get("title"),
                    )
                    if value
                )
            )

        parent = anchor
        for _ in range(5):
            parent = parent.parent if parent is not None else None
            if parent is None:
                break
            candidate = clean(parent.get_text(" ", strip=True))
            if len(candidate) >= 40:
                text = clean(f"{text} {candidate}")
                break

        if url in seen:
            continue

        seen.add(url)
        found.append({
            "url": url,
            "text": text[:800],
            "query_match_in_card": query_matches(text, query),
        })

    return found


def extract_product_urls_from_attributes(soup, query):
    found = []
    seen = set()

    for node in soup.find_all(True):
        context = clean(node.get_text(" ", strip=True))

        for attr in (
            "data-href",
            "data-url",
            "data-product-url",
            "data-link",
            "data-product",
        ):
            raw = node.get(attr)

            if not isinstance(raw, str):
                continue

            url = normalise_url(raw)

            if not url or not is_product_url(url):
                continue

            if url in seen:
                continue

            seen.add(url)
            found.append({
                "url": url,
                "attribute": attr,
                "context": context[:500],
                "query_match": query_matches(
                    f"{context} {url}",
                    query,
                ),
            })

    return found


def extract_product_urls_from_jsonld(soup, query):
    found = []
    seen = set()
    script_count = 0
    product_count = 0

    for script in soup.select('script[type="application/ld+json"]'):
        script_count += 1
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        for obj in walk_json(data):
            if not isinstance(obj, dict):
                continue

            obj_type = obj.get("@type")
            types = obj_type if isinstance(obj_type, list) else [obj_type]

            if any(str(item).lower() == "product" for item in types):
                product_count += 1

            for field in ("url", "@id"):
                value = obj.get(field)

                if not isinstance(value, str):
                    continue

                url = normalise_url(value)

                if not url or not is_product_url(url):
                    continue

                if url in seen:
                    continue

                seen.add(url)
                found.append({
                    "url": url,
                    "field": field,
                    "name": clean(obj.get("name")),
                    "query_match": query_matches(
                        f"{obj.get('name', '')} {url}",
                        query,
                    ),
                })

    return found, script_count, product_count


def extract_product_urls_from_raw_html(html):
    decoded = html.replace("\\/", "/").replace("\\u002F", "/")
    found = []
    seen = set()

    patterns = (
        r'https?://(?:www\.)?sabina\.com/(?:es|it|fr|en|de|nl)/[^"\'<>\s\\]+',
        r'/(?:es|it|fr|en|de|nl)/[^"\'<>\s\\]+',
    )

    for pattern in patterns:
        for match in re.finditer(pattern, decoded, re.I):
            url = normalise_url(match.group(0))

            if not url or not is_product_url(url):
                continue

            if url in seen:
                continue

            seen.add(url)
            found.append(url)

    return found


def extract_search_forms(soup):
    forms = []

    for form in soup.find_all("form"):
        action = normalise_url(form.get("action") or "/es/buscar")
        method = clean(form.get("method") or "get").lower()

        inputs = []

        for node in form.find_all(["input", "select", "textarea"]):
            name = clean(node.get("name"))
            value = clean(node.get("value"))

            if name:
                inputs.append({
                    "tag": node.name,
                    "name": name,
                    "value": value,
                    "type": clean(node.get("type")),
                })

        forms.append({
            "action": action,
            "method": method,
            "inputs": inputs[:50],
        })

    return forms


def extract_search_endpoints_from_html(html):
    decoded = html.replace("\\/", "/").replace("\\u002F", "/")
    found = []
    seen = set()

    # Extract Sabina internal URLs from scripts and markup. We later test
    # only generic URLs that visibly resemble search endpoints.
    for match in re.finditer(
        r'https?://(?:www\.)?sabina\.com/[^"\'<>\s\\]+',
        decoded,
        re.I,
    ):
        url = normalise_url(match.group(0))
        if not url or url in seen:
            continue

        path = urlparse(url).path.lower()

        if any(term in path for term in (
            "/buscar",
            "/search",
            "advancedsearch",
        )):
            seen.add(url)
            found.append(url)

    return found


def candidate_search_requests(query):
    # These are generic Sabina search mechanisms, not product-specific seeds.
    # The diagnostic tests them all and reports which one actually exposes
    # query-relevant product URLs.
    encoded = quote_plus(query)

    return [
        {
            "name": "search_query",
            "url": f"{BASE_URL}/es/buscar",
            "params": {"search_query": query},
        },
        {
            "name": "s",
            "url": f"{BASE_URL}/es/buscar",
            "params": {"s": query},
        },
        {
            "name": "controller_search_s",
            "url": f"{BASE_URL}/es/buscar",
            "params": {"controller": "search", "s": query},
        },
        {
            "name": "buscar_old_s",
            "url": f"{BASE_URL}/es/buscar_old",
            "params": {"s": query},
        },
        {
            "name": "buscar_old_controller_s",
            "url": f"{BASE_URL}/es/buscar_old",
            "params": {"controller": "search", "s": query},
        },
        {
            "name": "path_search_query",
            "url": f"{BASE_URL}/es/buscar",
            "params": {"search_query": query},
        },
        {
            "name": "query_in_path_fallback",
            "url": f"{BASE_URL}/es/buscar?search_query={encoded}",
            "params": None,
        },
    ]


def inspect_search_response(label, fetched, query):
    html = fetched.get("html", "")
    soup = BeautifulSoup(html, "html.parser") if html else BeautifulSoup("", "html.parser")

    anchors = extract_product_urls_from_anchors(soup, query)
    attributes = extract_product_urls_from_attributes(soup, query)
    jsonld, script_count, product_count = extract_product_urls_from_jsonld(
        soup,
        query,
    )
    raw_urls = extract_product_urls_from_raw_html(html) if html else []

    query_hits = query_hits_in_html(html, query) if html else {}

    product_urls = []
    seen = set()

    for source in (anchors, attributes, jsonld):
        for item in source:
            url = item["url"]
            if url not in seen:
                seen.add(url)
                product_urls.append(url)

    for url in raw_urls:
        if url not in seen:
            seen.add(url)
            product_urls.append(url)

    forms = extract_search_forms(soup) if html else []
    endpoint_links = extract_search_endpoints_from_html(html) if html else []

    return {
        "endpoint": label,
        "requested_url": fetched.get("requested_url"),
        "params": fetched.get("params"),
        "status": fetched.get("status"),
        "final_url": fetched.get("final_url"),
        "content_type": fetched.get("content_type"),
        "bytes": fetched.get("bytes"),
        "elapsed": fetched.get("elapsed"),
        "error": fetched.get("error"),
        "query_in_raw_html": any(
            value.get("raw_html")
            for value in query_hits.values()
        ) if query_hits else False,
        "query_in_visible_text": any(
            value.get("visible_text")
            for value in query_hits.values()
        ) if query_hits else False,
        "query_token_hits": query_hits,
        "product_url_count": len(product_urls),
        "sample_product_urls": product_urls[:20],
        "anchor_candidates": anchors[:20],
        "attribute_candidates": attributes[:20],
        "jsonld_candidates": jsonld[:20],
        "jsonld_script_count": script_count,
        "jsonld_product_count": product_count,
        "raw_product_url_count": len(raw_urls),
        "raw_product_urls": raw_urls[:20],
        "form_actions": [
            form["action"]
            for form in forms
            if form.get("action")
        ][:20],
        "search_endpoint_links": endpoint_links[:20],
    }


def inspect_product_page(session, url, query):
    fetched = fetch(session, url)

    result = {
        "url": url,
        "status": fetched.get("status"),
        "final_url": fetched.get("final_url"),
        "bytes": fetched.get("bytes"),
        "elapsed": fetched.get("elapsed"),
        "error": fetched.get("error"),
        "h1": "",
        "jsonld_products": [],
        "query_matches": {
            "h1": False,
            "jsonld": False,
        },
        "product_id": None,
        "price": None,
        "availability": None,
        "verdict": False,
        "failure": None,
    }

    if not fetched.get("ok"):
        result["failure"] = "product_request_failed"
        return result

    soup = BeautifulSoup(fetched["html"], "html.parser")

    h1_node = soup.select_one("h1")
    h1 = clean(h1_node.get_text(" ", strip=True)) if h1_node else ""
    result["h1"] = h1
    result["query_matches"]["h1"] = query_matches(h1, query)

    product = None

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        for obj in walk_json(data):
            if not isinstance(obj, dict):
                continue

            types = obj.get("@type")
            types = types if isinstance(types, list) else [types]

            if not any(str(t).lower() == "product" for t in types):
                continue

            product = obj

            name = clean(obj.get("name"))
            if name:
                result["jsonld_products"].append({
                    "name": name,
                    "url": clean(obj.get("url")),
                    "sku": clean(obj.get("sku")),
                    "gtin": clean(
                        obj.get("gtin13")
                        or obj.get("gtin12")
                        or obj.get("gtin14")
                        or obj.get("gtin")
                    ),
                })

    result["query_matches"]["jsonld"] = any(
        query_matches(item["name"], query)
        for item in result["jsonld_products"]
    )

    match = PRODUCT_PATH_RE.match(urlparse(fetched["final_url"] or url).path)
    result["product_id"] = match.group(1) if match else None

    if isinstance(product, dict):
        offers = product.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            result["price"] = offers.get("price")
            result["availability"] = offers.get("availability")

    if result["query_matches"]["h1"] or result["query_matches"]["jsonld"]:
        result["verdict"] = True
    else:
        result["failure"] = "product_identity_does_not_match_query"

    return result


def browser_discovery(query):
    if sync_playwright is None:
        return {
            "enabled": False,
            "reason": "playwright_not_installed",
            "status": None,
            "final_url": None,
            "bytes": 0,
            "candidate_urls": [],
            "error": None,
        }

    search_url = (
        f"{BASE_URL}/es/buscar?search_query={quote_plus(query)}"
    )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )

            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="es-ES",
                extra_http_headers={
                    "Accept-Language": HEADERS["Accept-Language"],
                },
                viewport={"width": 1365, "height": 900},
            )

            page = context.new_page()

            response = page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=BROWSER_TIMEOUT_MS,
            )

            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=15000,
                )
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(1000)

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            candidates = extract_product_urls_from_anchors(
                soup,
                query,
            )

            final_url = page.url
            status = response.status if response else None

            browser.close()

            return {
                "enabled": True,
                "reason": None,
                "status": status,
                "final_url": final_url,
                "bytes": len(html),
                "candidate_urls": candidates[:30],
                "error": None,
            }

    except Exception as exc:
        return {
            "enabled": True,
            "reason": None,
            "status": None,
            "final_url": None,
            "bytes": 0,
            "candidate_urls": [],
            "error": repr(exc),
        }


def sitemap_diagnostic(session, query):
    result = {
        "index_url": f"{BASE_URL}/sitemap_index.xml",
        "status": None,
        "content_type": None,
        "bytes": 0,
        "sitemaps_seen": 0,
        "sitemaps_fetched": 0,
        "product_candidates": [],
        "errors": [],
    }

    fetched = fetch(session, result["index_url"])

    result["status"] = fetched.get("status")
    result["content_type"] = fetched.get("content_type")
    result["bytes"] = fetched.get("bytes")

    if not fetched.get("ok"):
        result["errors"].append("sitemap_index_request_failed")
        return result

    soup = BeautifulSoup(fetched["html"], "xml")
    sitemap_urls = []

    for node in soup.find_all("loc"):
        url = clean(node.get_text())
        if url and same_host(url):
            sitemap_urls.append(url)

    result["sitemaps_seen"] = len(sitemap_urls)

    # Do not crawl an unbounded sitemap tree. Only inspect sitemap XMLs
    # discovered from the site's own index.
    for sitemap_url in sitemap_urls[:30]:
        child = fetch(session, sitemap_url)

        if not child.get("ok"):
            result["errors"].append({
                "url": sitemap_url,
                "error": "sitemap_request_failed",
            })
            continue

        result["sitemaps_fetched"] += 1

        child_soup = BeautifulSoup(child["html"], "xml")

        for loc in child_soup.find_all("loc"):
            url = normalise_url(loc.get_text())
            if not url or not is_product_url(url):
                continue

            if query_matches(url, query):
                result["product_candidates"].append(url)

            if len(result["product_candidates"]) >= 50:
                return result

    return result


def build_report(query):
    session = requests.Session()

    try:
        report = {
            "diagnostic_version": "sabina-DIAGNOSTIC-FINAL-v2",
            "store": STORE,
            "query": query,
            "method": "HTTP_SEARCH_PLUS_SITEMAP_PLUS_PRODUCT_VALIDATION_PLUS_BROWSER",
            "search": [],
            "sitemap": None,
            "product_probes": [],
            "browser": None,
            "summary": {},
        }

        # 1. Test all known generic search mechanisms.
        all_candidates = []

        for spec in candidate_search_requests(query):
            fetched = fetch(
                session,
                spec["url"],
                spec.get("params"),
            )

            # Preserve params in the diagnostic record.
            fetched["params"] = spec.get("params")

            inspected = inspect_search_response(
                spec["name"],
                fetched,
                query,
            )

            report["search"].append(inspected)

            for url in inspected["sample_product_urls"]:
                if url not in all_candidates:
                    all_candidates.append(url)

        # 2. Test endpoints discovered from the site's own search HTML.
        discovered_endpoint_urls = []

        for item in report["search"]:
            for endpoint_url in item["search_endpoint_links"]:
                if endpoint_url not in discovered_endpoint_urls:
                    discovered_endpoint_urls.append(endpoint_url)

        for endpoint_url in discovered_endpoint_urls[:20]:
            # Only test endpoint-looking paths and append the query generically.
            path = urlparse(endpoint_url).path.lower()

            if "/buscar" not in path and "/search" not in path:
                continue

            parsed = urlparse(endpoint_url)
            separator = "&" if parsed.query else "?"

            url = (
                endpoint_url
                + separator
                + "search_query="
                + quote_plus(query)
            )

            fetched = fetch(session, url)
            fetched["params"] = {"search_query": query}

            inspected = inspect_search_response(
                "discovered:" + endpoint_url,
                fetched,
                query,
            )

            report["search"].append(inspected)

            for candidate in inspected["sample_product_urls"]:
                if candidate not in all_candidates:
                    all_candidates.append(candidate)

        # 3. Sitemap is independent evidence.
        report["sitemap"] = sitemap_diagnostic(
            session,
            query,
        )

        for url in report["sitemap"]["product_candidates"]:
            if url not in all_candidates:
                all_candidates.append(url)

        # 4. Validate discovered product pages.
        for url in all_candidates[:MAX_PRODUCT_CHECKS]:
            report["product_probes"].append(
                inspect_product_page(
                    session,
                    url,
                    query,
                )
            )

        valid_products = [
            item
            for item in report["product_probes"]
            if item["verdict"]
        ]

        # 5. Browser is only a diagnostic fallback. It does not hide an HTTP
        # failure; it tells us whether the site behaves differently in a
        # browser than in requests.
        if not valid_products:
            report["browser"] = browser_discovery(query)

            for item in report["browser"].get("candidate_urls", []):
                url = item.get("url")
                if not url or url in all_candidates:
                    continue

                all_candidates.append(url)

                if len(report["product_probes"]) >= MAX_PRODUCT_CHECKS:
                    break

                report["product_probes"].append(
                    inspect_product_page(
                        session,
                        url,
                        query,
                    )
                )

            valid_products = [
                item
                for item in report["product_probes"]
                if item["verdict"]
            ]

        usable_searches = [
            item
            for item in report["search"]
            if item["status"] == 200
            and item["product_url_count"] > 0
            and any(
                candidate.get("query_match_in_card")
                or candidate.get("query_match")
                for candidate in (
                    item["anchor_candidates"]
                    + item["attribute_candidates"]
                    + item["jsonld_candidates"]
                )
            )
        ]

        if valid_products:
            report["summary"] = {
                "verdict": "DISCOVERY_AND_VALIDATION_WORK",
                "diagnosis": (
                    "Sabina exposes query-relevant product URLs and the "
                    "product pages validate successfully."
                ),
                "usable_search_methods": [
                    item["endpoint"] for item in usable_searches
                ],
                "candidate_count": len(all_candidates),
                "valid_product_count": len(valid_products),
            }
        elif usable_searches:
            report["summary"] = {
                "verdict": "DISCOVERY_WORKS_VALIDATION_FAILS",
                "diagnosis": (
                    "Sabina exposes query-relevant product URLs, but the "
                    "product-page validation layer rejects them or cannot "
                    "retrieve/identify the product."
                ),
                "usable_search_methods": [
                    item["endpoint"] for item in usable_searches
                ],
                "candidate_count": len(all_candidates),
                "valid_product_count": 0,
            }
        elif all_candidates:
            report["summary"] = {
                "verdict": "CANDIDATES_FOUND_BUT_QUERY_MATCH_UNCLEAR",
                "diagnosis": (
                    "Sabina exposes product URLs, but the diagnostic cannot "
                    "prove that the search response associates them with the "
                    "requested query. Inspect search records."
                ),
                "candidate_count": len(all_candidates),
                "valid_product_count": 0,
            }
        else:
            report["summary"] = {
                "verdict": "DISCOVERY_FAILS",
                "diagnosis": (
                    "No product URL was discovered through the tested HTTP "
                    "search mechanisms, sitemap, or browser fallback."
                ),
                "candidate_count": 0,
                "valid_product_count": 0,
            }

        return report

    finally:
        session.close()


def search(query):
    query = clean(query)

    if not query:
        return []

    report = build_report(query)

    # The existing main.py expects a normal scraper result list. We therefore
    # return exactly one diagnostic record containing the complete report.
    # This lets /test-store display the entire investigation without changing
    # main.py and without pretending that the diagnostic is a real product.
    return [{
        "store": STORE,
        "name": "SABINA_DIAGNOSTIC " + query,
        "brand": "Sabina",
        "price": "diagnostic",
        "url": BASE_URL,
        "available": False,
        "raw_data": report,
    }]


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generic Sabina discovery diagnostic"
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="Liquid Brun",
    )

    args = parser.parse_args()

    print(
        json.dumps(
            build_report(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
