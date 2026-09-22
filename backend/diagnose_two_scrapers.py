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


@router.get("/diagnose-sabina-pipeline")
def diagnose_sabina_pipeline(q: str = Query("Liquid Brun")):
    """Read-only trace of the Sabina scraper pipeline.

    This route does not modify the production scraper. It imports the current
    Sabina scraper and reports what each parser stage produces.
    """
    import importlib.util
    import os

    started = time.monotonic()
    scraper_path = os.path.join(
        os.path.dirname(__file__),
        "scrapers",
        "sabina",
        "scraper.py",
    )

    spec = importlib.util.spec_from_file_location(
        "scent_hunter_sabina_pipeline_diag",
        scraper_path,
    )
    if spec is None or spec.loader is None:
        return {
            "diagnostic": True,
            "store": "Sabina",
            "query": q,
            "stage": "import",
            "error": "Could not load Sabina scraper",
        }

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        return {
            "diagnostic": True,
            "store": "Sabina",
            "query": q,
            "stage": "import",
            "error": f"{type(exc).__name__}: {exc}",
        }

    base = getattr(module, "BASE", "https://www.sabina.com")
    headers = getattr(module, "HEADERS", HEADERS)
    url = base + "/it/ricerca_old?search_query=" + quote(q)

    result = {
        "diagnostic": True,
        "store": "Sabina",
        "query": q,
        "purpose": "read-only pipeline trace; no production mutation",
        "scraper_file": scraper_path,
        "stages": {},
    }

    page = _get(url, timeout=(2.0, 8.0), headers=headers)
    result["stages"]["http"] = {
        "ok": page["ok"],
        "status": page["status"],
        "url": page["url"],
        "elapsed_sec": page["elapsed_sec"],
        "bytes": page["bytes"],
        "error": page["error"],
    }

    if not page["ok"] or page["status"] != 200:
        result["elapsed_sec"] = round(time.monotonic() - started, 3)
        return result

    text = page["text"]

    try:
        impressions = module._parse_datalayer_impressions(text)
        result["stages"]["dataLayer"] = {
            "count": len(impressions),
            "items": impressions[:20],
        }
    except Exception as exc:
        result["stages"]["dataLayer"] = {
            "count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }
        impressions = []

    try:
        parsed = module._parse_html(text, q)
        result["stages"]["parse_html"] = {
            "count": len(parsed) if isinstance(parsed, list) else None,
            "rows": parsed[:20] if isinstance(parsed, list) else parsed,
        }
    except Exception as exc:
        result["stages"]["parse_html"] = {
            "count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }

    try:
        import requests as _requests
        session = _requests.Session()
        session.headers.update(headers)
        queries = [q]
        query_without_size = module._clean(
            re.sub(r"(?<!\d)\d{2,4}\s*ml\b", " ", q, flags=re.I)
        )
        if query_without_size and query_without_size.casefold() != q.casefold():
            queries.append(query_without_size)

        urls = []
        for search_query in queries:
            urls.extend([
                base + "/it/ricerca?search_query=" + quote(search_query),
                base + "/it/ricerca_old?s=" + quote(search_query),
                base + "/it/ricerca_old?search_query=" + quote(search_query),
            ])

        flow = []
        accumulated = []
        for search_url in urls:
            step = {"url": search_url}
            try:
                t0 = time.monotonic()
                r = module._get(session, search_url)
                step["elapsed_sec"] = round(time.monotonic() - t0, 3)
                step["status"] = None if r is None else r.status_code
                if r is None:
                    step["result"] = "request_returned_none"
                    flow.append(step)
                    continue

                html = r.text
                step["bytes"] = len(r.content)
                r.close()

                try:
                    parsed_url_rows = module._parse_html(html, q)
                    step["parse_html_count"] = len(parsed_url_rows)
                    step["parse_html_rows"] = parsed_url_rows[:10]
                    accumulated.extend(parsed_url_rows)
                except Exception as exc:
                    step["parse_html_error"] = f"{type(exc).__name__}: {exc}"
                    flow.append(step)
                    continue

                try:
                    deduped = module._dedupe(accumulated, q)
                    step["dedupe_count"] = len(deduped)
                    step["dedupe_rows"] = deduped[:10]
                except Exception as exc:
                    step["dedupe_error"] = f"{type(exc).__name__}: {exc}"
                    flow.append(step)
                    continue

                if deduped:
                    try:
                        enriched = module._enrich_product_sizes(session, deduped, q)
                        step["enrich_count"] = len(enriched)
                        step["enrich_rows"] = enriched[:10]
                    except Exception as exc:
                        step["enrich_error"] = f"{type(exc).__name__}: {exc}"
                flow.append(step)
            except Exception as exc:
                step["exception"] = f"{type(exc).__name__}: {exc}"
                flow.append(step)

        session.close()
        result["stages"]["search_flow"] = {
            "url_count": len(urls),
            "steps": flow,
            "accumulated_final_count": len(accumulated),
        }
    except Exception as exc:
        result["stages"]["search_flow"] = {
            "error": f"{type(exc).__name__}: {exc}",
        }

    try:
        searched = module.search(q)
        result["stages"]["search"] = {
            "count": len(searched) if isinstance(searched, list) else None,
            "rows": searched[:20] if isinstance(searched, list) else searched,
        }
    except Exception as exc:
        result["stages"]["search"] = {
            "count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }

    try:
        streamed = module.search_stream(q)
        result["stages"]["search_stream"] = {
            "type": type(streamed).__name__,
            "result": streamed,
        }
    except Exception as exc:
        result["stages"]["search_stream"] = {
            "type": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }

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


@router.get("/diagnose-deloox-pipeline")
def diagnose_deloox_pipeline(q: str = Query("Liquid Brun")):
    """Read-only trace of the current Deloox production scraper pipeline.

    Traces discovery -> candidate HTTP fetch -> _product parsing -> search().
    It does not modify the production scraper and contains no product-specific
    business rule.
    """
    import importlib.util
    import os
    import requests as _requests

    started = time.monotonic()
    scraper_path = os.path.join(
        os.path.dirname(__file__),
        "scrapers",
        "deloox",
        "scraper.py",
    )

    result = {
        "diagnostic": True,
        "store": "Deloox",
        "query": q,
        "purpose": "read-only trace of current Deloox scraper: _discover -> HTTP -> _product -> search",
        "scraper_file": scraper_path,
        "stages": {},
    }

    spec = importlib.util.spec_from_file_location(
        "scent_hunter_deloox_pipeline_diag",
        scraper_path,
    )
    if spec is None or spec.loader is None:
        result["stages"]["import"] = {
            "ok": False,
            "error": "Could not load Deloox scraper",
        }
        result["elapsed_sec"] = round(time.monotonic() - started, 3)
        return result

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        result["stages"]["import"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        result["elapsed_sec"] = round(time.monotonic() - started, 3)
        return result

    result["stages"]["import"] = {
        "ok": True,
        "module": getattr(module, "__file__", None),
        "has_discover": hasattr(module, "_discover"),
        "has_product": hasattr(module, "_product"),
        "has_search": hasattr(module, "search"),
    }

    session = None
    candidates = []

    try:
        session = _requests.Session()
        if hasattr(module, "HEADERS"):
            session.headers.update(getattr(module, "HEADERS"))

        t0 = time.monotonic()
        candidates = module._discover(session, q)
        result["stages"]["discover"] = {
            "ok": True,
            "elapsed_sec": round(time.monotonic() - t0, 3),
            "type": type(candidates).__name__,
            "count": len(candidates) if isinstance(candidates, list) else None,
            "urls": candidates[:100] if isinstance(candidates, list) else candidates,
        }
    except Exception as exc:
        result["stages"]["discover"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        candidates = []

    candidate_results = []
    if isinstance(candidates, list):
        for index, url in enumerate(candidates[:100]):
            item = {
                "index": index,
                "url": url,
            }
            try:
                t0 = time.monotonic()
                response = session.get(
                    url,
                    timeout=getattr(module, "TIMEOUT", 4),
                    allow_redirects=True,
                )
                item["http_elapsed_sec"] = round(time.monotonic() - t0, 3)
                item["status"] = response.status_code
                item["final_url"] = response.url
                item["bytes"] = len(response.content)

                if response.status_code >= 400:
                    item["parser_result"] = "skipped_http_error"
                else:
                    try:
                        parsed = module._product(response.url, response.text, q)
                        item["parser_result"] = "matched" if parsed else "rejected_or_none"
                        if parsed:
                            item["product"] = parsed
                    except Exception as exc:
                        item["parser_result"] = "exception"
                        item["parser_error"] = f"{type(exc).__name__}: {exc}"
                response.close()
            except Exception as exc:
                item["http_error"] = f"{type(exc).__name__}: {exc}"
            candidate_results.append(item)

    status_values = [x.get("status") for x in candidate_results if x.get("status") is not None]
    result["stages"]["candidate_fetch_and_product"] = {
        "candidate_count": len(candidate_results),
        "matched_count": sum(1 for x in candidate_results if x.get("parser_result") == "matched"),
        "http_error_count": sum(1 for x in candidate_results if "http_error" in x),
        "http_status_counts": {
            str(code): sum(1 for x in candidate_results if x.get("status") == code)
            for code in sorted(set(status_values))
        },
        "items": candidate_results,
    }

    try:
        t0 = time.monotonic()
        searched = module.search(q)
        result["stages"]["search"] = {
            "ok": True,
            "elapsed_sec": round(time.monotonic() - t0, 3),
            "type": type(searched).__name__,
            "count": len(searched) if isinstance(searched, list) else None,
            "rows": searched[:20] if isinstance(searched, list) else searched,
        }
    except Exception as exc:
        result["stages"]["search"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if session is not None:
        try:
            session.close()
        except Exception:
            pass

    result["elapsed_sec"] = round(time.monotonic() - started, 3)
    return result
