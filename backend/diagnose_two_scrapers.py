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
def diagnose_sabina_runtime(qs: str = Query("9 PM|Liquid Brun|Hawas")):
    """Read-only diagnostic of the deployed Sabina discovery path.

    IMPORTANT: Sabina's discover_product_urls() contract is
    discover_product_urls(session, query). The diagnostic must create and
    pass the same kind of Session used by production search().
    """
    import importlib.util
    import os

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
    result = {
        "diagnostic": True,
        "store": "Sabina",
        "scraper_file": scraper_path,
        "queries": queries,
        "query_results": [],
    }

    spec = importlib.util.spec_from_file_location(
        "scent_hunter_sabina_runtime_diag", scraper_path
    )
    module = None
    if spec is None or spec.loader is None:
        result["import"] = {"ok": False, "error": "Could not load Sabina scraper"}
        result["elapsed_sec"] = round(time.monotonic() - started, 3)
        return result

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        result["import"] = {"ok": True, "module_file": getattr(module, "__file__", None)}
    except Exception as exc:
        result["import"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        result["elapsed_sec"] = round(time.monotonic() - started, 3)
        return result

    base = getattr(module, "BASE_URL", "https://www.sabina.com")
    search_url = getattr(module, "SEARCH_URL", base.rstrip("/") + "/es/buscar")
    headers = getattr(module, "HEADERS", HEADERS)
    discover = getattr(module, "discover_product_urls", None)

    if not callable(discover):
        result["discovery_contract"] = {"ok": False, "error": "discover_product_urls_missing"}
        result["elapsed_sec"] = round(time.monotonic() - started, 3)
        return result

    for q in queries:
        qr = {"query": q, "http": {}, "discovery": {}}

        t0 = time.monotonic()
        try:
            response = requests.get(
                search_url,
                params={"search_query": q},
                headers=headers,
                timeout=(2.5, 10.0),
                allow_redirects=True,
            )
            html = response.text or ""
            qr["http"] = {
                "ok": True,
                "status": response.status_code,
                "requested_url": response.url,
                "elapsed_sec": round(time.monotonic() - t0, 3),
                "bytes": len(response.content),
                "query_occurrences": html.casefold().count(q.casefold()),
                "classification": (
                    "http_error" if response.status_code >= 400
                    else "empty_http_body" if not html
                    else "http_response_received"
                ),
            }
            response.close()
        except requests.Timeout as exc:
            qr["http"] = {"ok": False, "classification": "timeout", "elapsed_sec": round(time.monotonic()-t0,3), "error": f"{type(exc).__name__}: {exc}"}
        except requests.RequestException as exc:
            qr["http"] = {"ok": False, "classification": "request_error", "elapsed_sec": round(time.monotonic()-t0,3), "error": f"{type(exc).__name__}: {exc}"}

        # Production discovery uses a Session. The previous diagnostic called
        # discover_product_urls(q), which is invalid for the deployed scraper.
        session = requests.Session()
        try:
            session.headers.update(headers)
            t0 = time.monotonic()
            discovered = discover(session, q)
            qr["discovery"] = {
                "ok": True,
                "elapsed_sec": round(time.monotonic() - t0, 3),
                "type": type(discovered).__name__,
                "count": len(discovered) if isinstance(discovered, list) else None,
                "urls": discovered[:50] if isinstance(discovered, list) else discovered,
            }
        except requests.Timeout as exc:
            qr["discovery"] = {"ok": False, "classification": "timeout", "error": f"{type(exc).__name__}: {exc}"}
        except requests.RequestException as exc:
            qr["discovery"] = {"ok": False, "classification": "request_error", "error": f"{type(exc).__name__}: {exc}"}
        except Exception as exc:
            qr["discovery"] = {"ok": False, "classification": "scraper_exception", "error": f"{type(exc).__name__}: {exc}"}
        finally:
            session.close()

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
