"""Read-only differential diagnostic for Sabina's exact catalog refresh parser path."""
from __future__ import annotations
import inspect
import time
from urllib.parse import urlparse
from fastapi import APIRouter, Query

router = APIRouter()
DEFAULT_URL = "https://www.sabina.com/es/perfumes-mujer/31434-born-in-roma-donna-extradose-eau-de-parfum-valentino.html"

@router.get("/diagnose-sabina-refresh-parser-read-only")
def diagnose_sabina_refresh_parser_read_only(url: str = Query(DEFAULT_URL)):
    started = time.monotonic()
    parsed_url = urlparse(url)
    out = {
        "ok": False,
        "diagnostic": "sabina-refresh-parser-read-only-v1",
        "read_only": True,
        "database_written": False,
        "refresh_url_called": False,
        "http_requests": 0,
        "store": "sabina",
        "url": url,
        "fetch": {},
        "parser": {},
        "persisted": {"base_product_rows": [], "variant_rows": [], "hydration_queue_rows": []},
        "errors": [],
    }
    if parsed_url.scheme != "https" or parsed_url.hostname not in {"www.sabina.com", "sabina.com"}:
        out["errors"].append({"stage": "input", "error": "url_not_allowed"})
        return out
    try:
        import catalog_engine as ce
        import importlib
        import sqlite3
        # Same single-fetch transport and exact retailer parser path as refresh_url,
        # but deliberately do not call refresh_url or any persistence helper.
        status, final_url, data = ce.http_get(url, timeout=ce.REFRESH_TIMEOUT)
        out["http_requests"] = 1
        out["fetch"] = {"status": status, "final_url": final_url, "bytes": len(data or b"")}
        if status >= 400 or not data:
            out["errors"].append({"stage": "fetch", "error": f"http_status={status};empty_body={not bool(data)}"})
        else:
            try:
                module = importlib.import_module("scrapers.sabina.scraper")
                parser = getattr(module, "extract_product_page", None)
                out["parser"]["module_imported"] = True
                out["parser"]["extract_product_page_callable"] = callable(parser)
                if callable(parser):
                    out["parser"]["signature"] = str(inspect.signature(parser))
                item = ce._secondary_store_parser("sabina", final_url, url, html_data=data)
                variants = item.get("variants") if isinstance(item, dict) and isinstance(item.get("variants"), list) else []
                summarized = []
                valid = []
                for v in variants:
                    if not isinstance(v, dict):
                        summarized.append({"type": type(v).__name__, "valid": False})
                        continue
                    size = v.get("size_ml")
                    price = v.get("price_num")
                    try:
                        size_num = float(size) if size is not None else None
                    except (TypeError, ValueError):
                        size_num = None
                    try:
                        price_num = float(price) if price is not None else None
                    except (TypeError, ValueError):
                        price_num = None
                    is_valid = bool(size_num and size_num > 0 and price_num and price_num > 0)
                    row = {"size_ml": size, "price_num": price, "sku": v.get("sku"), "name": v.get("name"), "valid_by_refresh_rules": is_valid}
                    summarized.append(row)
                    if is_valid:
                        valid.append(row)
                out["parser"].update({
                    "item_is_dict": isinstance(item, dict),
                    "item_name": item.get("name") if isinstance(item, dict) else None,
                    "item_brand": item.get("brand") if isinstance(item, dict) else None,
                    "item_sku": item.get("sku") if isinstance(item, dict) else None,
                    "item_size_ml": item.get("size_ml") if isinstance(item, dict) else None,
                    "item_price_num": item.get("price_num") if isinstance(item, dict) else None,
                    "variants_field_type": type(item.get("variants")).__name__ if isinstance(item, dict) else None,
                    "variant_count": len(variants),
                    "valid_variant_count": len(valid),
                    "variants": summarized,
                })
            except Exception as exc:
                out["errors"].append({"stage": "parser", "error": f"{type(exc).__name__}: {exc}"})
                out["parser"]["exception_type"] = type(exc).__name__
    except Exception as exc:
        out["errors"].append({"stage": "catalog_engine", "error": f"{type(exc).__name__}: {exc}"})
    # Read persisted state only after the isolated parser run; no mutation SQL.
    try:
        import catalog_engine as ce
        import sqlite3
        conn = ce.db()
        conn.row_factory = sqlite3.Row
        key = url.rstrip("/")
        queries = [
            ("base_product_rows", "SELECT store,url,name,brand,sku,size_ml,price,currency,availability,fetched_at,fetch_status FROM store_products WHERE store=? AND (url=? OR RTRIM(url,'/')=?) LIMIT 10", ("sabina", url, key)),
            ("variant_rows", "SELECT store,url,variant_key,name,brand,sku,size_ml,price,currency,availability,fetched_at FROM store_product_variants WHERE store=? AND (url=? OR RTRIM(url,'/')=?) ORDER BY size_ml,variant_key LIMIT 100", ("sabina", url, key)),
            ("hydration_queue_rows", "SELECT store,url,state,attempts,last_finished_at,last_error,last_http_status FROM hydration_queue WHERE store=? AND (url=? OR RTRIM(url,'/')=?) LIMIT 10", ("sabina", url, key)),
        ]
        try:
            for label, sql, params in queries:
                try:
                    out["persisted"][label] = [dict(row) for row in conn.execute(sql, params).fetchall()]
                except Exception as exc:
                    out["errors"].append({"stage": "db_" + label, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            conn.close()
    except Exception as exc:
        out["errors"].append({"stage": "database", "error": f"{type(exc).__name__}: {exc}"})
    out["elapsed_sec"] = round(time.monotonic() - started, 3)
    out["ok"] = not out["errors"]
    return out
