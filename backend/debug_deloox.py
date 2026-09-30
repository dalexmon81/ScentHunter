"""ScentHunter - read-only Deloox real-crawler branch trace.

This diagnostic executes the real catalog_engine._discover_deloox_catalog()
without changing catalog data, hydration state, matcher state, or resync state.
It traces the actual process_page -> _html_listing_url -> add_fair -> add flow.
"""
from __future__ import annotations

import sys
import time
import traceback
from fastapi import APIRouter, Query

router = APIRouter()


def _norm_url(value):
    return str(value or "").split("#", 1)[0]


def _has_target(value, target):
    return str(target or "").strip().lower() in str(value or "").lower()


def _real_deloox_trace(target="Rasasi", max_pages=800, max_depth=8):
    import catalog_engine as ce

    target = str(target or "Rasasi").strip() or "Rasasi"
    seeds = list(dict.fromkeys(ce.HTML_DISCOVERY_SEEDS.get("deloox", ())))
    started = time.time()

    report = {
        "diagnostic": "deloox-real-crawler-branch-trace-read-only-v2",
        "ok": True,
        "read_only": True,
        "store": "Deloox",
        "target": target,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "hydration_called": False,
        "resync_called": False,
        "catalog_engine_module": getattr(ce, "__file__", None),
        "discover_function": "_discover_deloox_catalog",
        "parameters": {"max_pages": max_pages, "max_depth": max_depth},
        "seeds": seeds,
        "html_target_hits": [],
        "listing_url_checks": [],
        "fair_fanout": [],
        "queue_admission": [],
        "processed_pages": [],
        "summary": {},
    }

    # State is keyed by target URL and source page so repeated appearances are
    # retained only when they provide a distinct stage observation.
    seen_records = set()
    processed_urls = set()
    queued_urls = set()
    fair_target_calls = 0
    fair_calls = 0

    def add_record(bucket, item, key_fields=None):
        if key_fields is None:
            key_fields = sorted(item.keys())
        key = tuple((k, repr(item.get(k))) for k in key_fields)
        if key in seen_records:
            return
        seen_records.add(key)
        bucket.append(item)

    def trace(frame, event, arg):
        nonlocal fair_target_calls, fair_calls

        name = frame.f_code.co_name
        if name not in {
            "process_page",
            "_html_listing_url",
            "add_fair",
            "add",
            "_discover_deloox_catalog",
        }:
            return trace

        loc = frame.f_locals

        # Definitive "page processed" observation: process_page was actually
        # entered with requested == the target URL.
        if name == "process_page" and event == "call":
            requested = _norm_url(loc.get("requested"))
            if _has_target(requested, target):
                processed_urls.add(requested)
                add_record(
                    report["processed_pages"],
                    {
                        "requested": requested,
                        "final": loc.get("final"),
                        "depth": loc.get("depth"),
                        "source": loc.get("source"),
                        "stage": "PROCESS_PAGE_ENTRY",
                    },
                    ["requested", "depth", "source"],
                )

        # Stage 1/3: trace the actual _html_listing_url call and return for
        # target-containing raw URLs. This is the exact function used by add()
        # and by process_page's link classification.
        if name == "_html_listing_url":
            raw = loc.get("raw_url")
            base = loc.get("base_url")
            label = loc.get("label")
            if _has_target(raw, target) or _has_target(base, target) or _has_target(label, target):
                if event == "call":
                    add_record(
                        report["listing_url_checks"],
                        {
                            "stage": "HTML_LISTING_URL_CALL",
                            "store": loc.get("store"),
                            "raw_url": raw,
                            "base_url": base,
                            "label": label,
                        },
                        ["stage", "raw_url", "base_url", "label"],
                    )
                elif event == "return":
                    add_record(
                        report["listing_url_checks"],
                        {
                            "stage": "HTML_LISTING_URL_RETURN",
                            "store": loc.get("store"),
                            "raw_url": raw,
                            "base_url": base,
                            "label": label,
                            "returned_url": _norm_url(arg) if arg else None,
                            "accepted": bool(arg),
                        },
                        ["stage", "raw_url", "base_url", "returned_url"],
                    )

        # Stage 1/2: process_page's real listing_links list. This is the list
        # that is subsequently passed to add_fair(), so positions are exact.
        if name == "process_page":
            listing_links = loc.get("listing_links")
            if isinstance(listing_links, list):
                for idx, value in enumerate(listing_links):
                    if _has_target(value, target):
                        url = _norm_url(value)
                        add_record(
                            report["html_target_hits"],
                            {
                                "stage": "TARGET_IN_REAL_LISTING_LINKS",
                                "page": loc.get("requested"),
                                "final": loc.get("final"),
                                "depth": loc.get("depth"),
                                "source": loc.get("source"),
                                "original_position": idx,
                                "listing_count": len(listing_links),
                                "url": url,
                            },
                            ["stage", "page", "url", "original_position"],
                        )

        # Stages 4/5: inspect the exact list received by add_fair().
        if name == "add_fair":
            listings = loc.get("listings")
            unique = loc.get("unique")
            fair_calls += 1

            if isinstance(listings, list):
                hits = [
                    (idx, _norm_url(value))
                    for idx, value in enumerate(listings)
                    if _has_target(value, target)
                ]
                if hits:
                    fair_target_calls += 1
                    add_record(
                        report["fair_fanout"],
                        {
                            "stage": "ADD_FAIR_INPUT",
                            "depth": loc.get("depth"),
                            "source": loc.get("source"),
                            "input_count": len(listings),
                            "target_positions": hits,
                            "fair_fanout": 640,
                        },
                        ["stage", "depth", "source", "input_count", "target_positions"],
                    )

            if isinstance(unique, list) and isinstance(listings, list):
                hits = [
                    (idx, _norm_url(value))
                    for idx, value in enumerate(unique)
                    if _has_target(value, target)
                ]
                if hits:
                    add_record(
                        report["fair_fanout"],
                        {
                            "stage": "TARGET_PRESENT_IN_UNIQUE",
                            "depth": loc.get("depth"),
                            "source": loc.get("source"),
                            "unique_count": len(unique),
                            "target_positions": hits,
                        },
                        ["stage", "depth", "source", "unique_count", "target_positions"],
                    )

                # Once the sampling assignment has executed, the local
                # 'unique' list becomes the selected <=640 items. A target that
                # was in the input but is absent here was discarded by the real
                # FAIR_FANOUT sampling.
                input_hits = [
                    (idx, _norm_url(value))
                    for idx, value in enumerate(listings)
                    if _has_target(value, target)
                ]
                if input_hits and len(listings) > 640 and not hits:
                    add_record(
                        report["fair_fanout"],
                        {
                            "stage": "ELIMINATED_BY_FAIR_FANOUT",
                            "depth": loc.get("depth"),
                            "source": loc.get("source"),
                            "input_count": len(listings),
                            "fair_fanout": 640,
                            "target_positions": input_hits,
                            "selected": False,
                        },
                        ["stage", "depth", "source", "input_count", "target_positions"],
                    )

        # Stage 6: actual add() return. Inspect the real queued set after the
        # function has executed, so admission is not inferred from intent.
        if name == "add" and _has_target(loc.get("url"), target) and event == "return":
            url = _norm_url(loc.get("url"))
            queued = loc.get("queued")
            visited = loc.get("visited")
            in_queue = isinstance(queued, set) and url in queued
            already_visited = isinstance(visited, set) and url in visited
            if in_queue:
                queued_urls.add(url)
            add_record(
                report["queue_admission"],
                {
                    "stage": "ADD_RETURN",
                    "url": url,
                    "depth": loc.get("depth"),
                    "source": loc.get("source"),
                    "queued": in_queue,
                    "already_visited": already_visited,
                },
                ["stage", "url", "depth", "source", "queued", "already_visited"],
            )

        return trace

    old_trace = sys.gettrace()
    try:
        sys.settrace(trace)
        # Use the production function's own caps; max_pages/max_depth are
        # diagnostic metadata only and are not used to mutate production state.
        deadline = time.time() + 120
        result = ce._discover_deloox_catalog(seeds, deadline)
    finally:
        sys.settrace(old_trace)

    # Determine final queue/process state from the real trace plus the real
    # crawler's returned aggregate state. No second crawl is performed.
    all_target_urls = set(queued_urls) | processed_urls
    for item in report["html_target_hits"]:
        all_target_urls.add(item["url"])

    for url in sorted(all_target_urls):
        queued = url in queued_urls
        processed = url in processed_urls
        report["processed_pages"].append(
            {
                "url": url,
                "queued": queued,
                "processed": processed,
                "conclusion": (
                    "PROCESSED"
                    if processed
                    else "QUEUED_BUT_NOT_PROCESSED_WITHIN_BUDGET"
                    if queued
                    else "NOT_QUEUED"
                ),
            }
        )

    eliminated = any(
        x.get("stage") == "ELIMINATED_BY_FAIR_FANOUT"
        for x in report["fair_fanout"]
    )
    html_found = bool(report["html_target_hits"])
    passed_add_fair = fair_target_calls > 0
    added_queue = bool(queued_urls)
    processed = bool(processed_urls)
    out_of_budget = any(
        x.get("conclusion") == "QUEUED_BUT_NOT_PROCESSED_WITHIN_BUDGET"
        for x in report["processed_pages"]
    )

    report["summary"] = {
        "target_found_in_html": html_found,
        "target_html_occurrences": len(report["html_target_hits"]),
        "target_passed_to_add_fair": passed_add_fair,
        "target_eliminated_by_fair_fanout": eliminated,
        "target_added_to_queue": added_queue,
        "target_processed": processed,
        "target_out_of_budget": out_of_budget,
        "fair_fanout": 640,
        "add_fair_calls": fair_calls,
        "add_fair_target_calls": fair_target_calls,
        "crawler_return": {
            "visited": result.get("visited"),
            "successes": result.get("successes"),
            "product_count": len(result.get("product_urls") or {}),
            "error_count": len(result.get("errors") or []),
        },
    }
    report["elapsed_sec"] = round(time.time() - started, 3)
    return report


@router.get("/diagnose-deloox-real-branch")
def diagnose_deloox_real_branch(
    target: str = Query("Rasasi", min_length=2),
    max_pages: int = Query(800, ge=1, le=800),
    max_depth: int = Query(8, ge=0, le=10),
):
    try:
        return _real_deloox_trace(target=target, max_pages=max_pages, max_depth=max_depth)
    except Exception as exc:
        return {
            "diagnostic": "deloox-real-crawler-branch-trace-read-only-v2",
            "ok": False,
            "read_only": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
