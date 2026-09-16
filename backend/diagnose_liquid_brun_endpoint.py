"""
ScentHunter — DIAGNOSTIC ONLY / v2

Endpoint:
    /diagnose-liquid-brun?q=Liquid%20Brun

Purpose:
    Diagnose the exact rejection point inside the existing central
    main.matches() validation for discovered candidates.

IMPORTANT:
    This file is diagnostic only. It does NOT modify:
      - ProductMatcher
      - family_registry
      - any scraper
      - main.py
      - frontend
    It temporarily traces the already-loaded main.matches() function
    while it is called for a candidate, then restores normal execution.
"""

from fastapi import APIRouter
import importlib
import inspect
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

router = APIRouter()

STORES = [
    "bplatz",
    "deloox",
    "parfumcity",
    "parfumzentrum",
    "perfumemarket",
    "sabina",
    "orioudh",
    "easycosmetic",
]

# Keep the HTTP response useful and bounded.
MAX_REJECTION_DETAILS = 80


def _main():
    return importlib.import_module("main")


def _safe_scalar(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_scalar(item) for item in value[:20]]
    if isinstance(value, dict):
        out = {}
        for key, item in list(value.items())[:30]:
            out[str(key)] = _safe_scalar(item)
        return out
    return str(value)


def _matches_source(main):
    try:
        source_lines, start_line = inspect.getsourcelines(main.matches)
        source = "".join(source_lines)
        return {
            "available": True,
            "start_line": start_line,
            "source": source,
        }
    except Exception as exc:
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _trace_matches(main, product, query):
    """
    Call the real main.matches() unchanged, but trace its return line.

    We do not reproduce or reimplement matches() here. The diagnostic
    observes the actual deployed function, so the evidence points to
    the code that is really running.
    """
    target_code = getattr(main.matches, "__code__", None)
    trace = {
        "result": None,
        "return_line": None,
        "return_source": "",
        "locals_at_return": {},
        "executed_lines": [],
    }

    source_info = _matches_source(main)
    source_by_abs_line = {}

    if source_info.get("available"):
        start = source_info["start_line"]
        lines = source_info["source"].splitlines()
        source_by_abs_line = {
            start + index: line
            for index, line in enumerate(lines)
        }

    def tracer(frame, event, arg):
        if frame.f_code is target_code:
            if event == "line":
                if frame.f_lineno not in trace["executed_lines"]:
                    trace["executed_lines"].append(frame.f_lineno)
            elif event == "return":
                trace["result"] = arg
                trace["return_line"] = frame.f_lineno
                trace["return_source"] = source_by_abs_line.get(
                    frame.f_lineno,
                    "",
                ).strip()
                trace["locals_at_return"] = {
                    key: _safe_scalar(value)
                    for key, value in frame.f_locals.items()
                    if key not in {"product"}
                }
        return tracer

    old_trace = sys.gettrace()
    try:
        sys.settrace(tracer)
        result = main.matches(product, query)
    finally:
        sys.settrace(old_trace)

    trace["result"] = bool(result)
    return trace


def _candidate_snapshot(main, product, query):
    try:
        search_text = main.product_search_text(product)
    except Exception:
        search_text = ""

    query_tokens = []
    try:
        query_tokens = str(query).lower().split()
    except Exception:
        pass

    return {
        "name": product.get("name", ""),
        "title": product.get("title", ""),
        "product_name": product.get("product_name", ""),
        "brand": product.get("brand", ""),
        "size_ml": main.product_size_ml(product),
        "concentration": main.product_concentration(product)
        if hasattr(main, "product_concentration")
        else "",
        "availability": main.product_availability(product)
        if hasattr(main, "product_availability")
        else "",
        "url": product.get("url", ""),
        "price": product.get("price", ""),
        "query_tokens": query_tokens,
        "search_text": search_text[:1200],
    }


