from fastapi import APIRouter, Query
import time
import requests

router = APIRouter()

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

@router.get("/diagnose-deloox-scraper")
def diagnose_deloox_scraper(q: str = Query("Liquid Brun")):
    started = time.monotonic()
    query = str(q or "").strip() or "Liquid Brun"
    out = {
        "diagnostic": "deloox-scraper-discover-v2",
        "ok": False,
        "store": "Deloox",
        "query": query,
        "purpose": "direct read-only execution of deployed Deloox _discover(); real production discovery path, without ProductMatcher, catalog writes, hydration or resync",
    }
    session = None
    try:
        from scrapers.deloox import scraper
        discover = getattr(scraper, "_discover", None)
        if discover is None:
            out["error"] = "_discover not found in deployed Deloox scraper"
            return out
        out["scraper_module"] = getattr(scraper, "__file__", None)
        out["discover_function"] = getattr(discover, "__name__", None)
        out["category_function"] = getattr(getattr(scraper, "_discover_from_categories", None), "__name__", None)
        out["hierarchy_function"] = getattr(getattr(scraper, "_category_navigation_links", None), "__name__", None)
        session = requests.Session()
        session.headers.update(getattr(scraper, "HEADERS", HEADERS))
        candidates = discover(session, query)
        out["candidates"] = list(candidates or [])[:100]
        out["candidate_count"] = len(candidates or [])
        state = getattr(scraper, "_LAST_DISCOVERY_STATE", None)
        if isinstance(state, dict):
            out["discovery_state"] = dict(state)
        product_fn = getattr(scraper, "_product", None)
        validated = []
        validation_errors = []
        if product_fn:
            for url in (candidates or [])[:80]:
                try:
                    r = session.get(url, headers=getattr(scraper, "HEADERS", HEADERS), timeout=getattr(scraper, "TIMEOUT", (3.5, 8.0)), allow_redirects=True)
                    if r.status_code >= 400:
                        continue
                    item = product_fn(r.url or url, r.text, query)
                    if item:
                        validated.append(item)
                except Exception as exc:
                    validation_errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
        out["validated_products"] = validated
        out["validation_error_count"] = len(validation_errors)
        out["validation_errors"] = validation_errors[:20]
        out["ok"] = True
        return out
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    finally:
        if session is not None:
            session.close()
        out["elapsed_sec"] = round(time.monotonic() - started, 3)
