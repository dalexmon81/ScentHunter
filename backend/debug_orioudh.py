"""Temporary Orioudh diagnostic. No production scraper logic is changed."""
import json
import re
from urllib.parse import urljoin
import requests
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/debug", tags=["debug"])
BASE_URL = "https://orioudh.com"
TIMEOUT = 8
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}

def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()

def gate_diagnostics(scraper, product, variant, url, q):
    name = scraper.clean(product.get("title"))
    vname = scraper.clean(variant.get("title"))
    ptype = scraper.clean(product.get("product_type"))
    haystack = scraper.norm(f"{name} {vname} {ptype}")
    match_text = f"{name} {product.get('vendor','')} {url}"
    gates = {
        "mystery_or_gift": bool(re.search(r"\bmystery\s+box\b|\bgift\s+set\b", haystack)),
        "matches_query": scraper.matches(match_text, q),
        "price": scraper.price(variant.get("price")),
        "available": variant.get("available"),
        "title": name,
        "vendor": product.get("vendor"),
        "variant_title": vname,
        "variant_id": variant.get("id"),
        "sku": variant.get("sku"),
        "raw_price": variant.get("price"),
    }
    try:
        item = scraper._item(product, variant, url)
        gates["item_ok"] = isinstance(item, dict)
        if item:
            gates["item_name"] = item.get("name")
            gates["item_price"] = item.get("price")
            gates["item_available"] = item.get("available")
    except Exception as exc:
        gates["item_ok"] = False
        gates["item_error"] = f"{type(exc).__name__}: {exc}"
    return gates

def diagnose_endpoints(query="Hawas"):
    q = clean(query)
    result = {
        "diagnostic": True,
        "store": "Orioudh",
        "query": q,
        "purpose": "Direct pipeline test: _discover -> _product_json -> _item -> search -> search_stream",
        "endpoints": {},
    }
    if not q:
        result["error"] = "Empty query"
        return result

    # Runtime bootstrap check: sitecustomize should normally be auto-loaded by
    # Python before uvicorn starts. We first observe that state, then explicitly
    # import it ONLY inside this diagnostic request so we can prove whether the
    # adapter installs successfully. This does not edit production source.
    import os
    import sys
    import importlib

    result["runtime"] = {
        "cwd": os.getcwd(),
        "python_executable": sys.executable,
        "sitecustomize_in_sys_modules_before": "sitecustomize" in sys.modules,
        "sys_path_head": sys.path[:12],
    }

    try:
        sc = importlib.import_module("sitecustomize")
        result["runtime"]["sitecustomize_import"] = "ok"
        result["runtime"]["sitecustomize_file"] = getattr(sc, "__file__", None)
    except Exception as exc:
        result["runtime"]["sitecustomize_import"] = "error"
        result["runtime"]["sitecustomize_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from scrapers.orioudh import scraper
    except Exception as exc:
        result["scraper_import_error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["scraper_module"] = getattr(scraper, "__file__", None)
    result["search_stream_present"] = callable(getattr(scraper, "search_stream", None))
    result["search_stream_object"] = repr(getattr(scraper, "search_stream", None))

    with requests.Session() as session:
        try:
            discovered = scraper._discover(session, q)
            result["pipeline_discover"] = {
                "ok": True, "count": len(discovered), "urls": discovered[:8]
            }
        except Exception as exc:
            result["pipeline_discover"] = {
                "ok": False, "error": f"{type(exc).__name__}: {exc}"
            }
            discovered = []

        products_out = []
        for url in discovered[:8]:
            entry = {"url": url}
            try:
                data = scraper._product_json(session, url)
                entry["product_json_ok"] = isinstance(data, dict)
                if isinstance(data, dict):
                    entry["product"] = {
                        "title": data.get("title"),
                        "vendor": data.get("vendor"),
                        "handle": data.get("handle"),
                        "id": data.get("id"),
                        "variant_count": len(data.get("variants") or []),
                    }
                    entry["variants"] = [
                        gate_diagnostics(scraper, data, v, url, q)
                        for v in (data.get("variants") or [])
                        if isinstance(v, dict)
                    ]
                else:
                    entry["reason"] = "_product_json returned None/non-dict"
            except Exception as exc:
                entry["product_json_ok"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"
            products_out.append(entry)
        result["pipeline_product_json_item"] = products_out

        try:
            rows = scraper.search(q)
            result["pipeline_search"] = {
                "ok": True, "count": len(rows), "rows": rows[:12]
            }
        except Exception as exc:
            result["pipeline_search"] = {
                "ok": False, "error": f"{type(exc).__name__}: {exc}"
            }

        stream = getattr(scraper, "search_stream", None)
        if callable(stream):
            emitted = []
            try:
                def emit(row):
                    emitted.append(row)
                ret = stream(q, emit)
                result["pipeline_search_stream"] = {
                    "ok": True,
                    "return_type": type(ret).__name__,
                    "emitted_count": len(emitted),
                    "emitted_rows": emitted[:12],
                }
            except Exception as exc:
                result["pipeline_search_stream"] = {
                    "ok": False,
                    "emitted_count_before_error": len(emitted),
                    "emitted_rows_before_error": emitted[:12],
                    "error": f"{type(exc).__name__}: {exc}",
                }
        else:
            result["pipeline_search_stream"] = {
                "ok": False,
                "reason": "search_stream is not installed on the imported scraper module",
            }

        suggest = session.get(
            BASE_URL + "/search/suggest.json",
            params={
                "q": q,
                "resources[type]": "product",
                "resources[limit]": 20,
                "resources[options][unavailable_products]": "show",
            },
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        try:
            payload = suggest.json()
        except Exception:
            payload = {}
        products = (((payload or {}).get("resources") or {}).get("results") or {}).get("products") or []
        result["endpoints"]["suggest"] = {
            "ok": suggest.ok,
            "status": suggest.status_code,
            "product_count": len(products),
            "products": [
                {
                    "title": p.get("title"),
                    "url": p.get("url"),
                    "available": p.get("available"),
                    "price": p.get("price"),
                }
                for p in products if isinstance(p, dict)
            ],
        }

    return result

@router.get("/orioudh")
def debug_orioudh(q: str = Query("Hawas", min_length=2)):
    try:
        return diagnose_endpoints(q)
    except Exception as exc:
        return {
            "diagnostic": True, "ok": False, "store": "Orioudh", "query": q,
            "error_type": type(exc).__name__, "error": str(exc),
        }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="Hawas")
    args = parser.parse_args()
    print(json.dumps(diagnose_endpoints(args.query), ensure_ascii=False, indent=2))
