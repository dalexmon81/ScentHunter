"""ScentHunter diagnostic router: search-index and search-local timing.

All endpoints are diagnostic only. They never write to SQLite, never discover
URLs, never hydrate product pages, and never call retailer endpoints.

The timing endpoint may rebuild the in-process search index in RAM when
reset_cache=true. That changes only the process-local cache; it does not alter
the catalog database.
"""
import os
import sqlite3
import time
from fastapi import APIRouter

router = APIRouter()


def _rss_kb():
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except Exception:
        return None
    return None


def _catalog_module():
    try:
        from backend import catalog_engine
        return catalog_engine
    except Exception:
        import catalog_engine
        return catalog_engine


def _cache_snapshot(catalog):
    cache = getattr(catalog, "_LOCAL_SEARCH_INDEX_CACHE", {})
    out = {}
    for store, item in cache.items():
        out[store] = {
            "signature": list(item.get("signature", ())),
            "posting_count": len(item.get("postings", {})),
            "url_count": len(item.get("url_tokens", {})),
        }
    return out


@router.get("/diagnostic/search-index-build")
def diagnostic_search_index_build(q: str = "Liquid Brun"):
    """Read-only measurement of the cost of rebuilding every store index."""
    catalog = _catalog_module()
    started_all = time.perf_counter()

    uri = f"file:{catalog.DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=2000")
    conn.execute("PRAGMA query_only=ON")

    stores = {}
    try:
        for store in catalog.STORES:
            started = time.perf_counter()
            row = conn.execute(
                """SELECT COUNT(*) AS active_urls,
                          SUM(CASE WHEN p.url IS NOT NULL
                                   AND p.fetch_status='OK' THEN 1 ELSE 0 END)
                     AS fetched_products_ok
                   FROM store_urls u
                   LEFT JOIN store_products p
                     ON p.store=u.store AND p.url=u.url
                   WHERE u.store=? AND u.active=1""",
                (store,),
            ).fetchone()
            active_urls = int(row["active_urls"] or 0)
            fetched_ok = int(row["fetched_products_ok"] or 0)

            select_started = time.perf_counter()
            rows = conn.execute(
                """SELECT u.url,u.slug,u.lastmod,
                          p.name AS product_name,
                          p.brand AS product_brand
                   FROM store_urls u
                   LEFT JOIN store_products p
                     ON p.store=u.store
                    AND p.url=u.url
                    AND p.fetch_status='OK'
                   WHERE u.store=? AND u.active=1""",
                (store,),
            ).fetchall()
            select_sec = time.perf_counter() - select_started

            normalize_started = time.perf_counter()
            token_occurrences = 0
            unique_tokens = set()
            for r in rows:
                search_text = " ".join(
                    str(r[key] or "")
                    for key in ("slug", "product_name", "product_brand")
                )
                toks = set(catalog.norm(search_text).split())
                token_occurrences += len(toks)
                unique_tokens.update(toks)
            normalize_sec = time.perf_counter() - normalize_started
            total_sec = time.perf_counter() - started

            stores[store] = {
                "active_urls": active_urls,
                "fetched_products_ok": fetched_ok,
                "select_sec": round(select_sec, 4),
                "normalize_sec": round(normalize_sec, 4),
                "total_build_sec": round(total_sec, 4),
                "token_occurrences": token_occurrences,
                "unique_tokens": len(unique_tokens),
                "error": None,
            }
    finally:
        conn.close()

    slowest = sorted(
        (
            {
                "store": store,
                "total_build_sec": data["total_build_sec"],
                "active_urls": data["active_urls"],
                "normalize_sec": data["normalize_sec"],
                "select_sec": data["select_sec"],
            }
            for store, data in stores.items()
        ),
        key=lambda x: x["total_build_sec"],
        reverse=True,
    )[:3]

    lock = getattr(catalog, "_LOCAL_SEARCH_INDEX_LOCK", None)
    lock_locked = None
    if lock is not None:
        try:
            lock_locked = lock.locked()
        except Exception:
            pass

    return {
        "diagnostic": "search-index-build-read-only-v1",
        "ok": True,
        "query": q,
        "writes": False,
        "search_local_called": False,
        "stores": stores,
        "db": {
            "path": str(catalog.DB_PATH),
            "journal_mode": "wal",
            "search_index_lock_locked_at_start": lock_locked,
        },
        "rss_kb_after": _rss_kb(),
        "elapsed_sec": round(time.perf_counter() - started_all, 4),
        "slowest_stores": slowest,
        "diagnosis": "MEASURED_INDEX_BUILD_COST",
    }


@router.get("/diagnostic/search-local-timing")
def diagnostic_search_local_timing(
    q: str = "Liquid Brun",
    reset_cache: bool = False,
):
    """Measure the real production search_local() cold/warm timings.

    reset_cache=True clears only the process-local RAM index. No SQLite row is
    changed. This is intentionally separate from the normal search endpoint so
    we can distinguish:
      - cold index build,
      - warm index lookup,
      - cache invalidation/rebuild,
      - concurrent lock contention.
    """
    catalog = _catalog_module()
    search_local = getattr(catalog, "search_local", None)
    if not callable(search_local):
        return {
            "diagnostic": "search-local-timing-v1",
            "ok": False,
            "error": "search_local_not_callable",
        }

    cache = getattr(catalog, "_LOCAL_SEARCH_INDEX_CACHE", None)
    lock = getattr(catalog, "_LOCAL_SEARCH_INDEX_LOCK", None)
    if cache is None or lock is None:
        return {
            "diagnostic": "search-local-timing-v1",
            "ok": False,
            "error": "local_search_cache_or_lock_missing",
        }

    before = _cache_snapshot(catalog)
    cleared = False
    if reset_cache:
        with lock:
            cache.clear()
        cleared = True

    after_clear = _cache_snapshot(catalog)

    t1 = time.perf_counter()
    try:
        first_rows = search_local(q, per_store=64, search_terms=[q])
        first_error = None
    except Exception as exc:
        first_rows = []
        first_error = f"{type(exc).__name__}: {exc}"
    first_sec = time.perf_counter() - t1

    after_first = _cache_snapshot(catalog)

    t2 = time.perf_counter()
    try:
        second_rows = search_local(q, per_store=64, search_terms=[q])
        second_error = None
    except Exception as exc:
        second_rows = []
        second_error = f"{type(exc).__name__}: {exc}"
    second_sec = time.perf_counter() - t2

    after_second = _cache_snapshot(catalog)

    return {
        "diagnostic": "search-local-timing-v1",
        "ok": first_error is None and second_error is None,
        "query": q,
        "writes_to_sqlite": False,
        "process_ram_cache_mutated": bool(cleared or before != after_first),
        "reset_cache": reset_cache,
        "first_call": {
            "seconds": round(first_sec, 4),
            "result_count": len(first_rows),
            "error": first_error,
        },
        "second_call": {
            "seconds": round(second_sec, 4),
            "result_count": len(second_rows),
            "error": second_error,
        },
        "cache": {
            "before": before,
            "after_clear": after_clear,
            "after_first": after_first,
            "after_second": after_second,
        },
        "lock_locked_after": bool(lock.locked()),
        "rss_kb_after": _rss_kb(),
        "diagnosis": (
            "COLD_AND_WARM_TIMING"
            if first_error is None and second_error is None
            else "SEARCH_LOCAL_ERROR"
        ),
    }
