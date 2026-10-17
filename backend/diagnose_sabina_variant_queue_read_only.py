"""Read-only diagnostic for Sabina variant persistence and hydration state."""
from __future__ import annotations
import time
from urllib.parse import urlparse
from fastapi import APIRouter, Query

router = APIRouter()
DEFAULT_URL = "https://www.sabina.com/es/perfumes-mujer/31434-born-in-roma-donna-extradose-eau-de-parfum-valentino.html"

@router.get("/diagnose-sabina-variant-queue-read-only")
def diagnose_sabina_variant_queue_read_only(url: str = Query(DEFAULT_URL)):
    started = time.monotonic()
    parsed = urlparse(url)
    base = {"ok": False, "diagnostic": "sabina-variant-queue-read-only-v1", "read_only": True,
            "database_written": False, "refresh_called": False, "http_called": False,
            "store": "sabina", "url": url, "hydration_queue_rows": [],
            "base_product_rows": [], "variant_rows": [], "errors": []}
    if parsed.scheme != "https" or parsed.hostname not in {"www.sabina.com", "sabina.com"}:
        base["errors"].append({"stage": "input", "error": "url_not_allowed"})
        return base
    try:
        import catalog_engine as ce
        import sqlite3
        conn = ce.db()
        conn.row_factory = sqlite3.Row
        try:
            # Exact URL first, then trailing-slash-normalized comparison only.
            key = url.rstrip("/")
            for label, sql, params in [
                ("hydration_queue", "SELECT store,url,state,attempts,available_at,first_seen_at,last_started_at,last_finished_at,last_error,last_http_status,leased_until FROM hydration_queue WHERE store=? AND (url=? OR RTRIM(url,'/')=?) LIMIT 10", ("sabina", url, key)),
                ("base_products", "SELECT store,url,name,brand,sku,size_ml,price,currency,availability,fetched_at,fetch_status FROM store_products WHERE store=? AND (url=? OR RTRIM(url,'/')=?) LIMIT 10", ("sabina", url, key)),
                ("variants", "SELECT store,url,variant_key,name,brand,sku,size_ml,price,currency,availability,fetched_at FROM store_product_variants WHERE store=? AND (url=? OR RTRIM(url,'/')=?) ORDER BY size_ml,variant_key LIMIT 100", ("sabina", url, key)),
            ]:
                try:
                    rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
                    if label == "hydration_queue": base["hydration_queue_rows"] = rows
                    elif label == "base_products": base["base_product_rows"] = rows
                    else: base["variant_rows"] = rows
                except Exception as exc:
                    base["errors"].append({"stage": label, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            conn.close()
    except Exception as exc:
        base["errors"].append({"stage": "database", "error": f"{type(exc).__name__}: {exc}"})
    base["elapsed_sec"] = round(time.monotonic() - started, 3)
    base["ok"] = not base["errors"]
    return base
