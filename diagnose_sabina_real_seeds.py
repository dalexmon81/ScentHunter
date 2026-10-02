from __future__ import annotations

"""
ScentHunter - read-only Sabina real-seed discovery trace.

This diagnostic reproduces the Sabina HTML discovery function against the
same configured ricerca_old letter seeds used by production discovery, one
seed at a time, with one page and zero crawl depth per seed.

It does not call public search, ProductMatcher, discover_store(),
_save_discovery(), catalog resync, or any database write.
"""

import inspect
import string
import time
from fastapi import APIRouter, Query

router = APIRouter()

TARGET_TOKEN = "41708"
TARGET_URL = "https://www.sabina.com/it/profumi-di-donna/41708-liquid-brun-limited-edition-extrait-de-parfum.html"


def _load_engine():
    import catalog_engine as ce
    return ce


def _configured_sabina_seeds(ce):
    """Read the exact production seed constant when available.

    The explicit fallback mirrors the currently configured ricerca_old
    alphabetic seeds, but the diagnostic prefers the live module constant so
    it remains useful if the seed container is renamed or represented as a
    list/tuple/dict in a future revision.
    """
    candidates = []
    for name in (
        "HTML_DISCOVERY_SEEDS",
        "DISCOVERY_HTML_SEEDS",
        "SABINA_HTML_DISCOVERY_SEEDS",
    ):
        value = getattr(ce, name, None)
        if isinstance(value, dict):
            value = value.get("sabina") or value.get("Sabina") or value.get("SABINA")
        if isinstance(value, (list, tuple, set)):
            candidates.extend(str(item) for item in value if item)
            if candidates:
                break

    if not candidates:
        candidates = [
            f"https://www.sabina.com/it/ricerca_old?search_query={letter}"
            for letter in string.ascii_lowercase
        ]

    # Production Sabina discovery currently uses the ricerca_old alphabetic
    # probes plus other catalog surfaces. This diagnostic intentionally
    # isolates the ricerca_old probes because the target is known to be
    # exposed by that surface.
    return [
        url for url in candidates
        if "sabina.com" in url.lower()
        and "/ricerca_old" in url.lower()
        and "search_query=" in url.lower()
    ]


@router.get("/diagnose-sabina-real-seeds")
def diagnose_sabina_real_seeds(
    max_pages: int = Query(1, ge=1, le=1),
    max_depth: int = Query(0, ge=0, le=0),
):
    started = time.time()
    ce = _load_engine()

    fn = getattr(ce, "_discover_html_catalog", None)
    priority = getattr(ce, "_html_discovery_priority", None)
    if fn is None:
        return {
            "diagnostic": "sabina-real-seeds-v1",
            "ok": False,
            "error": "catalog_engine._discover_html_catalog not found",
            "read_only": True,
        }

    source = inspect.getsource(fn)
    seeds = _configured_sabina_seeds(ce)

    old_pages = getattr(ce, "HTML_MAX_PAGES", None)
    old_depth = getattr(ce, "HTML_MAX_DEPTH", None)

    rows = []
    union_urls = set()
    try:
        ce.HTML_MAX_PAGES = int(max_pages)
        ce.HTML_MAX_DEPTH = int(max_depth)

        for seed in seeds:
            seed_started = time.time()
            try:
                result = fn("sabina", [seed], time.time() + 45)
                product_urls = sorted((result.get("product_urls") or {}).keys())
                target_urls = [
                    url for url in product_urls
                    if TARGET_TOKEN in url or TARGET_URL.casefold() in url.casefold()
                ]
                union_urls.update(product_urls)
                rows.append({
                    "seed": seed,
                    "visited": result.get("visited"),
                    "successes": result.get("successes"),
                    "error_count": len(result.get("errors") or []),
                    "errors": (result.get("errors") or [])[:5],
                    "product_url_count": len(product_urls),
                    "target_urls": target_urls,
                    "target_found": bool(target_urls),
                    "elapsed_sec": round(time.time() - seed_started, 3),
                })
            except Exception as exc:
                rows.append({
                    "seed": seed,
                    "error": f"{type(exc).__name__}:{exc}",
                    "target_found": False,
                    "elapsed_sec": round(time.time() - seed_started, 3),
                })
    finally:
        if old_pages is not None:
            ce.HTML_MAX_PAGES = old_pages
        if old_depth is not None:
            ce.HTML_MAX_DEPTH = old_depth

    hits = [row for row in rows if row.get("target_found")]

    return {
        "diagnostic": "sabina-real-seeds-v1",
        "ok": True,
        "target": {
            "product_id": TARGET_TOKEN,
            "canonical_url": TARGET_URL,
        },
        "seed_source": {
            "seed_count": len(seeds),
            "seeds": seeds,
            "used_live_seed_constant": any(
                isinstance(getattr(ce, name, None), (list, tuple, set, dict))
                for name in (
                    "HTML_DISCOVERY_SEEDS",
                    "DISCOVERY_HTML_SEEDS",
                    "SABINA_HTML_DISCOVERY_SEEDS",
                )
            ),
        },
        "source_flags": {
            "discover_html_catalog_exists": True,
            "discover_calls_legacy_helper": "_sabina_legacy_product_urls" in source,
            "priority_exists": bool(priority),
            "priority_mentions_ricerca_old": "ricerca_old" in (inspect.getsource(priority) if priority else ""),
        },
        "per_seed": rows,
        "summary": {
            "seeds_tested": len(rows),
            "seeds_with_target": len(hits),
            "target_found": bool(hits),
            "target_seed_hits": [row["seed"] for row in hits],
            "union_product_url_count": len(union_urls),
        },
        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "catalog_resync_called": False,
        "elapsed_sec": round(time.time() - started, 3),
    }
