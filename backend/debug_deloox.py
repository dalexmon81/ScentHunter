from fastapi import APIRouter
import importlib
import time

router = APIRouter(prefix="/api/debug", tags=["debug-deloox-cap"])

@router.get("/deloox-cap-probe")
def deloox_cap_probe(q: str = "Born in Roma"):
    out = {"ok": True, "test": "TEST_7_DELOOX_SEARCH_CAP_PROBE", "query": q}
    try:
        m = importlib.import_module("scrapers.deloox.scraper")
        old = getattr(m, "MAX_RESULTS", None)
        out["runtime"] = {
            "module_file": getattr(m, "__file__", ""),
            "MAX_RESULTS_before": old,
        }

        t = time.perf_counter()
        default_rows = m.search(q)
        out["default_search"] = {
            "elapsed": round(time.perf_counter() - t, 3),
            "count": len(default_rows or []),
            "urls": [r.get("url") for r in (default_rows or []) if isinstance(r, dict)],
        }

        m.MAX_RESULTS = 100
        try:
            t = time.perf_counter()
            uncapped_rows = m.search(q)
            out["uncapped_search"] = {
                "elapsed": round(time.perf_counter() - t, 3),
                "count": len(uncapped_rows or []),
                "urls": [r.get("url") for r in (uncapped_rows or []) if isinstance(r, dict)],
            }
        finally:
            if old is None:
                try:
                    delattr(m, "MAX_RESULTS")
                except Exception:
                    pass
            else:
                m.MAX_RESULTS = old

        default_urls = set(out["default_search"]["urls"])
        uncapped_urls = set(out["uncapped_search"]["urls"])
        out["comparison"] = {
            "extra_when_uncapped": sorted(uncapped_urls - default_urls),
            "default_missing_count": len(uncapped_urls - default_urls),
            "contains_ivory_donna": any("1400164" in u for u in uncapped_urls),
            "contains_ivory_uomo": any("1400167" in u for u in uncapped_urls),
        }
        return out
    except Exception as exc:
        out["ok"] = False
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)
        return out
