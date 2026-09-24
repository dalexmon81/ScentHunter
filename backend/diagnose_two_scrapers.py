from fastapi import APIRouter, Query
import concurrent.futures
import json
import re
import time
from urllib.parse import quote, urljoin

import requests

router = APIRouter()

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"}
TOKEN_RE = re.compile(r"\b(liquid|brun)\b", re.I)

def _get(url, timeout=(1.5, 5.0), headers=None):
    t = time.monotonic()
    try:
        r = requests.get(url, headers=headers or HEADERS, timeout=timeout, allow_redirects=True)
        return {
            "ok": True,
            "status": r.status_code,
            "url": r.url,
            "elapsed_sec": round(time.monotonic()-t, 3),
            "bytes": len(r.content),
            "text": r.text,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "elapsed_sec": round(time.monotonic()-t, 3),
            "bytes": 0,
            "text": "",
            "error": f"{type(e).__name__}: {e}",
        }

def _compact(s, n=500):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:n]

@router.get("/diagnose-sabina-catalog")
def diagnose_sabina_precise(q: str = Query("Liquid Brun")):
    base = "https://www.sabina.com"
    urls = [
        f"{base}/it/ricerca_old?s={quote(q)}",
        f"{base}/it/ricerca?search_query={quote(q)}",
        f"{base}/it/ricerca_old?search_query={quote(q)}",
    ]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        pages = list(ex.map(lambda u: _get(u), urls))

    probes = []
    for p in pages:
        text = p["text"]
        low = text.lower()
        hits = {}
        for marker in [q, "liquid brun", "liquid-brun", "34982", "720100",
                       "french avenue", "profumi-da-uomo", "/it/profumi-da-uomo/"]:
            i = low.find(marker.lower())
            hits[marker] = None if i < 0 else {
                "offset": i,
                "context": _compact(text[max(0, i-350):i+700], 1050)
            }

        # Inspect links around product-like references.
        links = []
        for m in re.finditer(r'href=["\']([^"\']+)["\']', text, re.I):
            href = m.group(1)
            if any(x in href.lower() for x in ["34982", "liquid", "brun", "profumi-da-uomo"]):
                links.append(urljoin(p["url"], href))
        probes.append({
            "url": p["url"],
            "status": p["status"],
            "elapsed_sec": p["elapsed_sec"],
            "bytes": p["bytes"],
            "error": p["error"],
            "markers": hits,
            "matching_links": list(dict.fromkeys(links))[:50],
        })

    return {
        "diagnostic": True,
        "store": "Sabina",
        "query": q,
        "elapsed_sec": round(time.monotonic()-started, 3),
        "purpose": "read-only inspection of real search responses; no production search() and no product-specific rule",
        "probes": probes,
    }

