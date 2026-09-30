"""ScentHunter - read-only Deloox real-crawler branch trace.

Temporary diagnostic router. It executes the deployed catalog_engine
_discover_deloox_catalog() itself and traces the actual nested add/add_fair/
process_page flow. It never writes the catalog, hydration queue, or sync state.
"""
from __future__ import annotations

import sys
import time
import traceback
import urllib.parse
from fastapi import APIRouter, Query

router = APIRouter()


def _norm_url(value: str) -> str:
    return str(value or "").split("#", 1)[0]


def _has_target(value: str, target: str) -> bool:
    return str(target or "").strip().lower() in str(value or "").lower()


def _real_deloox_trace(target: str = "Rasasi", max_pages: int = 800, max_depth: int = 8):
    import catalog_engine as ce

    target = str(target or "Rasasi").strip()
    if not target:
        target = "Rasasi"

    seeds = list(dict.fromkeys(ce.HTML_DISCOVERY_SEEDS.get("deloox", ())))
    started = time.time()
    report = {
        "diagnostic": "deloox-real-crawler-branch-trace-read-only-v1",
        "ok": True,
        "store": "Deloox",
        "target": target,
        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "hydration_called": False,
        "resync_called": False,
        "catalog_engine_module": getattr(ce, "__file__", None),
        "discover_function": "_discover_deloox_catalog",
        "parameters": {"max_pages": max_pages, "max_depth": max_depth},
        "seeds": seeds,
        "target_found_in_html": [],
        "listing_admission": [],
        "fair_fanout": [],
        "queue_admission": [],
        "processed": [],
        "summary": {},
    }

    target_candidates = []
    target_seen = set()
    addfair_calls = 0
    addfair_target_calls = 0
    queue_target_seen = set()
    processed_target_seen = set()
    eliminated_target_seen = set()

    def record_once(bucket, item):
        key = repr(item)
        if key in bucket:
            return False
        bucket.add(key)
        return True

    def trace(frame, event, arg):
        nonlocal addfair_calls, addfair_target_calls
        name = frame.f_code.co_name
        if name not in {"process_page", "add_fair", "add", "_discover_deloox_catalog"}:
            return trace

        loc = frame.f_locals

        # 1/2/3: HTML extraction -> original position -> _html_listing_url result.
        if name == "process_page":
            listing_links = loc.get("listing_links")
            if isinstance(listing_links, list):
                for idx, value in enumerate(listing_links):
                    if _has_target(value, target):
                        key = _norm_url(value)
                        if key not in target_seen:
                            target_seen.add(key)
                            entry = {
                                "page": loc.get("requested"),
                                "final": loc.get("final"),
                                "depth": loc.get("depth"),
                                "source": loc.get("source"),
                                "original_position": idx,
                                "listing_count_at_observation": len(listing_links),
                                "url": key,
                                "stage": "listing_links",
                            }
                            report["target_found_in_html"].append(entry)
                            target_candidates.append(key)

        # 4/5: actual add_fair() receives the real listing list and then
        # performs the real FAIR_FANOUT sampling.
        if name == "add_fair":
            listings = loc.get("listings")
            unique = loc.get("unique")
            addfair_calls += 1

            if isinstance(listings, list):
                hits = [
                    (idx, _norm_url(value))
                    for idx, value in enumerate(listings)
                    if _has_target(value, target)
                ]
                if hits:
                    addfair_target_calls += 1
                    report["fair_fanout"].append({
                        "event": event,
                        "phase": "input",
                        "depth": loc.get("depth"),
                        "source": loc.get("source"),
                        "input_count": len(listings),
                        "target_positions": hits,
                        "fair_fanout": loc.get("FAIR_FANOUT", 640),
                    })

            if isinstance(unique, list):
                hits = [
                    (idx, _norm_url(value))
                    for idx, value in enumerate(unique)
                    if _has_target(value, target)
                ]
                if hits:
                    report["fair_fanout"].append({
                        "event": event,
                        "phase": "unique_before_or_after_sampling",
                        "depth": loc.get("depth"),
                        "source": loc.get("source"),
                        "unique_count": len(unique),
                        "target_positions": hits,
                        "target_present_after_sampling": True,
                    })

        # add_fair() does not expose FAIR_FANOUT as a local. Infer it from the
        # actual function behavior: if input > 640 and target disappears from
        # unique after line 954, it was eliminated by sampling.
        if name == "add_fair" and isinstance(loc.get("listings"), list):
            listings = loc["listings"]
            target_inputs = [
                (idx, _norm_url(v))
                for idx, v in enumerate(listings)
                if _has_target(v, target)
            ]
            unique = loc.get("unique")
            if target_inputs and isinstance(unique, list):
                target_unique = [
                    _norm_url(v) for v in unique if _has_target(v, target)
                ]
                if len(listings) > 640 and not target_unique:
                    for idx, key in target_inputs:
                        dedupe_key = f"{key}|{idx}|{loc.get('source')}"
                        if record_once(eliminated_target_seen, dedupe_key):
                            report["fair_fanout"].append({
                                "event": event,
                                "phase": "ELIMINATED_BY_FAIR_FANOUT",
                                "depth": loc.get("depth"),
                                "source": loc.get("source"),
                                "input_count": len(listings),
                                "target_original_position": idx,
                                "target_url": key,
                                "fair_fanout": 640,
                                "selected": False,
                            })

        # 6: actual nested add() queue admission. Return events let us inspect
        # the real queued set after the function body has completed.
        if name == "add" and _has_target(loc.get("url"), target):
            url = _norm_url(loc.get("url"))
            if event == "return":
                queued = loc.get("queued")
                visited = loc.get("visited")
                in_queue = url in queued if isinstance(queued, set) else False
                already_visited = url in visited if isinstance(visited, set) else False
                key = f"{url}|{in_queue}|{already_visited}|{loc.get('source')}"
                if record_once(queue_target_seen, key):
                    report["queue_admission"].append({
                        "url": url,
                        "depth": loc.get("depth"),
                        "source": loc.get("source"),
                        "queued": in_queue,
                        "already_visited": already_visited,
                        "stage": "add_return",
                    })

        # 7: after the real crawler completes, final visited/queue state is
        # inspected below. We deliberately do not alter queue/visited.
        return trace

    old_trace = sys.gettrace()
    try:
        sys.settrace(trace)
        deadline = time.time() + 120
        result = ce._discover_deloox_catalog(seeds, deadline)
    finally:
        sys.settrace(old_trace)

    # The actual function returns only aggregate state, so the diagnostic
    # derives the final process/budget conclusion from the traced queue events
    # and the returned product set. No second crawl is performed.
    queued_targets = {
        x["url"] for x in report["queue_admission"] if x.get("queued")
    }
    discovered_targets = {
        x["url"] for x in target_candidates
    }

    for url in sorted(discovered_targets | queued_targets):
        processed = False
        # A target URL appearing as a requested page is observable through the
        # process_page trace; target pages are the exact URLs the real crawler
        # fetched, not a synthetic reconstruction.
        for item in report["target_found_in_html"]:
            if item.get("page") == url:
                processed = True
                break
        entry = {
            "url": url,
            "queued": url in queued_targets,
            "processed": processed,
            "conclusion": (
                "PROCESSED" if processed else
                "QUEUED_BUT_NOT_PROCESSED_WITHIN_BUDGET" if url in queued_targets else
                "NOT_QUEUED"
            ),
        }
        report["processed"].append(entry)
        if processed:
            processed_target_seen.add(url)

    eliminated = [
        x for x in report["fair_fanout"]
        if x.get("phase") == "ELIMINATED_BY_FAIR_FANOUT"
    ]

    report["summary"] = {
        "target_found_in_html": bool(report["target_found_in_html"]),
        "target_html_occurrences": len(report["target_found_in_html"]),
        "target_passed_to_add_fair": addfair_target_calls > 0,
        "target_eliminated_by_fair_fanout": bool(eliminated),
        "target_added_to_queue": any(x.get("queued") for x in report["queue_admission"]),
        "target_processed": any(x.get("processed") for x in report["processed"]),
        "target_out_of_budget": any(x.get("conclusion") == "QUEUED_BUT_NOT_PROCESSED_WITHIN_BUDGET" for x in report["processed"]),
        "add_fair_calls": addfair_calls,
        "add_fair_target_calls": addfair_target_calls,
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
            "diagnostic": "deloox-real-crawler-branch-trace-read-only-v1",
            "ok": False,
            "read_only": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