def _run_one(store: str, query: str):
    main = _main()
    started = time.monotonic()

    row = {
        "store": store,
        "status": "ok",
        "raw": 0,
        "unique": 0,
        "valid": 0,
        "catalog": 0,
        "fallback": 0,
        "grouped": 0,
        "elapsed_sec": 0.0,
        "attempts": [],
        "products": [],
        "errors": [],
        "rejection_summary": {},
        "rejections": [],
    }

    try:
        module = main.load_scraper(store)

        search_fn = getattr(module, "search", None)
        if not callable(search_fn):
            search_fn = getattr(module, "scrape", None)

        if not callable(search_fn):
            raise RuntimeError("scraper senza search()/scrape()")

        attempts = main.build_search_attempts(store, query)
        row["attempts"] = attempts

        candidates = []
        seen = set()

        for attempt in attempts:
            try:
                results = search_fn(attempt) or []
            except Exception as exc:
                row["errors"].append({
                    "stage": "discovery",
                    "attempt": attempt,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            if not isinstance(results, list):
                continue

            row["raw"] += len(results)

            for item in results:
                if not isinstance(item, dict):
                    continue

                product = dict(item)
                product.setdefault("store", store)

                key = main.product_identity_key(product)
                if key in seen:
                    continue

                seen.add(key)

                product = main.resolve_actual_price(product)

                image = main.product_image(product)
                if image:
                    product["image"] = image

                candidates.append(product)

        row["unique"] = len(candidates)

        # The detailed trace is especially important for Easycosmetic,
        # because the previous diagnostic proved discovery succeeds there
        # (132 unique) but central validation returned zero.
        rejection_counter = Counter()
        rejected_details = []

        accepted_products = []

        for index, product in enumerate(candidates):
            try:
                trace = _trace_matches(main, product, query)

                if not trace["result"]:
                    return_line = trace.get("return_line")
                    return_source = trace.get("return_source", "")

                    summary_key = (
                        f"line {return_line}: {return_source}"
                        if return_line
                        else "unknown return point"
                    )
                    rejection_counter[summary_key] += 1

                    # Prioritize candidates whose search text actually
                    # contains the complete query terms.
                    search_text = ""
                    try:
                        search_text = main.product_search_text(product)
                    except Exception:
                        pass

                    query_tokens = [
                        token
                        for token in str(query).lower().split()
                        if token
                    ]
                    token_hits = {
                        token: token in search_text.lower()
                        for token in query_tokens
                    }

                    if len(rejected_details) < MAX_REJECTION_DETAILS:
                        rejected_details.append({
                            "candidate_index": index,
                            "candidate": _candidate_snapshot(
                                main,
                                product,
                                query,
                            ),
                            "query_token_hits": token_hits,
                            "matches_trace": {
                                "return_line": return_line,
                                "return_source": return_source,
                                "locals_at_return": trace.get(
                                    "locals_at_return",
                                    {},
                                ),
                                "executed_lines": trace.get(
                                    "executed_lines",
                                    [],
                                ),
                            },
                        })

                    continue

                row["valid"] += 1

                catalog_product = main._catalog_match(product, query)

                if catalog_product is not None:
                    row["catalog"] += 1
                    accepted = catalog_product
                else:
                    family = main._catalog_family_for_query(query)

                    if (
                        family is not None
                        and main._catalog_product_is_excluded(
                            product,
                            family,
                        )
                    ):
                        continue

                    row["fallback"] += 1
                    accepted = main._apply_generic_display_name(
                        product,
                        query,
                    )

                accepted_products.append(accepted)

                row["products"].append({
                    "name": (
                        accepted.get("name")
                        or accepted.get("display_name")
                        or ""
                    ),
                    "display_name": accepted.get(
                        "display_name",
                        "",
                    ),
                    "variant": accepted.get(
                        "variant",
                        "",
                    ),
                    "size_ml": main.product_size_ml(
                        accepted
                    ),
                    "price": accepted.get(
                        "price",
                        "",
                    ),
                    "url": accepted.get(
                        "url",
                        "",
                    ),
                    "catalog_variant": accepted.get(
                        "catalog_variant",
                        "",
                    ),
                    "family_id": accepted.get(
                        "family_id",
                        "",
                    ),
                })

            except Exception as exc:
                row["errors"].append({
                    "stage": "validation",
                    "candidate_index": index,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        propagated = main._propagate_catalog_identity(
            accepted_products
        )

        grouped = main._group_catalog_results(
            propagated
        )

        row["grouped"] = len(grouped)
        row["rejection_summary"] = dict(
            rejection_counter.most_common()
        )

        if store == "easycosmetic":
            row["matches_source"] = _matches_source(main)
            row["rejections"] = rejected_details

    except Exception as exc:
        row["status"] = "error"
        row["errors"].append({
            "stage": "store",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })

    row["elapsed_sec"] = round(
        time.monotonic() - started,
        3,
    )

    return row


@router.get("/diagnose-liquid-brun")
def diagnose_liquid_brun(
    q: str = "Liquid Brun",
):
    query = str(q or "").strip() or "Liquid Brun"
    started = time.monotonic()

    with ThreadPoolExecutor(
        max_workers=len(STORES),
        thread_name_prefix="diag",
    ) as pool:

        futures = {
            pool.submit(
                _run_one,
                store,
                query,
            ): store
            for store in STORES
        }

        rows = []

        for future in as_completed(futures):
            store = futures[future]

            try:
                rows.append(
                    future.result()
                )
            except Exception as exc:
                rows.append({
                    "store": store,
                    "status": "error",
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                })

    rows.sort(
        key=lambda item: (
            STORES.index(item["store"])
            if item.get("store") in STORES
            else 999
        )
    )

    easycosmetic = next(
        (
            item
            for item in rows
            if item.get("store") == "easycosmetic"
        ),
        None,
    )

    return {
        "diagnostic": True,
        "version": "v2_matches_trace",
        "query": query,
        "elapsed_sec": round(
            time.monotonic() - started,
            3,
        ),
        "stores": rows,
        "focus": {
            "store": "easycosmetic",
            "previous_proof": (
                "132 unique candidates reached central validation "
                "and 0 passed main.matches()"
            ),
            "new_evidence": (
                "v2 traces the real deployed main.matches() return "
                "line and locals for rejected Easycosmetic candidates"
            ),
            "easycosmetic_rejection_summary": (
                easycosmetic.get("rejection_summary", {})
                if easycosmetic
                else {}
            ),
        },
        "interpretation": {
            "raw_0": (
                "discovery/scraper did not return candidates"
            ),
            "unique_positive_valid_0": (
                "candidates discovered but rejected "
                "by central validation"
            ),
            "matches_trace_return_line": (
                "the exact source line where main.matches() "
                "returned False"
            ),
            "locals_at_return": (
                "local values at that return point; useful to prove "
                "which condition rejected the candidate"
            ),
            "valid_positive_grouped_lower": (
                "loss in catalog/grouping"
            ),
            "status_error": (
                "runtime/import/scraper execution problem"
            ),
        },
    }
