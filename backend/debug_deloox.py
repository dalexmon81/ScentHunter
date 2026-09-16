from __future__ import annotations

import importlib
import time
import traceback

from fastapi import APIRouter

router = APIRouter(prefix="/api/debug", tags=["debug-scenthunter"])

TARGET_ID = "1391716"
TARGET_QUERY = "Born in Roma"


def _has_target(row):
    if not isinstance(row, dict):
        return False

    url = str(
        row.get("url")
        or row.get("product_url")
        or ""
    )

    product_id = str(
        row.get("store_product_id")
        or row.get("product_id")
        or row.get("sku")
        or ""
    )

    return TARGET_ID in url or TARGET_ID == product_id


def _compact(row):
    if not isinstance(row, dict):
        return {
            "type": type(row).__name__,
            "value": repr(row),
        }

    keys = [
        "store",
        "shop",
        "brand",
        "name",
        "price",
        "price_num",
        "url",
        "available",
        "availability",
        "size_ml",
        "catalog_id",
        "family_id",
        "family_name",
        "canonical_name",
        "canonical_brand",
        "catalog_variant",
        "match_method",
        "match_score",
        "product_identity",
        "variant_id",
    ]

    return {
        key: row.get(key)
        for key in keys
        if key in row
    }


@router.get("/deloox-frontend-trace")
def deloox_frontend_trace(q: str = TARGET_QUERY):
    """
    TEST 16

    Traces Deloox product 1391716 through the exact ScentHunter
    backend layers used by /test-store:

        Deloox search()
        -> raw rows
        -> clean_result()
        -> ProductMatcher / family identity
        -> run_store()
        -> dedupe_results()
        -> sort_results()

    Diagnostic only. No production files are modified.
    """

    out = {
        "ok": True,
        "test": "TEST_16_DELOOX_SCENTHUNTER_FRONTEND_TRACE",
        "query": q,
        "target": {
            "id": TARGET_ID,
            "name": "Valentino Born in Roma Purple Melancholia Donna",
        },
    }

    try:
        main = importlib.import_module("main")

        out["runtime"] = {
            "main_file": getattr(main, "__file__", ""),
            "app_version": getattr(main, "APP_VERSION", None),
            "stores": getattr(main, "STORES", None),
        }

        # ------------------------------------------------------------
        # 1. Exact Deloox scraper output
        # ------------------------------------------------------------
        scraper = importlib.import_module(
            "scrapers.deloox.scraper"
        )

        started = time.perf_counter()
        raw = scraper.search(q)
        raw_rows = (
            []
            if raw is None
            else list(raw)
            if not isinstance(raw, list)
            else raw
        )

        target_raw = [
            row
            for row in raw_rows
            if _has_target(row)
        ]

        out["deloox_search"] = {
            "elapsed": round(
                time.perf_counter() - started,
                3,
            ),
            "count": len(raw_rows),
            "target_found": bool(target_raw),
            "target_rows": [
                _compact(row)
                for row in target_raw
            ],
        }

        # ------------------------------------------------------------
        # 2. Exact clean_result() stage
        # ------------------------------------------------------------
        clean_fn = getattr(main, "clean_result", None)

        cleaned_rows = []
        clean_errors = []
        target_cleaned = []

        if not callable(clean_fn):
            out["clean_result"] = {
                "ok": False,
                "error": "main.clean_result is not callable",
            }
        else:
            for index, row in enumerate(raw_rows):
                if not isinstance(row, dict):
                    continue

                try:
                    cleaned = clean_fn(
                        row,
                        "deloox",
                        q,
                    )

                    if cleaned is not None:
                        cleaned_rows.append(cleaned)

                        if _has_target(cleaned):
                            target_cleaned.append(cleaned)

                except Exception as exc:
                    clean_errors.append({
                        "index": index,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "row": _compact(row),
                    })

            out["clean_result"] = {
                "ok": True,
                "input_count": len(raw_rows),
                "output_count": len(cleaned_rows),
                "target_found": bool(target_cleaned),
                "target_rows": [
                    _compact(row)
                    for row in target_cleaned
                ],
                "error_count": len(clean_errors),
                "errors_for_target": [
                    error
                    for error in clean_errors
                    if TARGET_ID in str(error)
                ],
            }

        # ------------------------------------------------------------
        # 3. Direct ProductMatcher trace on target
        # ------------------------------------------------------------
        matcher_trace = {
            "available": False,
        }

        try:
            matcher_module = importlib.import_module(
                "product_matcher"
            )

            matcher_trace["module_file"] = getattr(
                matcher_module,
                "__file__",
                "",
            )

            matcher = getattr(
                matcher_module,
                "ProductMatcher",
                None,
            )

            if callable(matcher):
                matcher_trace["available"] = True

                # Recover the same catalog/family data used by main,
                # when those objects are exposed by the runtime.
                catalog = getattr(
                    main,
                    "CATALOG",
                    None,
                )

                family_registry = getattr(
                    main,
                    "FAMILY_REGISTRY",
                    None,
                )

                matcher_trace["main_catalog_present"] = (
                    catalog is not None
                )

                matcher_trace["main_family_registry_present"] = (
                    family_registry is not None
                )

                target_offer = (
                    target_cleaned[0]
                    if target_cleaned
                    else (
                        target_raw[0]
                        if target_raw
                        else None
                    )
                )

                if target_offer is not None:
                    try:
                        if catalog is not None:
                            instance = matcher(
                                catalog=catalog,
                                family_registry=family_registry,
                            )
                            matched = instance.match(
                                target_offer,
                                q,
                            )

                            matcher_trace["match"] = {
                                "returned": bool(matched),
                                "row": (
                                    _compact(matched)
                                    if matched
                                    else None
                                ),
                            }
                        else:
                            matcher_trace["match"] = {
                                "skipped": True,
                                "reason": (
                                    "main does not expose CATALOG"
                                ),
                            }

                    except Exception as exc:
                        matcher_trace["match"] = {
                            "ok": False,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }

        except Exception as exc:
            matcher_trace["error"] = {
                "type": type(exc).__name__,
                "error": str(exc),
            }

        out["product_matcher"] = matcher_trace

        # ------------------------------------------------------------
        # 4. Exact run_store("deloox", q)
        # ------------------------------------------------------------
        run_store = getattr(main, "run_store", None)

        if not callable(run_store):
            out["run_store"] = {
                "ok": False,
                "error": "main.run_store is not callable",
            }
        else:
            try:
                started = time.perf_counter()

                report = run_store(
                    "deloox",
                    q,
                )

                results = (
                    report.get("results", [])
                    if isinstance(report, dict)
                    else []
                )

                target_results = [
                    row
                    for row in results
                    if _has_target(row)
                ]

                out["run_store"] = {
                    "ok": True,
                    "elapsed": round(
                        time.perf_counter() - started,
                        3,
                    ),
                    "status": (
                        report.get("status")
                        if isinstance(report, dict)
                        else None
                    ),
                    "count": (
                        report.get("count")
                        if isinstance(report, dict)
                        else len(results)
                    ),
                    "target_found": bool(target_results),
                    "target_rows": [
                        _compact(row)
                        for row in target_results
                    ],
                    "report_error": (
                        report.get("error")
                        if isinstance(report, dict)
                        else None
                    ),
                }

            except Exception as exc:
                out["run_store"] = {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }

        # ------------------------------------------------------------
        # 5. Dedupe + sort exactly as main does
        # ------------------------------------------------------------
        dedupe_fn = getattr(
            main,
            "dedupe_results",
            None,
        )

        sort_fn = getattr(
            main,
            "sort_results",
            None,
        )

        pipeline_rows = []

        if isinstance(
            out.get("run_store"),
            dict,
        ) and out["run_store"].get("ok"):
            # Re-run report to keep this stage independent and explicit.
            try:
                report2 = run_store(
                    "deloox",
                    q,
                )

                pipeline_rows = list(
                    report2.get("results", [])
                )

            except Exception:
                pipeline_rows = []

        dedupe_target = []
        sorted_target = []

        if callable(dedupe_fn):
            try:
                deduped = dedupe_fn(
                    pipeline_rows
                )

                dedupe_target = [
                    row
                    for row in deduped
                    if _has_target(row)
                ]

                out["dedupe"] = {
                    "input_count": len(pipeline_rows),
                    "output_count": len(deduped),
                    "target_found": bool(dedupe_target),
                    "target_rows": [
                        _compact(row)
                        for row in dedupe_target
                    ],
                }

                pipeline_rows = deduped

            except Exception as exc:
                out["dedupe"] = {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
        else:
            out["dedupe"] = {
                "ok": False,
                "error": "main.dedupe_results not callable",
            }

        if callable(sort_fn):
            try:
                sorted_rows = sort_fn(
                    pipeline_rows
                )

                sorted_target = [
                    row
                    for row in sorted_rows
                    if _has_target(row)
                ]

                out["sort"] = {
                    "input_count": len(pipeline_rows),
                    "output_count": len(sorted_rows),
                    "target_found": bool(sorted_target),
                    "target_index": next(
                        (
                            index
                            for index, row
                            in enumerate(sorted_rows)
                            if _has_target(row)
                        ),
                        None,
                    ),
                    "target_rows": [
                        _compact(row)
                        for row in sorted_target
                    ],
                }

            except Exception as exc:
                out["sort"] = {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
        else:
            out["sort"] = {
                "ok": False,
                "error": "main.sort_results not callable",
            }

        # ------------------------------------------------------------
        # 6. Final diagnosis
        # ------------------------------------------------------------
        raw_found = bool(target_raw)
        cleaned_found = bool(target_cleaned)
        run_store_found = bool(
            out.get("run_store", {}).get(
                "target_found"
            )
        )
        dedupe_found = bool(
            out.get("dedupe", {}).get(
                "target_found"
            )
        )
        sorted_found = bool(
            out.get("sort", {}).get(
                "target_found"
            )
        )

        out["diagnosis"] = {
            "raw_deloox_found": raw_found,
            "clean_result_found": cleaned_found,
            "run_store_found": run_store_found,
            "dedupe_found": dedupe_found,
            "sort_found": sorted_found,
            "lost_raw_to_clean": (
                raw_found and not cleaned_found
            ),
            "lost_clean_to_run_store": (
                cleaned_found and not run_store_found
            ),
            "lost_run_store_to_dedupe": (
                run_store_found and not dedupe_found
            ),
            "lost_dedupe_to_sort": (
                dedupe_found and not sorted_found
            ),
            "FINAL_TARGET_PRESENT": sorted_found,
        }

        return out

    except Exception as exc:
        out["ok"] = False
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)
        out["traceback"] = traceback.format_exc()
        return out
