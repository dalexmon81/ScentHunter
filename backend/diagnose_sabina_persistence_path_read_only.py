from __future__ import annotations

import hashlib
import inspect
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Query

router = APIRouter()

DEFAULT_URL = (
    "https://www.sabina.com/es/perfumes-hombre/"
    "31433-born-in-roma-uomo-extradose-eau-de-parfum-valentino.html"
)


@router.get("/diagnose-sabina-persistence-path-read-only")
def diagnose_sabina_persistence_path_read_only(
    url: str = Query(DEFAULT_URL),
):
    started = time.monotonic()
    parsed = urlparse(url)

    out = {
        "ok": False,
        "diagnostic": "sabina-persistence-path-v1",
        "read_only": True,
        "database_written": False,
        "http_requests": 0,
        "refresh_url_called": False,
        "url": url,
        "runtime": {},
        "database": {},
        "rows": {
            "store_urls": [],
            "store_products": [],
            "variants": [],
            "hydration_queue": [],
        },
        "schema": {
            "indexes": [],
            "triggers": [],
        },
        "errors": [],
    }

    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.sabina.com", "sabina.com"}
    ):
        out["errors"].append({
            "stage": "input",
            "error": "url_not_allowed",
        })
        return out

    try:
        import catalog_engine as ce

        source = inspect.getsource(ce.refresh_url)
        source_lines = source.splitlines()

        out["runtime"] = {
            "catalog_engine_file": str(Path(ce.__file__).resolve()),
            "refresh_url_source_file": inspect.getsourcefile(ce.refresh_url),
            "refresh_url_sha256": hashlib.sha256(
                source.encode("utf-8")
            ).hexdigest(),
            "has_variant_insert": (
                "INSERT INTO store_product_variants" in source
            ),
            "has_variant_validation": (
                "valid_variants" in source
                and "variant_size > 0 and variant_price > 0" in source
            ),
            "has_store_urls_insert": (
                "INSERT INTO store_urls" in source
            ),
            "has_hydration_queue_insert": (
                "INSERT INTO hydration_queue" in source
            ),
            "variant_branch_lines": [
                {"line": i + 1, "text": line.strip()}
                for i, line in enumerate(source_lines)
                if (
                    "store_product_variants" in line
                    or "valid_variants" in line
                    or "item.get('variants')" in line
                )
            ],
        }

        db_path = Path(ce.DB_PATH).resolve()
        out["database"] = {
            "configured_path": str(ce.DB_PATH),
            "resolved_path": str(db_path),
            "exists": db_path.exists(),
            "is_file": db_path.is_file(),
        }

        if not db_path.is_file():
            out["errors"].append({
                "stage": "database",
                "error": "configured_database_missing",
            })
            return out

        # SQLite read-only URI: do not use ce.db(), which may run migrations.
        conn = sqlite3.connect(
            db_path.as_uri() + "?mode=ro",
            uri=True,
            timeout=3,
        )
        conn.row_factory = sqlite3.Row

        try:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }

            out["database"]["tables_present"] = {
                name: name in tables
                for name in (
                    "store_urls",
                    "store_products",
                    "store_product_variants",
                    "hydration_queue",
                )
            }

            # Exact URL plus slash-normalized URL, without changing stored data.
            key = url.rstrip("/")
            params = ("sabina", url, key)

            queries = {
                "store_urls": (
                    "SELECT store,url,slug,lastmod,discovered_at,active "
                    "FROM store_urls "
                    "WHERE store=? AND (url=? OR RTRIM(url,'/')=?) "
                    "LIMIT 20"
                ),
                "store_products": (
                    "SELECT store,url,name,brand,sku,size_ml,price,currency,"
                    "availability,fetched_at,fetch_status "
                    "FROM store_products "
                    "WHERE store=? AND (url=? OR RTRIM(url,'/')=?) "
                    "LIMIT 20"
                ),
                "variants": (
                    "SELECT store,url,variant_key,name,sku,size_ml,price,"
                    "currency,availability,fetched_at "
                    "FROM store_product_variants "
                    "WHERE store=? AND (url=? OR RTRIM(url,'/')=?) "
                    "ORDER BY size_ml,variant_key LIMIT 100"
                ),
                "hydration_queue": (
                    "SELECT store,url,state,attempts,available_at,"
                    "leased_until,last_started_at,last_finished_at,"
                    "last_error,last_http_status "
                    "FROM hydration_queue "
                    "WHERE store=? AND (url=? OR RTRIM(url,'/')=?) "
                    "LIMIT 20"
                ),
            }

            table_for_result = {
                "store_urls": "store_urls",
                "store_products": "store_products",
                "variants": "store_product_variants",
                "hydration_queue": "hydration_queue",
            }

            for label, sql in queries.items():
                table = table_for_result[label]
                if table not in tables:
                    out["errors"].append({
                        "stage": label,
                        "error": f"table_missing:{table}",
                    })
                    continue
                try:
                    out["rows"][label] = [
                        dict(row)
                        for row in conn.execute(sql, params).fetchall()
                    ]
                except Exception as exc:
                    out["errors"].append({
                        "stage": label,
                        "error": f"{type(exc).__name__}: {exc}",
                    })

            # Inspect actual SQLite metadata; do not create or rebuild anything.
            out["schema"]["indexes"] = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT type, name, tbl_name, sql
                    FROM sqlite_master
                    WHERE type='index'
                      AND tbl_name IN (
                        'store_urls',
                        'store_products',
                        'store_product_variants',
                        'hydration_queue'
                      )
                    ORDER BY tbl_name, name
                    """
                ).fetchall()
            ]

            out["schema"]["triggers"] = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT name, tbl_name, sql
                    FROM sqlite_master
                    WHERE type='trigger'
                      AND tbl_name IN (
                        'store_urls',
                        'store_products',
                        'store_product_variants',
                        'hydration_queue'
                      )
                    ORDER BY tbl_name, name
                    """
                ).fetchall()
            ]

            out["database"]["variant_rows_for_url"] = len(
                out["rows"]["variants"]
            )
            out["database"]["base_rows_for_url"] = len(
                out["rows"]["store_products"]
            )
            out["database"]["store_url_rows_for_url"] = len(
                out["rows"]["store_urls"]
            )

        finally:
            conn.close()

    except Exception as exc:
        out["errors"].append({
            "stage": "runtime_audit",
            "error": f"{type(exc).__name__}: {exc}",
        })

    out["elapsed_sec"] = round(time.monotonic() - started, 3)
    out["ok"] = not out["errors"]
    return out
