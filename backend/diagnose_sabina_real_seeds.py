from __future__ import annotations

"""
ScentHunter - read-only Sabina real-seed discovery diagnostics.

Endpoints:

1. /diagnose-sabina-real-seeds
   Tests ONE configured production ricerca_old seed.

2. /diagnose-sabina-real-seeds-batch
   Tests ALL configured production ricerca_old seeds plus generic
   Sabina native ?s= surfaces and reports exactly where target 41708
   is exposed.

No production search, ProductMatcher, discover_store(), _save_discovery(),
catalog resync, hydration, or database write is performed.
"""

import inspect
import string
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Query

router = APIRouter()

TARGET_TOKEN = "41708"
TARGET_URL = (
    "https://www.sabina.com/it/profumi-di-donna/"
    "41708-liquid-brun-limited-edition-extrait-de-parfum.html"
)

SABINA_SEARCH_BASE = "https://www.sabina.com/it/ricerca_old"

# These are intentionally generic category/language probes.
# They are NOT product-specific and are used only diagnostically.
NATIVE_S_PROBES = (
    "parfum",
    "perfume",
    "extrait",
    "profumi",
    "fragrance",
    "eau",
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
        parsed = urlsplit(seed)
        query = parse_qs(parsed.query, keep_blank_values=True)

        values = query.get("search_query") or []

        for value in values:
            if str(value).strip().lower() == wanted:
                return seed

    return None


def _target_urls(product_urls):
    return [
        url
        for url in product_urls
        if TARGET_TOKEN in str(url)
        or TARGET_URL.casefold() in str(url).casefold()
    ]


def _native_s_url(term):
    return (
        SABINA_SEARCH_BASE
        + "?"
        + urlencode({"s": term})
    )


def _extract_ids_directly(ce, url):
    """
    Fetch one Sabina page and run exactly the generic legacy-ID helper
    used by production HTML discovery.

    This is read-only.
    """
    fetch = getattr(ce, "_http_fetch", None)
    helper = getattr(ce, "_sabina_legacy_product_urls", None)

    if fetch is None:
        raise RuntimeError("catalog_engine._http_fetch not found")

    if helper is None:
        raise RuntimeError(
            "catalog_engine._sabina_legacy_product_urls not found"
        )

    started = time.time()

    response = fetch(url, timeout=25)

    status = response.get("status")
    final_url = response.get("url") or url
    data = response.get("data") or ""

    ids_as_urls = helper(data, final_url)

    product_urls = sorted(
        str(value)
        for value in ids_as_urls
        if value
    )

    elapsed = round(time.time() - started, 3)

    return {
        "url": url,
        "final_url": final_url,
        "status": status,
        "bytes": int(response.get("length") or 0),
        "content_type": response.get("content_type"),
        "id_count": len(product_urls),
        "target_urls": _target_urls(product_urls),
        "target_found": bool(_target_urls(product_urls)),
        "sample_urls": product_urls[:20],
        "ids": product_urls,
        "elapsed_sec": elapsed,
    }


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

    target_urls = _target_urls(product_urls)

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


@router.get("/diagnose-sabina-real-seeds-batch")
def diagnose_sabina_real_seeds_batch(
    include_native: bool = Query(True),
    workers: int = Query(6, ge=1, le=8),
):
    """
    Batch diagnostic.

    Tests:
      A) every configured production `search_query=a...z` seed
      B) generic native `?s=` surfaces

    The request is read-only and bypasses production search/matcher/database.
    It directly exercises the same Sabina legacy ID extraction helper used
    by catalog discovery.
    """

    started = time.time()
    ce = _load_engine()

    fetch = getattr(ce, "_http_fetch", None)
    helper = getattr(ce, "_sabina_legacy_product_urls", None)

    if fetch is None:
        return {
            "diagnostic": "sabina-real-seeds-batch-v1",
            "ok": False,
            "error": "catalog_engine._http_fetch not found",
            "read_only": True,
        }

    if helper is None:
        return {
            "diagnostic": "sabina-real-seeds-batch-v1",
            "ok": False,
            "error": (
                "catalog_engine._sabina_legacy_product_urls not found"
            ),
            "read_only": True,
        }

    seeds = _configured_sabina_seeds(ce)

    configured_by_letter = {}

    for letter in string.ascii_lowercase:
        seed = _select_seed(seeds, letter)

        configured_by_letter[letter] = seed

    production_surfaces = [
        seed
        for seed in configured_by_letter.values()
        if seed
    ]

    native_surfaces = []

    if include_native:
        native_surfaces = [
            _native_s_url(term)
            for term in NATIVE_S_PROBES
        ]

    all_surfaces = []
    surface_kind = {}

    for seed in production_surfaces:
        if seed not in all_surfaces:
            all_surfaces.append(seed)
            surface_kind[seed] = "production_search_query"

    for seed in native_surfaces:
        if seed not in all_surfaces:
            all_surfaces.append(seed)
            surface_kind[seed] = "native_s"

    results = {}

    def run_one(url):
        try:
            return _extract_ids_directly(ce, url)
        except Exception as exc:
            return {
                "url": url,
                "status": None,
                "bytes": 0,
                "content_type": None,
                "id_count": 0,
                "target_urls": [],
                "target_found": False,
                "sample_urls": [],
                "ids": [],
                "elapsed_sec": None,
                "error": f"{type(exc).__name__}:{exc}",
            }

    with ThreadPoolExecutor(
        max_workers=min(int(workers), max(1, len(all_surfaces)))
    ) as executor:
        futures = {
            executor.submit(run_one, url): url
            for url in all_surfaces
        }

        for future in as_completed(futures):
            url = futures[future]
            result = future.result()
            results[url] = result

    ordered_results = []

    for url in all_surfaces:
        result = results.get(url) or {
            "url": url,
            "status": None,
            "bytes": 0,
            "content_type": None,
            "id_count": 0,
            "target_urls": [],
            "target_found": False,
            "sample_urls": [],
            "ids": [],
            "elapsed_sec": None,
            "error": "NO_RESULT",
        }

        letter = None

        parsed = urlsplit(url)
        query = parse_qs(
            parsed.query,
            keep_blank_values=True,
        )

        if "search_query" in query:
            values = query.get("search_query") or []
            if values:
                letter = values[0]

        ordered_results.append({
            "kind": surface_kind.get(url),
            "letter": letter,
            "term": (
                (query.get("s") or [None])[0]
                if "s" in query
                else None
            ),
            "url": url,
            "final_url": result.get("final_url"),
            "status": result.get("status"),
            "bytes": result.get("bytes"),
            "content_type": result.get("content_type"),
            "id_count": result.get("id_count"),
            "target_found": result.get("target_found"),
            "target_urls": result.get("target_urls"),
            "sample_urls": result.get("sample_urls"),
            "error": result.get("error"),
            "elapsed_sec": result.get("elapsed_sec"),
        })

    # Build union only from successfully fetched surfaces.
    union_ids = set()

    for url in all_surfaces:
        result = results.get(url) or {}
        for product_url in result.get("ids") or []:
            union_ids.add(str(product_url))

    union_target_urls = _target_urls(sorted(union_ids))

    target_surfaces = [
        {
            "kind": item["kind"],
            "letter": item["letter"],
            "term": item["term"],
            "url": item["url"],
            "status": item["status"],
            "id_count": item["id_count"],
            "target_urls": item["target_urls"],
        }
        for item in ordered_results
        if item["target_found"]
    ]

    production_target_surfaces = [
        item
        for item in target_surfaces
        if item["kind"] == "production_search_query"
    ]

    native_target_surfaces = [
        item
        for item in target_surfaces
        if item["kind"] == "native_s"
    ]

    successful = [
        item
        for item in ordered_results
        if isinstance(item.get("status"), int)
        and item.get("status") < 400
    ]

    failed = [
        item
        for item in ordered_results
        if not (
            isinstance(item.get("status"), int)
            and item.get("status") < 400
        )
    ]

    return {
        "diagnostic": "sabina-real-seeds-batch-v1",
        "ok": True,

        "target": {
            "product_id": TARGET_TOKEN,
            "canonical_url": TARGET_URL,
        },

        "purpose": (
            "Determinare quali superfici Sabina espongono il prodotto "
            "41708 e se le seed configurate in catalog discovery "
            "sono sufficienti a raggiungerlo."
        ),

        "configured_production_seeds": {
            "total_configured_ricerca_old_seeds": len(seeds),
            "expected_letters": list(string.ascii_lowercase),
            "found_letters": [
                letter
                for letter, seed in configured_by_letter.items()
                if seed
            ],
            "missing_letters": [
                letter
                for letter, seed in configured_by_letter.items()
                if not seed
            ],
            "seeds": configured_by_letter,
        },

        "native_s_probes": {
            "enabled": bool(include_native),
            "terms": list(NATIVE_S_PROBES)
            if include_native
            else [],
            "urls": native_surfaces,
        },

        "limits": {
            "workers": workers,
            "surfaces_tested": len(all_surfaces),
        },

        "summary": {
            "surfaces_tested": len(all_surfaces),
            "successful_http": len(successful),
            "failed_http": len(failed),
            "production_search_query_surfaces_tested": len(
                production_surfaces
            ),
            "native_s_surfaces_tested": len(native_surfaces),
            "unique_ids_union": len(union_ids),
            "target_found_in_union": bool(union_target_urls),
            "target_union_urls": union_target_urls,
            "target_surfaces_total": len(target_surfaces),
            "target_production_search_query_surfaces": len(
                production_target_surfaces
            ),
            "target_native_s_surfaces": len(
                native_target_surfaces
            ),
        },

        "target_surfaces": target_surfaces,

        "production_target_surfaces": production_target_surfaces,

        "native_target_surfaces": native_target_surfaces,

        "surfaces": ordered_results,

        "union_sample_urls": sorted(union_ids)[:100],

        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "catalog_resync_called": False,
        "hydration_called": False,

        "elapsed_sec": round(time.time() - started, 3),
    }
