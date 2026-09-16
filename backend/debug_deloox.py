from fastapi import APIRouter
import importlib
import inspect
import json
import re
import requests
from bs4 import BeautifulSoup

router = APIRouter(prefix="/api/debug", tags=["debug-deloox-ivory"])

IVORY = {
    "1400164": "https://www.deloox.be/produit/1400164/valentino-donna-born-in-roma-ivory-eau-de-parfum-limited-edition-100-ml.html",
    "1400167": "https://www.deloox.be/produit/1400167/valentino-born-in-roma-ivory-uomo-eau-de-toilette-limited-edition-100-ml.html",
}

def _jsonld_products(html):
    soup = BeautifulSoup(html or "", "html.parser")
    out = []
    for node in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                graph = item.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
                if item.get("@type") == "Product" or (
                    isinstance(item.get("@type"), list) and "Product" in item.get("@type")
                ):
                    out.append(item)
    return out

def _safe_call(fn, *args):
    try:
        value = fn(*args)
        return {"ok": True, "value": value}
    except Exception as exc:
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

@router.get("/deloox-ivory-debug")
def deloox_ivory_debug():
    out = {
        "ok": True,
        "test": "TEST_6_DELOOX_IVORY_END_TO_END",
        "query": "Born in Roma",
        "targets": {},
    }

    try:
        m = importlib.import_module("scrapers.deloox.scraper")
        session = requests.Session()

        # Runtime facts needed to prove exactly where each Ivory is lost.
        out["runtime"] = {
            "module_file": getattr(m, "__file__", ""),
            "parse_product_signature": str(inspect.signature(m.parse_product)),
            "relevant": _safe_call(m.relevant, "Valentino Donna Born in Roma Ivory Eau de Parfum Limited Edition 100 ml", "Born in Roma"),
            "non_fragrance": _safe_call(m.non_fragrance, "Valentino Donna Born in Roma Ivory Eau de Parfum Limited Edition 100 ml"),
        }

        for pid, url in IVORY.items():
            item = {"url": url}

            try:
                r = m.get(session, url)
                item["request"] = {
                    "ok": bool(r),
                    "status_code": getattr(r, "status_code", None),
                    "final_url": getattr(r, "url", ""),
                    "html_length": len(getattr(r, "text", "") or ""),
                }
                html = getattr(r, "text", "") if r else ""
            except Exception as exc:
                item["request"] = {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                html = ""

            products = _jsonld_products(html)
            item["jsonld_product_count"] = len(products)
            item["jsonld_products"] = []

            for p in products[:10]:
                offers = p.get("offers")
                if isinstance(offers, list):
                    offers_view = offers[:10]
                else:
                    offers_view = offers

                item["jsonld_products"].append({
                    "name": p.get("name"),
                    "brand": p.get("brand"),
                    "sku": p.get("sku"),
                    "url": p.get("url"),
                    "image": p.get("image"),
                    "offers": offers_view,
                })

            # Exact helper decisions on the real URL.
            item["url_helpers"] = {
                "is_product_url": _safe_call(m.is_product_url, url),
                "product_url": _safe_call(m.product_url, url),
                "born_in_roma_slug": _safe_call(m.born_in_roma_slug, url),
                "excluded_product_slug": _safe_call(m.excluded_product_slug, url),
            }

            # Reproduce the exact final parser, independently of /test-store.
            parsed = _safe_call(m.parse_product, url, "Born in Roma")
            if parsed.get("ok"):
                rows = parsed.get("value")
                item["parse_product"] = {
                    "returned_type": type(rows).__name__,
                    "row_count": len(rows) if isinstance(rows, list) else None,
                    "rows": rows,
                }
            else:
                item["parse_product"] = parsed

            out["targets"][pid] = item

        session.close()
        return out

    except Exception as exc:
        out["ok"] = False
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)
        return out
