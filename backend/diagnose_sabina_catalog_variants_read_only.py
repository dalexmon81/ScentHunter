"""Read-only diagnostic for Sabina persisted variants and local search."""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Query

router = APIRouter()

DEFAULT_URL = (
    "https://www.sabina.com/es/perfumes-mujer/31434-born-in-roma-donna-"
    "extradose-eau-de-parfum-valentino.html"
)


@router.get("/diagnose-sabina-catalog-variants-read-only")
def diagnose_sabina_catalog_variants_read_only(
    url: str = Query(DEFAULT_URL),
    q: str = Query("Born in Roma Extradose Donna"),
):
    """Read SQLite rows and replay local search; never refreshes or writes."""
    started = time.monotonic()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.sabina.com", "sabina.com"}:
        return {
            "ok": False, "diagnostic": "sabina-catalog-variants-read-only-v1",
            "read_only": True, "database_written": False,
            "error": "url_not_allowed",
            "allowed_hosts": ["www.sabina.com", "sabina.com"],
        }

    try:
        import catalog_engine as ce
    except Exception as exc:
        return {
            "ok": False, "diagnostic": "sabina-catalog-variants-read-only-v1",
            "read_only": True, "database_written": False,
            "error": "catalog_engine_import_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    report = {
        "ok": False,
        "diagnostic": "sabina-catalog-variants-read-only-v1",
        "read_only": True,
        "database_written": False,
        "refresh_called": False,
        "production_search_called": False,
        "product_matcher_called": False,
        "store": "sabina",
        "url": url,
        "query": q,
        "base_product_rows": [],
        "persisted_variants": [],
        "persisted_variant_count": 0,
        "local_search": {"called": False, "count": 0, "results": [], "error": None},
        "errors": [],
    }

    conn = None
    try:
        conn = ce.db()
        conn.row_factory = __import__("sqlite3").Row

        # Canonicalize only the URL host/trailing slash for matching. Do not
        # follow redirects, fetch pages, or alter stored URLs.
        url_key = url.rstrip("/")
        base_rows = conn.execute(
            """SELECT store,url,name,brand,sku,size_ml,price,currency,availability,
                      fetched_at
               FROM store_products
               WHERE store=? AND (url=? OR RTRIM(url,'/')=?)
               LIMIT 10""",
            ("sabina", url, url_key),
        ).fetchall()
        report["base_product_rows"] = [dict(row) for row in base_rows]

        variant_rows = conn.execute(
            """SELECT store,url,variant_key,name,brand,sku,gtin,mpn,size_ml,
                      concentration,gender,price,currency,availability,fetched_at
               FROM store_product_variants
               WHERE store=? AND (url=? OR RTRIM(url,'/')=?)
               ORDER BY size_ml,variant_key
               LIMIT 100""",
            ("sabina", url, url_key),
        ).fetchall()
        report["persisted_variants"] = [dict(row) for row in variant_rows]
        report["persisted_variant_count"] = len(variant_rows)
    except Exception as exc:
        report["errors"].append({
            "stage": "sqlite_read",
            "error": f"{type(exc).__name__}: {exc}",
        })
    finally:
        if conn is not None:
            conn.close()

    # Call the internal read-only implementation, not search_local(), because
    # the public wrapper may schedule background repairs for other retailers.
    try:
        local_impl = getattr(ce, "_search_local_impl", None)
        if not callable(local_impl):
            raise RuntimeError("_search_local_impl_unavailable")
        rows = local_impl(q, per_store=64, search_terms=[q])
        if not isinstance(rows, list):
            rows = []
        # Keep the response small and focused on this product family / URL.
        filtered = []
        needle = re.sub(r"[^a-z0-9]+", " ", q.lower()).strip()
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_url = str(row.get("url") or "").rstrip("/")
            row_name = str(row.get("name") or row.get("title") or "").lower()
            if row_url == url.rstrip("/") or ("born in roma" in row_name and "extradose" in row_name):
                filtered.append({
                    key: row.get(key)
                    for key in (
                        "store", "name", "canonical_name", "url", "catalog_id",
                        "sku", "size_ml", "price", "currency", "availability",
                        "variant", "variant_id", "source",
                    )
                    if key in row
                })
        report["local_search"] = {
            "called": True,
            "count": len(filtered),
            "results": filtered[:50],
            "error": None,
        }
    except Exception as exc:
        report["local_search"] = {
            "called": False, "count": 0, "results": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    report["elapsed_sec"] = round(time.monotonic() - started, 3)
    report["ok"] = not report["errors"] and report["local_search"]["error"] is None
    return report
