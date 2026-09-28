from fastapi import APIRouter, Query
import time
import requests

router = APIRouter()

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

@router.get("/diagnose-deloox-scraper")
def diagnose_deloox_scraper(q: str = Query("Liquid Brun")):
    """
    READ-ONLY diagnostic of the deployed Deloox scraper.

    Calls the scraper's own diagnose_search() function directly.
    Does NOT call production search(), catalog search, ProductMatcher,
    hydration, catalog writes, cache invalidation, or resync.
    """
    started = time.monotonic()
    query = str(q or "").strip() or "Liquid Brun"

    out = {
        "diagnostic": "deloox-scraper-direct-v1",
        "ok": False,
        "store": "Deloox",
        "query": query,
        "purpose": (
            "direct read-only execution of the deployed Deloox scraper "
            "diagnose_search(); no production search, catalog writes, "
            "ProductMatcher, hydration or resync"
        ),
    }

    try:
        from scrapers.deloox import scraper

        out["scraper_module"] = getattr(scraper, "__file__", None)
        out["discover_function"] = getattr(
            getattr(scraper, "diagnose_search", None), "__name__", None
        )

        fn = getattr(scraper, "diagnose_search", None)
        if fn is None:
            out["error"] = "diagnose_search not found in deployed Deloox scraper"
            return out

        session = requests.Session()
        session.headers.update(getattr(scraper, "HEADERS", HEADERS))

        try:
            report = fn(session, query)
        finally:
            session.close()

        out["ok"] = True
        out["report"] = report
        return out

    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    finally:
        out["elapsed_sec"] = round(time.monotonic() - started, 3)
