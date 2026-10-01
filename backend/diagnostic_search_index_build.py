"""Read-only ScentHunter search-index build diagnostic."""
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

@router.get("/diagnostic/search-index-build")
def diagnostic_search_index_build(q: str = "Liquid Brun"):
    """Measure SELECT and tokenization cost without calling search_local()."""
    started = time.perf_counter()
    query = str(q or "").strip() or "Liquid Brun"
    out = {
        "diagnostic": "search-index-build-read-only-v1",
        "ok": False,
        "query": query,
        "writes": False,
        "search_local_called": False,
        "stores": {},
    }
    try:
        import catalog_engine
        db_path = str(catalog_engine.DB_PATH)
        stores = list(catalog_engine.STORES.keys())
        norm_fn = catalog_engine.norm
        lock = getattr(catalog_engine, "_LOCAL_SEARCH_INDEX_LOCK", None)
        try:
            lock_locked = bool(lock.locked()) if lock is not None else None
        except Exception:
            lock_locked = None

        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=2000")
        conn.execute("PRAGMA query_only=ON")
        try:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        except Exception:
            journal_mode = None

        out["db"] = {
            "path": db_path,
            "journal_mode": journal_mode,
            "search_index_lock_locked_at_start": lock_locked,
        }

        for store in stores:
            store_started = time.perf_counter()
            item = {
                "active_urls": 0,
                "fetched_products_ok": 0,
                "select_sec": None,
                "normalize_sec": None,
                "total_build_sec": None,
                "token_occurrences": 0,
                "unique_tokens": 0,
                "error": None,
            }
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM store_urls WHERE store=? AND active=1",
                    (store,),
                ).fetchone()
                item["active_urls"] = int(row["n"] or 0)

                row = conn.execute(
                    """SELECT COUNT(*) AS n
                       FROM store_products p
                       JOIN store_urls u ON u.store=p.store AND u.url=p.url
                       WHERE p.store=? AND u.active=1 AND p.fetch_status='OK'""",
                    (store,),
                ).fetchone()
                item["fetched_products_ok"] = int(row["n"] or 0)

                t = time.perf_counter()
                rows = conn.execute(
                    """SELECT u.url,u.slug,u.lastmod,
                              p.name AS product_name,p.brand AS product_brand
                       FROM store_urls u
                       LEFT JOIN store_products p
                         ON p.store=u.store AND p.url=u.url
                        AND p.fetch_status='OK'
                       WHERE u.store=? AND u.active=1""",
                    (store,),
                ).fetchall()
                item["select_sec"] = round(time.perf_counter() - t, 4)

                t = time.perf_counter()
                unique_tokens = set()
                occurrences = 0
                for row in rows:
                    text = " ".join(
                        str(row[key] or "")
                        for key in ("slug", "product_name", "product_brand")
                    )
                    combined = set(norm_fn(text).split())
                    occurrences += len(combined)
                    unique_tokens.update(combined)

                item["normalize_sec"] = round(time.perf_counter() - t, 4)
                item["token_occurrences"] = occurrences
                item["unique_tokens"] = len(unique_tokens)
                item["total_build_sec"] = round(
                    time.perf_counter() - store_started, 4
                )
            except Exception as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
                item["total_build_sec"] = round(
                    time.perf_counter() - store_started, 4
                )
            out["stores"][store] = item

        conn.close()
        out["ok"] = True
        out["rss_kb_after"] = _rss_kb()
        out["elapsed_sec"] = round(time.perf_counter() - started, 4)
        out["slowest_stores"] = sorted(
            [
                {
                    "store": s,
                    "total_build_sec": d["total_build_sec"],
                    "active_urls": d["active_urls"],
                    "normalize_sec": d["normalize_sec"],
                    "select_sec": d["select_sec"],
                }
                for s, d in out["stores"].items()
                if d["total_build_sec"] is not None
            ],
            key=lambda x: x["total_build_sec"],
            reverse=True,
        )[:3]
        out["diagnosis"] = "MEASURED_INDEX_BUILD_COST"
        return out
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["rss_kb_after"] = _rss_kb()
        out["elapsed_sec"] = round(time.perf_counter() - started, 4)
        out["diagnosis"] = "DIAGNOSTIC_FAILED"
        return out
