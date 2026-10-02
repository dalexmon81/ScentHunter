from __future__ import annotations

import inspect
import time
from urllib.parse import quote

from fastapi import APIRouter, Query

router = APIRouter()

TARGET_TOKEN = "41708"

BASE_URL = "https://www.sabina.com/it/ricerca_old"


def _load_engine():
    import catalog_engine as ce
    return ce


@router.get("/diagnose-sabina-legacy-sparam")
def diagnose_sabina_legacy_sparam(
    q: str = Query("liquid"),
):
    started = time.time()
    ce = _load_engine()

    fn = getattr(ce, "_discover_html_catalog", None)
    legacy = getattr(ce, "_sabina_legacy_product_urls", None)

    if fn is None:
        return {
            "diagnostic": "sabina-legacy-sparam-v1",
            "ok": False,
            "error": "catalog_engine._discover_html_catalog not found",
            "read_only": True,
        }

    search_url = f"{BASE_URL}?s={quote(q)}"

    old_pages = getattr(ce, "HTML_MAX_PAGES", None)
    old_depth = getattr(ce, "HTML_MAX_DEPTH", None)

    try:
        ce.HTML_MAX_PAGES = 1
        ce.HTML_MAX_DEPTH = 0

        result = fn(
            "sabina",
            [search_url],
            time.time() + 45,
        )

    except Exception as exc:
        return {
            "diagnostic": "sabina-legacy-sparam-v1",
            "ok": False,
            "query": q,
            "seed": search_url,
            "error": f"{type(exc).__name__}:{exc}",
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "database_written": False,
            "catalog_resync_called": False,
            "elapsed_sec": round(time.time() - started, 3),
        }

    finally:
        if old_pages is not None:
            ce.HTML_MAX_PAGES = old_pages

        if old_depth is not None:
            ce.HTML_MAX_DEPTH = old_depth

    product_urls = sorted(
        (result.get("product_urls") or {}).keys()
    )

    target_urls = [
        url for url in product_urls
        if TARGET_TOKEN in url
    ]

    return {
        "diagnostic": "sabina-legacy-sparam-v1",
        "ok": True,

        "query": q,
        "seed": search_url,

        "source_flags": {
            "discover_html_catalog_exists": True,
            "legacy_helper_exists": bool(legacy),
            "discover_calls_legacy_helper": (
                "_sabina_legacy_product_urls"
                in inspect.getsource(fn)
            ),
        },

        "discovery_result": {
            "visited": result.get("visited"),
            "successes": result.get("successes"),
            "error_count": len(result.get("errors") or []),
            "errors": (result.get("errors") or [])[:10],
            "product_url_count": len(product_urls),
            "target_urls": target_urls,
            "target_found": bool(target_urls),
        },

        "sample_product_urls": product_urls[:50],

        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "catalog_resync_called": False,

        "elapsed_sec": round(time.time() - started, 3),
    }
