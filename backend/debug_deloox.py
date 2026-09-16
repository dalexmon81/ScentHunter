
from fastapi import APIRouter
import importlib, inspect, time

router = APIRouter()

@router.get("/deloox-purple-1391716")
def deloox_purple_1391716(q: str = "Born in Roma"):
    TARGET_ID = "1391716"
    out = {
        "ok": True,
        "test": "DELOOX_TARGET_1391716_TRACE",
        "query": q,
        "target_id": TARGET_ID,
        "target_url": "https://www.deloox.be/produit/1391716/",
    }

    try:
        s = importlib.import_module("scrapers.deloox.scraper")
        out["runtime"] = {
            "file": getattr(s, "__file__", ""),
            "search_signature": str(inspect.signature(s.search)),
            "discover_signature": str(inspect.signature(s.discover)),
            "parse_product_signature": str(inspect.signature(s.parse_product)),
        }

        # 1) Discovery: locate the exact target candidate.
        session = s.requests.Session()
        t = time.perf_counter()
        candidates = s.discover(session, q)
        out["discover"] = {
            "elapsed": round(time.perf_counter() - t, 3),
            "count": len(candidates or []),
            "target": None,
        }

        target_candidate = None
        for url, info in candidates or []:
            if TARGET_ID in str(url):
                target_candidate = (url, info)
                break

        if target_candidate:
            url, info = target_candidate
            out["discover"]["target"] = {
                "url": url,
                "info_type": type(info).__name__,
                "info_repr": repr(info)[:3000],
            }

            # 2) Card extraction exactly as production search does.
            try:
                if isinstance(info, (tuple, list)):
                    context = info[1] if len(info) >= 2 else ""
                    image = info[2] if len(info) >= 3 else ""
                else:
                    context, image = "", ""

                row = s._row_from_card(url, context, q, image)
                out["row_from_card"] = {
                    "accepted": isinstance(row, dict),
                    "row": row,
                    "context_preview": str(context)[:2000],
                }
            except Exception as exc:
                out["row_from_card"] = {
                    "accepted": False,
                    "exception": type(exc).__name__,
                    "error": str(exc),
                }

            # 3) Product-page parser exactly for the target.
            try:
                t = time.perf_counter()
                parsed = s.parse_product(url, q)
                out["parse_product"] = {
                    "elapsed": round(time.perf_counter() - t, 3),
                    "count": len(parsed or []),
                    "rows": parsed or [],
                }
            except Exception as exc:
                out["parse_product"] = {
                    "exception": type(exc).__name__,
                    "error": str(exc),
                }
        else:
            out["row_from_card"] = {"skipped": True, "reason": "target_not_in_discover"}
            out["parse_product"] = {"skipped": True, "reason": "target_not_in_discover"}

        # 4) One real production search. This is the decisive check.
        t = time.perf_counter()
        rows = s.search(q)
        out["search"] = {
            "elapsed": round(time.perf_counter() - t, 3),
            "count": len(rows or []),
            "target_present": any(
                TARGET_ID in str(r.get("url", ""))
                for r in (rows or [])
                if isinstance(r, dict)
            ),
            "target_rows": [
                r for r in (rows or [])
                if isinstance(r, dict) and TARGET_ID in str(r.get("url", ""))
            ],
        }

        # 5) Exact conclusion.
        d = out["discover"].get("target") is not None
        c = out.get("row_from_card", {}).get("accepted") is True
        p = out.get("parse_product", {}).get("count", 0) > 0
        f = out["search"]["target_present"]

        if not d:
            diagnosis = "LOST_IN_DISCOVER"
        elif c or p:
            diagnosis = "PARSER_HAS_TARGET_BUT_SEARCH_DROPS_IT"
        else:
            diagnosis = "DISCOVER_HAS_TARGET_BUT_BOTH_CARD_AND_PRODUCT_PARSER_DROP_IT"

        if f:
            diagnosis = "TARGET_REACHES_FINAL_SEARCH"

        out["diagnosis"] = {
            "discovered": d,
            "card_accepted": c,
            "product_page_parsed": p,
            "final_search_present": f,
            "result": diagnosis,
        }

        return out

    except Exception as exc:
        out["ok"] = False
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)
        return out
