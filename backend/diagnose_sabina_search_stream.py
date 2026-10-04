"""
ScentHunter - Sabina/catalog coverage diagnostics.

Read-only scraper diagnostics plus one explicitly operational coverage runner
and one explicitly operational hydration runner.

The hydration runner is generic: it accepts a store + URL already present in
hydration_queue, forces exactly that durable queue item through the normal
catalog_engine.refresh_url() path, and reports the resulting queue state.
It contains no product-specific URL, name, or matching rule.
"""

import time
from fastapi import APIRouter, Query
import requests

router = APIRouter()

TARGET_41708 = (
    "https://www.sabina.com/es/perfumes-mujer/"
    "41708-liquid-brun-limited-edition-extrait-de-parfum.html"
)


@router.get("/diagnose-sabina-search-stream")
def diagnose_sabina_search_stream(
    q: str = Query("Liquid Brun", min_length=1, max_length=120),
):
    started = time.monotonic()
    try:
        from scrapers.sabina import scraper

        stream = getattr(scraper, "search_stream", None)
        if not callable(stream):
            return {
                "diagnostic": "sabina-search-stream-v1",
                "ok": False,
                "error": "search_stream not available",
                "read_only": True,
            }

        returned = stream(q)
        result_rows = []
        if isinstance(returned, dict):
            value = returned.get("results")
            if isinstance(value, list):
                result_rows = value

        compact = []
        for row in result_rows:
            if isinstance(row, dict):
                compact.append({
                    "name": row.get("name"),
                    "brand": row.get("brand"),
                    "price": row.get("price"),
                    "availability": row.get("availability"),
                    "available": row.get("available"),
                    "url": row.get("url"),
                    "identity": row.get("identity"),
                })

        return {
            "diagnostic": "sabina-search-stream-v1",
            "ok": True,
            "query": q,
            "return_type": type(returned).__name__,
            "return": {
                "status": returned.get("status") if isinstance(returned, dict) else None,
                "verified": returned.get("verified") if isinstance(returned, dict) else None,
                "error": returned.get("error") if isinstance(returned, dict) else None,
                "details": returned.get("details") if isinstance(returned, dict) else None,
                "results_count": len(result_rows),
                "results": compact,
            },
            "read_only": True,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        return {
            "diagnostic": "sabina-search-stream-v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "read_only": True,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }


@router.get("/diagnose-sabina-product-page")
def diagnose_sabina_product_page(
    url: str = Query(TARGET_41708, min_length=20, max_length=500),
    q: str = Query("Liquid Brun Limited Edition", min_length=1, max_length=120),
):
    """Read-only transport/parser isolation test."""
    started = time.monotonic()

    try:
        from scrapers.sabina import scraper

        session = requests.Session()
        try:
            response = session.get(
                url,
                headers=scraper.HEADERS,
                timeout=scraper.TIMEOUT,
                allow_redirects=True,
            )

            transport = {
                "status_code": response.status_code,
                "final_url": response.url,
                "bytes": len(response.content or b""),
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

            parsed = None
            parse_error = None
            if response.status_code < 400:
                try:
                    parsed = scraper.extract_product_page(session, url, q)
                except Exception as exc:
                    parse_error = f"{type(exc).__name__}: {exc}"

            compact = None
            if isinstance(parsed, dict):
                compact = {
                    "name": parsed.get("name"),
                    "brand": parsed.get("brand"),
                    "price": parsed.get("price"),
                    "available": parsed.get("available"),
                    "availability": parsed.get("availability"),
                    "url": parsed.get("url"),
                    "identity": parsed.get("identity"),
                    "attributes": parsed.get("attributes"),
                    "offer": parsed.get("offer"),
                    "provenance": parsed.get("provenance"),
                }

            return {
                "diagnostic": "sabina-product-page-v1",
                "ok": True,
                "query": q,
                "url": url,
                "transport": transport,
                "parser": {
                    "returned_product": parsed is not None,
                    "parse_error": parse_error,
                    "product": compact,
                },
                "read_only": True,
                "product_matcher_called": False,
                "catalog_written": False,
                "hydration_called": False,
                "elapsed_sec": round(time.monotonic() - started, 3),
            }
        finally:
            session.close()

    except Exception as exc:
        return {
            "diagnostic": "sabina-product-page-v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "read_only": True,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }


@router.get("/diagnose-sabina-discover-and-target")
def diagnose_sabina_discover_and_target(
    q: str = Query("Liquid Brun Limited Edition", min_length=1, max_length=120),
):
    """Read-only isolation of production discovery + the exact discovered target."""
    started = time.monotonic()
    target_token = "41708"

    try:
        from scrapers.sabina import scraper

        session = requests.Session()
        try:
            discovery_started = time.monotonic()
            candidates = scraper.discover_product_urls(session, q)
            discovery_elapsed = round(time.monotonic() - discovery_started, 3)

            target_urls = [url for url in candidates if target_token in str(url)]

            target_result = None
            target_error = None

            if target_urls:
                target_url = target_urls[0]
                parse_started = time.monotonic()
                try:
                    target_result = scraper.extract_product_page(
                        session, target_url, q
                    )
                except Exception as exc:
                    target_error = f"{type(exc).__name__}: {exc}"
                parse_elapsed = round(time.monotonic() - parse_started, 3)
            else:
                target_url = None
                parse_elapsed = None

            compact = None
            if isinstance(target_result, dict):
                compact = {
                    "name": target_result.get("name"),
                    "brand": target_result.get("brand"),
                    "price": target_result.get("price"),
                    "available": target_result.get("available"),
                    "availability": target_result.get("availability"),
                    "url": target_result.get("url"),
                    "identity": target_result.get("identity"),
                    "attributes": target_result.get("attributes"),
                    "offer": target_result.get("offer"),
                }

            return {
                "diagnostic": "sabina-discover-and-target-v1",
                "ok": True,
                "query": q,
                "discovery": {
                    "elapsed_sec": discovery_elapsed,
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                    "target_41708_found": bool(target_urls),
                    "target_urls": target_urls,
                },
                "target_parse": {
                    "url": target_url,
                    "elapsed_sec": parse_elapsed,
                    "returned_product": target_result is not None,
                    "error": target_error,
                    "product": compact,
                },
                "read_only": True,
                "production_search_called": False,
                "product_matcher_called": False,
                "catalog_written": False,
                "hydration_called": False,
                "elapsed_sec": round(time.monotonic() - started, 3),
            }
        finally:
            session.close()

    except Exception as exc:
        return {
            "diagnostic": "sabina-discover-and-target-v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "read_only": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }


@router.get("/diagnose-catalog-coverage-run")
def diagnose_catalog_coverage_run(
    store: str = Query("sabina", min_length=1, max_length=40),
    product_id: str = Query(..., min_length=1, max_length=120),
):
    """Explicitly advance one generic store x canonical-product coverage task."""
    started = time.monotonic()
    store_key = str(store or "").strip().lower()
    product_key = str(product_id or "").strip()

    try:
        from catalog_engine import (
            _coverage_ensure_schema,
            _coverage_load_catalog,
            _coverage_run_task,
            _coverage_finish_task,
        )

        _coverage_ensure_schema()
        products = _coverage_load_catalog()

        product = next(
            (
                p for p in products
                if str(p.get("product_id") or "").strip() == product_key
            ),
            None,
        )

        if product is None:
            return {
                "diagnostic": "catalog-coverage-run-v1",
                "ok": False,
                "error": "canonical_product_not_found",
                "store": store_key,
                "product_id": product_key,
                "catalog_written": False,
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        task = {"store": store_key, "product": product, "attempts": 0}
        result = _coverage_run_task(task)
        _coverage_finish_task(task, result)

        return {
            "diagnostic": "catalog-coverage-run-v1",
            "ok": True,
            "store": store_key,
            "product_id": product_key,
            "canonical_name": product.get("canonical_name"),
            "coverage_queries": __import__("catalog_engine")._coverage_queries(product),
            "result": result,
            "catalog_written": bool(result.get("found")),
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    except Exception as exc:
        return {
            "diagnostic": "catalog-coverage-run-v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "store": store_key,
            "product_id": product_key,
            "catalog_written": False,
            "hydration_called": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }


@router.get("/diagnose-catalog-hydration-run")
def diagnose_catalog_hydration_run(
    store: str = Query("sabina", min_length=1, max_length=40),
    url: str = Query(..., min_length=20, max_length=1000),
):
    """
    Operational single-queue-item hydration diagnostic.

    This is intentionally generic. It does not know any product name, brand,
    ID, or retailer-specific rule. It only accepts a URL already present in
    hydration_queue, claims that durable queue row, calls the exact normal
    catalog_engine.refresh_url() path, and records DONE/ERROR/DEAD.
    """
    started = time.monotonic()
    store_key = str(store or "").strip().lower()
    url_key = str(url or "").strip()

    try:
        from catalog_engine import db, refresh_url, STORES

        if store_key not in STORES:
            return {
                "diagnostic": "catalog-hydration-run-v1",
                "ok": False,
                "error": "unknown_store",
                "store": store_key,
                "url": url_key,
            }

        conn = db()
        try:
            row = conn.execute(
                """SELECT store,url,state,attempts,last_error,last_http_status,
                          last_started_at,last_finished_at,available_at,
                          leased_until,lease_token
                   FROM hydration_queue
                   WHERE store=? AND url=?""",
                (store_key, url_key),
            ).fetchone()

            if not row:
                return {
                    "diagnostic": "catalog-hydration-run-v1",
                    "ok": False,
                    "error": "url_not_in_hydration_queue",
                    "store": store_key,
                    "url": url_key,
                }

            previous = dict(row)
            if previous.get("state") == "PROCESSING":
                return {
                    "diagnostic": "catalog-hydration-run-v1",
                    "ok": False,
                    "error": "url_currently_processing",
                    "store": store_key,
                    "url": url_key,
                    "previous": previous,
                }

            if previous.get("state") == "DONE":
                return {
                    "diagnostic": "catalog-hydration-run-v1",
                    "ok": True,
                    "status": "ALREADY_DONE",
                    "store": store_key,
                    "url": url_key,
                    "previous": previous,
                }

            token = f"diagnose-{int(time.time() * 1000)}"
            now = time.time()
            updated = conn.execute(
                """UPDATE hydration_queue
                   SET state='PROCESSING',
                       leased_until=?,
                       lease_token=?,
                       last_started_at=?,
                       attempts=COALESCE(attempts,0)+1
                   WHERE store=? AND url=?
                     AND state IN ('PENDING','ERROR','DEAD')""",
                (now + 180.0, token, now, store_key, url_key),
            ).rowcount
            conn.commit()

            if updated != 1:
                return {
                    "diagnostic": "catalog-hydration-run-v1",
                    "ok": False,
                    "error": "queue_claim_failed",
                    "store": store_key,
                    "url": url_key,
                    "previous": previous,
                }
        finally:
            conn.close()

        item = None
        refresh_error = None
        try:
            item = refresh_url(store_key, url_key)
        except Exception as exc:
            refresh_error = f"{type(exc).__name__}: {exc}"

        conn = db()
        try:
            final_state = "DONE" if item and item.get("name") else "ERROR"
            last_error = None
            if final_state != "DONE":
                row = conn.execute(
                    """SELECT fetch_status
                       FROM store_products
                       WHERE store=? AND url=?""",
                    (store_key, url_key),
                ).fetchone()
                last_error = (
                    str(row["fetch_status"])
                    if row and row["fetch_status"]
                    else refresh_error or "product_parser_not_found"
                )

            conn.execute(
                """UPDATE hydration_queue
                   SET state=?,
                       leased_until=NULL,
                       lease_token=NULL,
                       last_finished_at=?,
                       last_error=?,
                       last_http_status=?
                   WHERE store=? AND url=? AND lease_token=?""",
                (
                    final_state,
                    time.time(),
                    last_error,
                    None,
                    store_key,
                    url_key,
                    token,
                ),
            )
            conn.commit()

            final_row = conn.execute(
                """SELECT store,url,state,attempts,last_error,last_http_status,
                          last_started_at,last_finished_at,available_at
                   FROM hydration_queue
                   WHERE store=? AND url=?""",
                (store_key, url_key),
            ).fetchone()

            product_row = conn.execute(
                """SELECT name,brand,price,currency,availability,
                          fetched_at,fetch_status
                   FROM store_products
                   WHERE store=? AND url=?""",
                (store_key, url_key),
            ).fetchone()
        finally:
            conn.close()

        return {
            "diagnostic": "catalog-hydration-run-v1",
            "ok": final_state == "DONE",
            "status": final_state,
            "store": store_key,
            "url": url_key,
            "refresh_returned_product": bool(item and item.get("name")),
            "product": dict(product_row) if product_row else None,
            "queue": dict(final_row) if final_row else None,
            "refresh_error": refresh_error,
            "catalog_written": bool(item and item.get("name")),
            "hydration_called": True,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    except Exception as exc:
        return {
            "diagnostic": "catalog-hydration-run-v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "store": store_key,
            "url": url_key,
            "hydration_called": True,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
