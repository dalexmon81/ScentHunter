from __future__ import annotations

"""
ScentHunter - read-only Sabina real-seed discovery trace.

Tests ONE production Sabina ricerca_old seed at a time.

No production search, ProductMatcher, discover_store(), _save_discovery(),
catalog resync, hydration, or database write is performed.
"""

import inspect
import string
import time

from fastapi import APIRouter, Query

router = APIRouter()

TARGET_TOKEN = "41708"
TARGET_URL = (
    "https://www.sabina.com/it/profumi-di-donna/"
    "41708-liquid-brun-limited-edition-extrait-de-parfum.html"
)


def _load_engine():
    import catalog_engine as ce
    return ce


def _configured_sabina_seeds(ce):
    candidates = []

    for name in (
        "HTML_DISCOVERY_SEEDS",
        "DISCOVERY_HTML_SEEDS",
        "SABINA_HTML_DISCOVERY_SEEDS",
    ):
        value = getattr(ce, name, None)

        if isinstance(value, dict):
            value = (
                value.get("sabina")
                or value.get("Sabina")
                or value.get("SABINA")
            )

        if isinstance(value, (list, tuple, set)):
            candidates.extend(str(item) for item in value if item)
            if candidates:
                break

    if not candidates:
        candidates = [
            f"https://www.sabina.com/it/ricerca_old?search_query={letter}"
            for letter in string.ascii_lowercase
        ]

    return [
        url
        for url in candidates
        if "sabina.com" in url.lower()
        and "/ricerca_old" in url.lower()
        and "search_query=" in url.lower()
    ]


def _select_seed(seeds, letter):
    wanted = str(letter).strip().lower()

    for seed in seeds:
        low = seed.lower()

        if (
            f"search_query={wanted}" in low
            or f"search_query={wanted}&" in low
        ):
            return seed

    return None


@router.get("/diagnose-sabina-real-seeds")
def diagnose_sabina_real_seeds(
    letter: str = Query("l", min_length=1, max_length=1),
    max_pages: int = Query(1, ge=1, le=1),
    max_depth: int = Query(0, ge=0, le=0),
):
    started = time.time()
    ce = _load_engine()

    fn = getattr(ce, "_discover_html_catalog", None)
    priority = getattr(ce, "_html_discovery_priority", None)

    if fn is None:
        return {
            "diagnostic": "sabina-real-seed-v2",
            "ok": False,
            "error": "catalog_engine._discover_html_catalog not found",
            "read_only": True,
        }

    source = inspect.getsource(fn)
    priority_source = inspect.getsource(priority) if priority else ""

    seeds = _configured_sabina_seeds(ce)
    selected_seed = _select_seed(seeds, letter)

    if selected_seed is None:
        return {
            "diagnostic": "sabina-real-seed-v2",
            "ok": False,
            "error": "requested production seed not found",
            "requested_letter": letter,
            "available_seeds": seeds,
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "database_written": False,
            "catalog_resync_called": False,
        }

    old_pages = getattr(ce, "HTML_MAX_PAGES", None)
    old_depth = getattr(ce, "HTML_MAX_DEPTH", None)

    try:
        ce.HTML_MAX_PAGES = int(max_pages)
        ce.HTML_MAX_DEPTH = int(max_depth)

        seed_started = time.time()

        result = fn(
            "sabina",
            [selected_seed],
            time.time() + 45,
        )

        elapsed_seed = round(time.time() - seed_started, 3)

    except Exception as exc:
        return {
            "diagnostic": "sabina-real-seed-v2",
            "ok": False,
            "requested_letter": letter,
            "seed": selected_seed,
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
        url
        for url in product_urls
        if TARGET_TOKEN in url
        or TARGET_URL.casefold() in url.casefold()
    ]

    return {
        "diagnostic": "sabina-real-seed-v2",
        "ok": True,

        "target": {
            "product_id": TARGET_TOKEN,
            "canonical_url": TARGET_URL,
        },

        "requested_seed": {
            "letter": letter,
            "seed": selected_seed,
        },

        "limits": {
            "max_pages": max_pages,
            "max_depth": max_depth,
        },

        "source_flags": {
            "discover_html_catalog_exists": True,
            "discover_calls_legacy_helper": (
                "_sabina_legacy_product_urls" in source
            ),
            "priority_exists": bool(priority),
            "priority_mentions_ricerca_old": (
                "ricerca_old" in priority_source
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

        "elapsed_seed_sec": elapsed_seed,
        "elapsed_sec": round(time.time() - started, 3),
    }
