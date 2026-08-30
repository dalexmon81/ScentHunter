from __future__ import annotations

import importlib
import inspect
import json
import re
import time
import traceback
from collections import Counter
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

APP_TITLE = "ScentHunter - Deloox Causal Diagnostic"
SCRAPER_MODULE = "scrapers.deloox.scraper"
DEFAULT_QUERY = "Liquid Brun"
TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

app = FastAPI(title=APP_TITLE, version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    return re.sub(
        r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(value).lower())
    ).strip()


def tokens(value):
    return {x for x in norm(value).split() if len(x) > 1}


def token_match(text, query):
    wanted = tokens(query)
    return bool(wanted) and wanted.issubset(tokens(text))


def safe_call(fn, *args, **kwargs):
    started = time.perf_counter()
    try:
        value = fn(*args, **kwargs)
        return {
            "status": "OK",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "value": value,
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "ERROR",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "value": None,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def request_page(session, url, timeout=TIMEOUT):
    started = time.perf_counter()
    try:
        r = session.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        body = r.text or ""
        return {
            "ok": r.status_code < 400,
            "status": r.status_code,
            "elapsed_ms": elapsed,
            "requested_url": url,
            "final_url": r.url,
            "redirected": r.url != url,
            "content_type": r.headers.get("content-type", ""),
            "bytes": len(r.content),
            "html_length": len(body),
            "body": body,
            "error": None,
        }
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        return {
            "ok": False,
            "status": None,
            "elapsed_ms": elapsed,
            "requested_url": url,
            "final_url": None,
            "redirected": False,
            "content_type": "",
            "bytes": 0,
            "html_length": 0,
            "body": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def html_structure(html):
    soup = BeautifulSoup(html or "", "html.parser")
    scripts = soup.find_all("script")
    anchors = soup.find_all("a", href=True)
    jsonld_scripts = soup.select('script[type="application/ld+json"]')
    forms = soup.find_all("form")
    return {
        "title": clean(soup.title.get_text(" ", strip=True)) if soup.title else "",
        "h1": [clean(x.get_text(" ", strip=True)) for x in soup.find_all("h1")[:10]],
        "anchor_count": len(anchors),
        "script_count": len(scripts),
        "jsonld_script_count": len(jsonld_scripts),
        "form_count": len(forms),
        "has_next_data": bool(soup.select_one("script#__NEXT_DATA__")),
        "has_jsonld_product": False,
        "jsonld_names": [],
        "marker_counts": {
            "/product": (html or "").lower().count("/product"),
            "/products": (html or "").lower().count("/products"),
            "/produit": (html or "").lower().count("/produit"),
            "Product": (html or "").count('"Product"'),
            "product": (html or "").lower().count("product"),
        },
    }


def extract_broad_product_urls(html, base_url):
    """Diagnostic-only broad extractor; intentionally looser than production."""
    soup = BeautifulSoup(html or "", "html.parser")
    found = []
    seen = set()

    def add(raw, source, context=""):
        if not raw:
            return
        raw = clean(raw).replace("\\/", "/")
        if raw.startswith(("javascript:", "mailto:", "#")):
            return
        url = urljoin(base_url, raw).split("#")[0]
        try:
            p = urlparse(url)
        except Exception:
            return
        if p.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
            return
        path = p.path.lower()
        if "/product" not in path and "/produit" not in path:
            return
        if url in seen:
            return
        seen.add(url)
        found.append({
            "url": url,
            "source": source,
            "context": clean(context)[:300],
        })

    for a in soup.find_all("a", href=True):
        add(a.get("href"), "anchor", a.get_text(" ", strip=True))

    raw = (html or "").replace("\\\\/", "/")
    patterns = [
        (r'https?://(?:www\\.)?deloox\\.be/[^"\'>\s]+/(?:product|produit)/[^"\'>\s]+', "absolute"),
        (r'["\']((?:/)?(?:en/|fr/|nl/|it/)?(?:product|produit)/[^"\']+)["\']', "relative"),
        (r'["\']((?:/)?(?:en/|fr/|nl/|it/)?(?:products|produits)/[^"\']+)["\']', "plural"),
    ]
    for pattern, source in patterns:
        for raw_url in re.findall(pattern, raw, re.I):
            add(raw_url, source)

    return found


def summarize_urls(items, query):
    query_hits = [
        x for x in items
        if token_match(f'{x.get("context", "")} {x.get("url", "")}', query)
    ]
    return {
        "all_count": len(items),
        "query_token_count": len(query_hits),
        "all_sample": items[:30],
        "query_sample": query_hits[:30],
    }


def inspect_jsonld(html):
    soup = BeautifulSoup(html or "", "html.parser")
    products = []
    errors = []
    for index, script in enumerate(soup.select('script[type="application/ld+json"]')):
        raw = script.get_text(strip=True)
        try:
            data = json.loads(raw)
        except Exception as exc:
            errors.append({"script_index": index, "error": f"{type(exc).__name__}: {exc}"})
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                typ = item.get("@type")
                if typ == "Product" or "offers" in item:
                    products.append(item)
                graph = item.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
    return {
        "product_objects": len(products),
        "names": [clean(x.get("name")) for x in products if x.get("name")][:20],
        "errors": errors[:20],
        "objects": [
            {
                "name": clean(x.get("name")),
                "type": x.get("@type"),
                "brand": x.get("brand"),
                "sku": x.get("sku"),
                "gtin": x.get("gtin13") or x.get("gtin"),
                "offers_type": type(x.get("offers")).__name__,
                "offers": x.get("offers") if isinstance(x.get("offers"), (dict, list)) else None,
            }
            for x in products[:10]
        ],
    }


def production_function_report(module):
    names = [
        "search", "scrape", "_discover", "_candidate_queries",
        "_candidate_product_urls", "_category_pages",
        "_category_page_variants", "_category_product_line_links",
        "_discover_from_categories", "_sitemap_category_urls",
        "_sitemap_product_urls", "_product", "_jsonld",
    ]
    out = {
        "module": getattr(module, "__name__", None),
        "file": getattr(module, "__file__", None),
        "BASE_URL": getattr(module, "BASE_URL", None),
        "TIMEOUT": getattr(module, "TIMEOUT", None),
        "MAX_PRODUCT_FETCHES": getattr(module, "MAX_PRODUCT_FETCHES", None),
        "DISCOVERY_MAX_CATEGORY_REQUESTS": getattr(module, "DISCOVERY_MAX_CATEGORY_REQUESTS", None),
        "functions": {},
    }
    for name in names:
        fn = getattr(module, name, None)
        item = {"exists": fn is not None, "callable": callable(fn)}
        if callable(fn):
            try:
                item["signature"] = str(inspect.signature(fn))
            except Exception:
                item["signature"] = None
            try:
                source = inspect.getsource(fn)
                item["source_lines"] = len(source.splitlines())
                item["source_sha1"] = __import__("hashlib").sha1(source.encode()).hexdigest()
            except Exception:
                item["source_lines"] = None
                item["source_sha1"] = None
        out["functions"][name] = item
    return out


def diagnose_product_gate(module, session, url, query):
    """Reconstruct the exact _product() gates without changing production code."""
    page = request_page(session, url)
    result = {
        "url": url,
        "http": {k: v for k, v in page.items() if k != "body"},
        "gate": None,
        "name": None,
        "query_match": None,
        "price": None,
        "jsonld": None,
        "production_product_result": None,
    }
    if not page["ok"]:
        result["gate"] = "HTTP_FAILED"
        return result

    html = page["body"]
    soup = BeautifulSoup(html, "html.parser")
    jsonld = inspect_jsonld(html)
    result["jsonld"] = jsonld

    h1 = soup.find("h1")
    h1_text = clean(h1.get_text(" ", strip=True)) if h1 else ""
    first_jsonld_name = next((x for x in jsonld["names"] if x), "")
    name = first_jsonld_name or h1_text
    result["name"] = {
        "jsonld_name": first_jsonld_name,
        "h1": h1_text,
        "selected_name": name,
    }

    name_match = token_match(name, query)
    result["query_match"] = name_match
    if not name:
        result["gate"] = "REJECTED_NAME_EMPTY"
    elif not name_match:
        result["gate"] = "REJECTED_NAME_QUERY_MISMATCH"

    # Mirror production price parsing as closely as possible.
    parse_price = getattr(module, "parse_price", None)
    text = soup.get_text(" ", strip=True)
    offers = []
    for obj in jsonld.get("objects", []):
        raw_offers = obj.get("offers")
        if isinstance(raw_offers, dict):
            offers.append(raw_offers)
        elif isinstance(raw_offers, list):
            offers.extend([x for x in raw_offers if isinstance(x, dict)])
    offer_price_raw = next((x.get("price") for x in offers if x.get("price") is not None), None)
    parsed_offer_price = None
    parsed_text_price = None
    if callable(parse_price):
        try:
            parsed_offer_price = parse_price(offer_price_raw)
        except Exception as exc:
            result["price_parse_error"] = f"offer: {type(exc).__name__}: {exc}"
        if parsed_offer_price is None:
            try:
                parsed_text_price = parse_price(text)
            except Exception as exc:
                result["price_parse_error_text"] = f"text: {type(exc).__name__}: {exc}"
    else:
        m = re.search(r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?", clean(offer_price_raw)) if offer_price_raw is not None else None
        parsed_offer_price = float(m.group(1).replace(",", ".")) if m else None

    price = parsed_offer_price if parsed_offer_price is not None else parsed_text_price
    result["price"] = {
        "jsonld_offer_price_raw": offer_price_raw,
        "parsed_offer_price": parsed_offer_price,
        "parsed_text_price": parsed_text_price,
        "selected_price": price,
    }

    if result["gate"] is None and price is None:
        result["gate"] = "REJECTED_PRICE_MISSING"

    # Run the actual production parser last, so the reconstructed gate and the real result can be compared.
    product_fn = getattr(module, "_product", None)
    if callable(product_fn):
        try:
            actual = product_fn(url, html, query)
            result["production_product_result"] = {
                "returned": actual is not None,
                "name": actual.get("name") if isinstance(actual, dict) else None,
                "price": actual.get("offer", {}).get("price") if isinstance(actual, dict) else None,
                "available": actual.get("available") if isinstance(actual, dict) else None,
            }
            if actual is not None:
                result["gate"] = "ACCEPTED_BY_PRODUCT"
            elif result["gate"] is None:
                result["gate"] = "REJECTED_BY_UNEXPLAINED_PRODUCT_LOGIC"
        except Exception as exc:
            result["production_product_result"] = {
                "returned": None,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            if result["gate"] is None:
                result["gate"] = "PRODUCT_PARSER_EXCEPTION"
    return result


def run_endpoint_probe(session, url, query, module):
    page = request_page(session, url)
    body = page["body"]
    broad = extract_broad_product_urls(body, getattr(module, "BASE_URL", "https://www.deloox.be"))
    structure = html_structure(body)
    structure["jsonld"] = inspect_jsonld(body)
    scraper_extractor = {}
    fn = getattr(module, "_candidate_product_urls", None)
    if callable(fn) and page["ok"]:
        for mode, kwargs in (
            ("production_default", {}),
            ("production_accept_all", {"accept_all_products": True}),
        ):
            try:
                value = fn(body, query, **kwargs)
                scraper_extractor[mode] = {
                    "count": len(value or []),
                    "urls": list(value or [])[:30],
                }
            except TypeError:
                try:
                    value = fn(body, query)
                    scraper_extractor[mode] = {
                        "count": len(value or []),
                        "urls": list(value or [])[:30],
                        "fallback_signature": True,
                    }
                except Exception as exc:
                    scraper_extractor[mode] = {"count": None, "urls": [], "error": f"{type(exc).__name__}: {exc}"}
            except Exception as exc:
                scraper_extractor[mode] = {"count": None, "urls": [], "error": f"{type(exc).__name__}: {exc}"}

    return {
        "http": {k: v for k, v in page.items() if k != "body"},
        "structure": structure,
        "broad_extractor": summarize_urls(broad, query),
        "production_extractor": scraper_extractor,
    }


def definitive_cause(report):
    integ = report.get("integration", {})
    candidates = integ.get("candidate_diagnostics", [])
    real_search = integ.get("real_scraper_search", {})

    for c in candidates:
        gate = c.get("gate")
        if gate in {"REJECTED_NAME_EMPTY", "REJECTED_NAME_QUERY_MISMATCH", "REJECTED_PRICE_MISSING", "PRODUCT_PARSER_EXCEPTION", "REJECTED_BY_UNEXPLAINED_PRODUCT_LOGIC"}:
            return {
                "status": "CAUSE_ISOLATED",
                "stage": "PRODUCT_VALIDATION",
                "code": gate,
                "evidence_url": c.get("url"),
                "reason": "Un candidato Deloox reale è stato raggiunto; il report mostra il gate esatto che lo elimina.",
            }

    discovery = integ.get("discovery_trace", {})
    if discovery.get("candidate_count") == 0:
        for step in discovery.get("steps", []):
            if step.get("candidate_count"):
                return {
                    "status": "CAUSE_ISOLATED",
                    "stage": "DISCOVERY_FILTER",
                    "code": "CANDIDATES_FOUND_THEN_LOST",
                    "reason": "Una fase precedente produce candidati ma una fase successiva li porta a zero.",
                    "step": step,
                }
        if any(x.get("production_extractor", {}).get("production_accept_all", {}).get("count", 0) > 0 for x in report.get("endpoint_tests", [])):
            return {
                "status": "CAUSE_ISOLATED",
                "stage": "PRODUCTION_CANDIDATE_FILTER",
                "code": "REAL_HTML_HAS_PRODUCTS_BUT_PRODUCTION_FILTER_REJECTS",
                "reason": "L'HTML contiene URL prodotto, ma l'estrattore reale non le accetta.",
            }

    if real_search.get("count") == 0 and integ.get("discover_return_count") == 0:
        return {
            "status": "NOT_YET_ISOLATED",
            "stage": "DISCOVERY",
            "code": "NO_CANDIDATE_REACHED_VALIDATION",
            "reason": "Nessun candidato è arrivato alla validazione prodotto; servono i dettagli delle singole strategie di discovery nel report.",
        }

    return {
        "status": "NOT_YET_ISOLATED",
        "stage": "UNKNOWN",
        "code": "NO_SINGLE_CAUSE_PROVEN",
        "reason": "Il diagnostico ha raccolto le prove ma non ha ancora una condizione sufficiente per dichiarare la causa.",
    }


@app.get("/")
def root():
    return {
        "status": "ok",
        "diagnostic": "Deloox CAUSAL / production scraper read-only",
        "endpoint": "/diagnose-deloox?q=Liquid%20Brun",
        "note": "Non modifica il production scraper.",
    }


@app.get("/diagnose-deloox")
def diagnose_deloox(q: str = DEFAULT_QUERY):
    query = clean(q)
    if not query:
        raise HTTPException(400, "Parametro q mancante")

    started = time.perf_counter()
    report = {
        "diagnostic_version": "deloox-causal-2.0",
        "query": query,
        "scraper": {},
        "endpoint_tests": [],
        "category_tests": [],
        "sitemap_tests": [],
        "integration": {},
    }

    try:
        module = importlib.import_module(SCRAPER_MODULE)
    except Exception as exc:
        report["scraper"] = {
            "import_error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        report["verdict"] = definitive_cause(report)
        return report

    report["scraper"] = production_function_report(module)
    base = str(getattr(module, "BASE_URL", "https://www.deloox.be")).rstrip("/")
    session = requests.Session()

    try:
        # 1) EXACT production search endpoints.
        search_urls = [
            f"{base}/en/search?query={quote_plus(query)}",
            f"{base}/en/search?search={quote_plus(query)}",
            f"{base}/en/search?q={quote_plus(query)}",
        ]
        for url in search_urls:
            report["endpoint_tests"].append(run_endpoint_probe(session, url, query, module))
            report["endpoint_tests"][-1]["strategy"] = "production_search_endpoint"
            report["endpoint_tests"][-1]["url"] = url

        # 2) EXACT category pages returned by the real scraper.
        category_fn = getattr(module, "_category_pages", None)
        category_urls = []
        if callable(category_fn):
            result = safe_call(category_fn, session)
            if result["status"] == "ERROR":
                result = safe_call(category_fn)
            category_urls = list(result.get("value") or []) if result["status"] == "OK" else []
        report["integration"]["production_category_urls"] = category_urls

        for category_url in category_urls[:12]:
            variants = [category_url]
            variants_fn = getattr(module, "_category_page_variants", None)
            if callable(variants_fn):
                try:
                    variants = list(variants_fn(category_url, max_pages=3) or [])
                except TypeError:
                    try:
                        variants = list(variants_fn(category_url) or [])
                    except Exception:
                        variants = [category_url]
                except Exception:
                    variants = [category_url]
            for url in variants[:3]:
                item = run_endpoint_probe(session, url, query, module)
                item["strategy"] = "production_category"
                item["url"] = url
                report["category_tests"].append(item)

        # 3) Run the REAL _discover() with cache cleared, but instrument its
        #    individual helpers separately. This tells us where candidates first appear.
        cache = getattr(module, "_SEARCH_CACHE", None)
        if isinstance(cache, dict):
            cache.clear()

        discovery_trace = {"steps": [], "candidate_count": 0, "return_candidates": []}

        candidate_queries_fn = getattr(module, "_candidate_queries", None)
        if callable(candidate_queries_fn):
            try:
                candidate_queries = list(candidate_queries_fn(query) or [])
            except Exception as exc:
                candidate_queries = [query]
                discovery_trace["candidate_queries_error"] = f"{type(exc).__name__}: {exc}"
        else:
            candidate_queries = [query]
        discovery_trace["candidate_queries"] = candidate_queries

        # Search endpoint -> production candidate extractor, with all-product mode.
        candidate_fn = getattr(module, "_candidate_product_urls", None)
        for dq in candidate_queries:
            for url in search_urls:
                page = request_page(session, url)
                if not page["ok"] or not callable(candidate_fn):
                    discovery_trace["steps"].append({
                        "strategy": "search_endpoint",
                        "query": dq,
                        "url": url,
                        "http_status": page["status"],
                        "candidate_count": 0,
                        "reason": page.get("error") or "HTTP_FAILED",
                    })
                    continue
                row = {"strategy": "search_endpoint", "query": dq, "url": url, "http_status": page["status"]}
                for mode, kwargs in (("default", {}), ("accept_all", {"accept_all_products": True})):
                    try:
                        values = list(candidate_fn(page["body"], dq, **kwargs) or [])
                        row[mode] = {"count": len(values), "urls": values[:30]}
                    except TypeError:
                        try:
                            values = list(candidate_fn(page["body"], dq) or [])
                            row[mode] = {"count": len(values), "urls": values[:30], "signature_fallback": True}
                        except Exception as exc:
                            row[mode] = {"count": None, "urls": [], "error": f"{type(exc).__name__}: {exc}"}
                    except Exception as exc:
                        row[mode] = {"count": None, "urls": [], "error": f"{type(exc).__name__}: {exc}"}
                discovery_trace["steps"].append(row)

        # Category helper directly, with its real signature.
        cat_discover = getattr(module, "_discover_from_categories", None)
        if callable(cat_discover):
            try:
                values = list(cat_discover(session, query, max_urls=20, max_category_requests=12) or [])
                discovery_trace["steps"].append({
                    "strategy": "production_category_discover",
                    "candidate_count": len(values),
                    "urls": values[:30],
                })
            except Exception as exc:
                discovery_trace["steps"].append({
                    "strategy": "production_category_discover",
                    "candidate_count": None,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                })

        # Sitemap helper directly.
        sitemap_fn = getattr(module, "_sitemap_product_urls", None)
        if callable(sitemap_fn):
            try:
                values = list(sitemap_fn(session, query, max_sitemaps=6, max_urls=30) or [])
                report["sitemap_tests"].append({
                    "strategy": "production_sitemap_products",
                    "candidate_count": len(values),
                    "urls": values[:30],
                })
                discovery_trace["steps"].append({
                    "strategy": "production_sitemap_products",
                    "candidate_count": len(values),
                    "urls": values[:30],
                })
            except Exception as exc:
                report["sitemap_tests"].append({
                    "strategy": "production_sitemap_products",
                    "candidate_count": None,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        # Real _discover return, after cache clear.
        discover_fn = getattr(module, "_discover", None)
        if callable(discover_fn):
            try:
                discovered = list(discover_fn(session, query) or [])
                discovery_trace["candidate_count"] = len(discovered)
                discovery_trace["return_candidates"] = discovered[:40]
            except Exception as exc:
                discovery_trace["discover_error"] = f"{type(exc).__name__}: {exc}"
                discovery_trace["discover_traceback"] = traceback.format_exc()

        report["integration"]["discovery_trace"] = discovery_trace
        report["integration"]["discover_return_count"] = discovery_trace.get("candidate_count", 0)

        # 4) Candidate diagnostics: for every real candidate we can obtain,
        #    expose the exact _product() rejection gate.
        candidate_urls = []
        for step in discovery_trace.get("steps", []):
            for key in ("default", "accept_all"):
                data = step.get(key) or {}
                candidate_urls.extend(data.get("urls") or [])
            candidate_urls.extend(step.get("urls") or [])
        candidate_urls.extend(discovery_trace.get("return_candidates") or [])
        for item in report["endpoint_tests"] + report["category_tests"]:
            for group in (item.get("broad_extractor", {}).get("query_sample", []), item.get("broad_extractor", {}).get("all_sample", [])):
                candidate_urls.extend(x.get("url") for x in group if x.get("url"))
        candidate_urls = list(dict.fromkeys(candidate_urls))[:20]

        report["integration"]["candidate_urls_for_validation"] = candidate_urls
        report["integration"]["candidate_diagnostics"] = [
            diagnose_product_gate(module, session, url, query)
            for url in candidate_urls
        ]

        # 5) Actual production search() after cache clear.
        if isinstance(cache, dict):
            cache.clear()
        search_fn = getattr(module, "search", None)
        if callable(search_fn):
            started_search = time.perf_counter()
            try:
                actual = list(search_fn(query) or [])
                report["integration"]["real_scraper_search"] = {
                    "count": len(actual),
                    "elapsed_ms": round((time.perf_counter() - started_search) * 1000, 1),
                    "sample": actual[:10],
                    "error": None,
                }
            except Exception as exc:
                report["integration"]["real_scraper_search"] = {
                    "count": None,
                    "elapsed_ms": round((time.perf_counter() - started_search) * 1000, 1),
                    "sample": [],
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }

        report["verdict"] = definitive_cause(report)
        report["elapsed_total_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return report
    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="ScentHunter Deloox causal diagnostic")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
