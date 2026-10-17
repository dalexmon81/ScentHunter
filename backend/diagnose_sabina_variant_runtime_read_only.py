"""Read-only runtime audit for Sabina variant persistence; no HTTP and no writes."""
from __future__ import annotations
import hashlib
import inspect
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse
from fastapi import APIRouter, Query

router = APIRouter()
DEFAULT_URL = "https://www.sabina.com/es/perfumes-mujer/31434-born-in-roma-donna-extradose-eau-de-parfum-valentino.html"

@router.get("/diagnose-sabina-variant-runtime-read-only")
def diagnose_sabina_variant_runtime_read_only(url: str = Query(DEFAULT_URL)):
    started = time.monotonic()
    parsed = urlparse(url)
    out = {
        "ok": False,
        "diagnostic": "sabina-variant-runtime-read-only-v1",
        "read_only": True,
        "database_written": False,
        "http_requests": 0,
        "store": "sabina",
        "url": url,
        "runtime": {},
        "database": {},
        "rows": {"base_product": [], "variants": [], "hydration_queue": []},
        "errors": [],
    }
    if parsed.scheme != "https" or parsed.hostname not in {"www.sabina.com", "sabina.com"}:
        out["errors"].append({"stage": "input", "error": "url_not_allowed"})
        return out
    try:
        import catalog_engine as ce
        source = inspect.getsource(ce.refresh_url)
        out["runtime"] = {
            "catalog_engine_file": str(Path(ce.__file__).resolve()),
            "refresh_url_source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "refresh_url_has_sabina_variant_insert": "INSERT INTO store_product_variants" in source and "store == 'sabina' and item.get('variants')" in source,
            "refresh_url_has_variant_validation": "valid_variants" in source and "variant_size > 0 and variant_price > 0" in source,
            "db_path_configured": str(getattr(ce, "DB_PATH", "")),
            "db_path_resolved": str(Path(getattr(ce, "DB_PATH", ".")).resolve()),
            "db_function_source_file": inspect.getsourcefile(ce.db),
            "refresh_url_source_file": inspect.getsourcefile(ce.refresh_url),
        }
        db_path = Path(getattr(ce, "DB_PATH", "" )).resolve()
        out["database"]["path_exists"] = db_path.exists()
        out["database"]["path_is_file"] = db_path.is_file()
        if not db_path.exists() or not db_path.is_file():
            out["errors"].append({"stage": "database", "error": "configured_db_path_missing_or_not_file"})
        else:
            # Open the exact configured DB path in SQLite read-only mode; do not call ce.db().
            conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=2)
            conn.row_factory = sqlite3.Row
            try:
                out["database"]["sqlite_version"] = sqlite3.sqlite_version
                tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                out["database"]["has_store_product_variants_table"] = "store_product_variants" in tables
                out["database"]["has_store_products_table"] = "store_products" in tables
                out["database"]["has_hydration_queue_table"] = "hydration_queue" in tables
                if "store_product_variants" in tables:
                    out["database"]["variant_table_columns"] = [dict(r) for r in conn.execute("PRAGMA table_info(store_product_variants)").fetchall()]
                key = url.rstrip("/")
                queries = [
                    ("base_product", "SELECT store,url,name,brand,sku,size_ml,price,currency,availability,fetched_at,fetch_status FROM store_products WHERE store=? AND (url=? OR RTRIM(url,'/')=?) LIMIT 10", ("sabina", url, key), "store_products"),
                    ("variants", "SELECT store,url,variant_key,name,brand,sku,size_ml,price,currency,availability,fetched_at FROM store_product_variants WHERE store=? AND (url=? OR RTRIM(url,'/')=?) ORDER BY size_ml,variant_key LIMIT 100", ("sabina", url, key), "store_product_variants"),
                    ("hydration_queue", "SELECT store,url,state,attempts,last_started_at,last_finished_at,last_error,last_http_status FROM hydration_queue WHERE store=? AND (url=? OR RTRIM(url,'/')=?) LIMIT 10", ("sabina", url, key), "hydration_queue"),
                ]
                for label, sql, params, table in queries:
                    if table not in tables:
                        out["errors"].append({"stage": label, "error": f"table_missing:{table}"})
                        continue
                    try:
                        out["rows"][label] = [dict(r) for r in conn.execute(sql, params).fetchall()]
                    except Exception as exc:
                        out["errors"].append({"stage": label, "error": f"{type(exc).__name__}: {exc}"})
                out["database"]["variant_rows_for_url"] = len(out["rows"]["variants"])
                out["database"]["base_rows_for_url"] = len(out["rows"]["base_product"])
            finally:
                conn.close()
    except Exception as exc:
        out["errors"].append({"stage": "runtime_audit", "error": f"{type(exc).__name__}: {exc}"})
    out["elapsed_sec"] = round(time.monotonic() - started, 3)
    out["ok"] = not out["errors"]
    return out