@router.get("/diagnose-sabina-runtime")
def diagnose_sabina_runtime(
    qs: str = Query("9 PM|Liquid Brun|Hawas")
):
    """Read-only runtime diagnosis of the current Sabina discovery/search path.

    It deliberately does not modify the production scraper. It captures the
    real HTTP response from Sabina's search surfaces and, when possible,
    invokes the current scraper discovery/search functions while preserving
    exceptions and HTTP status information instead of converting failures into
    empty results.
    """
    import importlib.util
    import os
    import requests as _requests

    started = time.monotonic()

    raw_queries = [x.strip() for x in (qs or "").split("|") if x.strip()]
    queries = []
    seen = set()
    for q in raw_queries[:12]:
        key = q.casefold()
        if key not in seen:
            seen.add(key)
            queries.append(q)

    scraper_path = os.path.join(
        os.path.dirname(__file__),
        "scrapers",
        "sabina",
        "scraper.py",
    )

    result = {
        "diagnostic": True,
        "store": "Sabina",
        "purpose": "read-only runtime diagnosis; no production mutation",
        "scraper_file": scraper_path,
        "queries": queries,
        "query_results": [],
    }

    # Load the exact production scraper currently deployed with this app.
    spec = importlib.util.spec_from_file_location(
        "scent_hunter_sabina_runtime_diag",
        scraper_path,
    )
    module = None
    if spec is None or spec.loader is None:
        result["import"] = {
            "ok": False,
            "error": "Could not load Sabina scraper",
        }
    else:
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            result["import"] = {
                "ok": True,
                "module_file": getattr(module, "__file__", None),
            }
        except Exception as exc:
            result["import"] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            module = None

    base = getattr(module, "BASE_URL", None) or getattr(
        module, "BASE", "https://www.sabina.com"
    )
    search_url = getattr(
        module,
        "SEARCH_URL",
        base.rstrip("/") + "/es/buscar",
    )
    headers = getattr(module, "HEADERS", HEADERS)

    for q in queries:
        qr = {
            "query": q,
            "http_surfaces": [],
            "scraper": {},
        }

        # Probe the same generic search surfaces without treating an error
        # as an empty result.
        surfaces = [
            {
                "name": "production_search_url",
                "url": search_url,
                "params": {"search_query": q},
            },
            {
                "name": "it_search",
                "url": base.rstrip("/") + "/it/ricerca",
                "params": {"search_query": q},
            },
            {
                "name": "it_search_old_s",
                "url": base.rstrip("/") + "/it/ricerca_old",
                "params": {"s": q},
            },
            {
                "name": "it_search_old_query",
                "url": base.rstrip("/") + "/it/ricerca_old",
                "params": {"search_query": q},
            },
        ]

        for surface in surfaces:
            item = {
                "name": surface["name"],
                "url": surface["url"],
                "params": surface["params"],
            }
            t0 = time.monotonic()
            try:
                r = _requests.get(
                    surface["url"],
                    params=surface["params"],
                    headers=headers,
                    timeout=(2.5, 10.0),
                    allow_redirects=True,
                )
                html = r.text or ""
                item.update({
                    "ok": True,
                    "status": r.status_code,
                    "requested_url": r.url,
                    "elapsed_sec": round(time.monotonic() - t0, 3),
                    "bytes": len(r.content),
                    "content_type": r.headers.get("content-type"),
                    "server": r.headers.get("server"),
                    "location": r.headers.get("location"),
                })

                # Generic product URL extraction based on the current
                # scraper's URL contract, not on a particular product.
                product_re = getattr(module, "PRODUCT_URL_RE", None)
                if product_re is not None:
                    try:
                        matches = list(product_re.finditer(html))
                        urls = []
                        for m in matches:
                            try:
                                raw = m.group(0)
                            except Exception:
                                raw = None
                            if raw:
                                urls.append(urljoin(r.url, raw))
                        item["production_regex_match_count"] = len(matches)
                        item["production_regex_urls"] = list(
                            dict.fromkeys(urls)
                        )[:50]
                    except Exception as exc:
                        item["production_regex_error"] = (
                            f"{type(exc).__name__}: {exc}"
                        )

                # Generic anchor inspection. This is diagnostic only.
                links = []
                for m in re.finditer(
                    r'href=["\']([^"\']+)["\']',
                    html,
                    re.I,
                ):
                    href = m.group(1)
                    absolute = urljoin(r.url, href)
                    if re.search(
                        r"/(?:es|it|fr|en|de|nl|pt)/[^/]+/\d+-[^/]+\.html$",
                        absolute,
                        re.I,
                    ):
                        links.append(absolute)

                item["generic_product_url_count"] = len(
                    list(dict.fromkeys(links))
                )
                item["generic_product_urls"] = list(
                    dict.fromkeys(links)
                )[:50]

                # Query occurrence is informational only; it is not used to
                # decide whether the store has a product.
                item["query_occurrences"] = html.casefold().count(
                    q.casefold()
                )

                if r.status_code >= 400:
                    item["classification"] = "http_error"
                elif not html:
                    item["classification"] = "empty_http_body"
                else:
                    item["classification"] = "http_response_received"

                r.close()
            except _requests.Timeout as exc:
                item.update({
                    "ok": False,
                    "classification": "timeout",
                    "elapsed_sec": round(time.monotonic() - t0, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                })
            except _requests.ConnectionError as exc:
                item.update({
                    "ok": False,
                    "classification": "unavailable",
                    "elapsed_sec": round(time.monotonic() - t0, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                })
            except _requests.RequestException as exc:
                item.update({
                    "ok": False,
                    "classification": "request_error",
                    "elapsed_sec": round(time.monotonic() - t0, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                })
            except Exception as exc:
                item.update({
                    "ok": False,
                    "classification": "exception",
                    "elapsed_sec": round(time.monotonic() - t0, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                })

            qr["http_surfaces"].append(item)

        if module is not None:
            # Trace discovery if the current scraper exposes it.
            discover = getattr(module, "discover_product_urls", None)
            if callable(discover):
                try:
                    t0 = time.monotonic()
                    discovered = discover(q)
                    qr["scraper"]["discover_product_urls"] = {
                        "ok": True,
                        "elapsed_sec": round(time.monotonic() - t0, 3),
                        "type": type(discovered).__name__,
                        "count": (
                            len(discovered)
                            if isinstance(discovered, list)
                            else None
                        ),
                        "urls": (
                            discovered[:50]
                            if isinstance(discovered, list)
                            else discovered
                        ),
                    }
                except Exception as exc:
                    qr["scraper"]["discover_product_urls"] = {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }

            # Trace the current production search separately.
            search = getattr(module, "search", None)
            if callable(search):
                try:
                    t0 = time.monotonic()
                    rows = search(q)
                    qr["scraper"]["search"] = {
                        "ok": True,
                        "elapsed_sec": round(time.monotonic() - t0, 3),
                        "type": type(rows).__name__,
                        "count": (
                            len(rows) if isinstance(rows, list) else None
                        ),
                        "rows": (
                            rows[:20] if isinstance(rows, list) else rows
                        ),
                    }
                except Exception as exc:
                    qr["scraper"]["search"] = {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }

            search_stream = getattr(module, "search_stream", None)
            if callable(search_stream):
                try:
                    t0 = time.monotonic()
                    streamed = search_stream(q)
                    qr["scraper"]["search_stream"] = {
                        "ok": True,
                        "elapsed_sec": round(time.monotonic() - t0, 3),
                        "type": type(streamed).__name__,
                        "result": streamed,
                    }
                except Exception as exc:
                    qr["scraper"]["search_stream"] = {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }

        result["query_results"].append(qr)

    result["elapsed_sec"] = round(time.monotonic() - started, 3)
    return result

@router.get("/diagnose-deloox-catalog")
def diagnose_deloox_precise(q: str = Query("Liquid Brun")):
    urls = [
        "https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html",
        "https://www.deloox.com/en/category/1121322/french-avenue-fragrances.html",
        "https://www.deloox.com/en/category/1132834/liquid-brun.html",
    ]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        pages = list(ex.map(lambda u: _get(u, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}), urls))

    out = []
    for p in pages:
        text = p["text"]
        low = text.lower()
        # Capture product-card-like anchors whose nearby text contains a query token.
        matches = []
        for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S):
            href, inner = m.group(1), m.group(2)
            visible = re.sub(r"<[^>]+>", " ", inner)
            visible = _compact(visible, 800)
            if TOKEN_RE.search(visible):
                matches.append({
                    "url": urljoin(p["url"], href),
                    "text": visible,
                })
        # Also locate raw occurrences in page text, independent of href.
        raw_contexts = []
        for m in list(TOKEN_RE.finditer(text))[:20]:
            raw_contexts.append(_compact(text[max(0, m.start()-300):m.end()+500], 900))
        out.append({
            "url": p["url"],
            "status": p["status"],
            "elapsed_sec": p["elapsed_sec"],
            "bytes": p["bytes"],
            "error": p["error"],
            "card_token_hits": matches[:50],
            "raw_token_contexts": raw_contexts,
        })

    return {
        "diagnostic": True,
        "store": "Deloox",
        "query": q,
        "elapsed_sec": round(time.monotonic()-started, 3),
        "purpose": "read-only inspection of category/card text; no URL-token discovery and no production search()",
        "pages": out,
    }
