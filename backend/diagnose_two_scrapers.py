from fastapi import APIRouter, Query
import concurrent.futures
import importlib.util
import json
import os
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
def diagnose_sabina_runtime(qs: str = Query("9 PM|Liquid Brun|Hawas")):
    """Bounded, read-only Sabina diagnostic.

    It deliberately does NOT call search() and search_stream() together.
    The endpoint first tests the real search HTTP surface and then executes
    discover_product_urls() at most once per query with a hard diagnostic
    timeout. A timeout is returned as data instead of leaving the HTTP request
    hanging.
    """
    started = time.monotonic()
    queries = []
    seen = set()
    for raw in (qs or "").split("|")[:12]:
        q = raw.strip()
        if q and q.casefold() not in seen:
            seen.add(q.casefold())
            queries.append(q)

    scraper_path = os.path.join(
        os.path.dirname(__file__), "scrapers", "sabina", "scraper.py"
    )
    out = {
        "diagnostic": True,
        "store": "Sabina",
        "queries": queries,
        "scraper_file": scraper_path,
        "query_results": [],
    }

    spec = importlib.util.spec_from_file_location(
        "scent_hunter_sabina_runtime_diag", scraper_path
    )
    module = None
    if spec is None or spec.loader is None:
        out["import"] = {"ok": False, "error": "Could not load Sabina scraper"}
    else:
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            out["import"] = {"ok": True, "module_file": getattr(module, "__file__", None)}
        except Exception as exc:
            out["import"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            module = None

    base = getattr(module, "BASE_URL", None) or getattr(module, "BASE", "https://www.sabina.com")
    search_url = getattr(module, "SEARCH_URL", base.rstrip("/") + "/es/buscar")
    headers = getattr(module, "HEADERS", HEADERS)

    for q in queries:
        qr = {"query": q, "http": {}, "discovery": {}}
        t0 = time.monotonic()
        try:
            r = requests.get(
                search_url,
                params={"search_query": q},
                headers=headers,
                timeout=(2.5, 7.0),
                allow_redirects=True,
            )
            html = r.text or ""
            qr["http"] = {
                "ok": True,
                "status": r.status_code,
                "requested_url": r.url,
                "elapsed_sec": round(time.monotonic() - t0, 3),
                "bytes": len(r.content),
                "query_occurrences": html.casefold().count(q.casefold()),
                "classification": "http_error" if r.status_code >= 400 else "http_response_received",
            }
            r.close()
        except requests.Timeout as exc:
            qr["http"] = {"ok": False, "classification": "timeout", "elapsed_sec": round(time.monotonic()-t0,3), "error": f"{type(exc).__name__}: {exc}"}
        except requests.RequestException as exc:
            qr["http"] = {"ok": False, "classification": "request_error", "elapsed_sec": round(time.monotonic()-t0,3), "error": f"{type(exc).__name__}: {exc}"}

        discover = getattr(module, "discover_product_urls", None) if module else None
        if not callable(discover):
            qr["discovery"] = {"ok": False, "classification": "missing_discover_product_urls"}
        else:
            holder = {}
            def _run_discovery():
                try:
                    holder["value"] = discover(q)
                except Exception as exc:
                    holder["error"] = f"{type(exc).__name__}: {exc}"

            thread = __import__("threading").Thread(target=_run_discovery, daemon=True)
            t1 = time.monotonic()
            thread.start()
            thread.join(timeout=12.0)
            if thread.is_alive():
                qr["discovery"] = {
                    "ok": False,
                    "classification": "diagnostic_timeout",
                    "elapsed_sec": round(time.monotonic()-t1, 3),
                    "error": "discover_product_urls did not return within 12s",
                }
            elif "error" in holder:
                qr["discovery"] = {
                    "ok": False,
                    "classification": "scraper_exception",
                    "elapsed_sec": round(time.monotonic()-t1, 3),
                    "error": holder["error"],
                }
            else:
                value = holder.get("value")
                qr["discovery"] = {
                    "ok": True,
                    "classification": "urls_found" if value else "verified_empty",
                    "elapsed_sec": round(time.monotonic()-t1, 3),
                    "type": type(value).__name__,
                    "count": len(value) if isinstance(value, list) else None,
                    "urls": value[:50] if isinstance(value, list) else value,
                }

        out["query_results"].append(qr)

    out["elapsed_sec"] = round(time.monotonic() - started, 3)
    return out

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
