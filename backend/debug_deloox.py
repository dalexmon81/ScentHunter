"""ScentHunter - lightweight read-only Deloox crawler branch diagnostic."""
from __future__ import annotations

import sys
import time
import traceback
from fastapi import APIRouter, Query

router = APIRouter()

TARGET_FUNCTIONS = {
    "_discover_deloox_catalog",
    "process_page",
    "add_fair",
    "add",
    "_html_listing_url",
}


def _norm(value):
    return str(value or "").split("#", 1)[0]


def _contains(value, target):
    return str(target or "").strip().lower() in str(value or "").lower()


def _run_trace(target="Rasasi", max_pages=150, max_depth=8):
    import catalog_engine as ce

    target = str(target or "Rasasi").strip() or "Rasasi"
    max_pages = max(1, min(int(max_pages), 150))
    max_depth = max(0, min(int(max_depth), 10))

    seeds = list(dict.fromkeys(ce.HTML_DISCOVERY_SEEDS.get("deloox", ())))
    report = {
        "diagnostic": "deloox-real-crawler-branch-read-only-v3",
        "ok": True,
        "read_only": True,
        "store": "Deloox",
        "target": target,
        "parameters": {"max_pages": max_pages, "max_depth": max_depth},
        "crawler": "_discover_deloox_catalog",
        "catalog_engine_module": getattr(ce, "__file__", None),
        "target_found_in_html": [],
        "listing_url_calls": [],
        "add_fair": [],
        "queue_admission": [],
        "processed": [],
        "summary": {},
    }

    seen_events = set()

    def add(bucket, item):
        key = repr(item)
        if key not in seen_events:
            seen_events.add(key)
            report[bucket].append(item)

    def profiler(frame, event, arg):
        name = frame.f_code.co_name
        if name not in TARGET_FUNCTIONS:
            return profiler

        loc = frame.f_locals

        # 1 + 7: actual process_page entry. This is the definitive proof
        # that a target URL itself was fetched/processed by the real crawler.
        if name == "process_page" and event == "call":
            requested = _norm(loc.get("requested"))
            if _contains(requested, target):
                add("processed", {
                    "url": requested,
                    "depth": loc.get("depth"),
                    "source": loc.get("source"),
                    "stage": "process_page_call",
                    "processed": True,
                })

        # 1/2/3: every real call to _html_listing_url whose raw URL or
        # resulting listing contains the target. This is the exact function
        # used by add_fair's input construction and by add().
        if name == "_html_listing_url":
            raw = _norm(loc.get("raw_url"))
            base = _norm(loc.get("base_url"))
            if event == "call" and (_contains(raw, target) or _contains(base, target)):
                add("listing_url_calls", {
                    "stage": "call",
                    "raw_url": raw,
                    "base_url": base,
                    "label": loc.get("label"),
                    "target_in_raw_url": _contains(raw, target),
                })
            elif event == "return" and (_contains(raw, target) or _contains(arg, target)):
                add("listing_url_calls", {
                    "stage": "return",
                    "raw_url": raw,
                    "result": _norm(arg),
                    "result_contains_target": _contains(arg, target),
                })

        # 4/5: the REAL add_fair receives the real listing list. On return,
        # 'unique' is the actual post-FAIR_FANOUT list.
        if name == "add_fair" and event == "call":
            listings = loc.get("listings")
            if isinstance(listings, list):
                hits = [
                    {"position": i, "url": _norm(v)}
                    for i, v in enumerate(listings)
                    if _contains(v, target)
                ]
                if hits:
                    add("add_fair", {
                        "stage": "input",
                        "input_count": len(listings),
                        "target_positions": hits,
                        "fair_fanout": 640,
                        "depth": loc.get("depth"),
                        "source": loc.get("source"),
                    })

        if name == "add_fair" and event == "return":
            listings = loc.get("listings")
            unique = loc.get("unique")
            if isinstance(listings, list):
                hits_in = [
                    {"position": i, "url": _norm(v)}
                    for i, v in enumerate(listings)
                    if _contains(v, target)
                ]
                if hits_in:
                    hits_out = [
                        {"position": i, "url": _norm(v)}
                        for i, v in enumerate(unique or [])
                        if _contains(v, target)
                    ]
                    add("add_fair", {
                        "stage": "return_after_sampling",
                        "input_count": len(listings),
                        "target_positions": hits_in,
                        "target_survived_fanout": bool(hits_out),
                        "selected_positions": hits_out,
                        "fair_fanout": 640,
                        "eliminated_by_fair_fanout": len(listings) > 640 and not hits_out,
                    })

        # 6: add() return tells us whether the real URL entered the real queue.
        if name == "add" and event == "return":
            url = _norm(loc.get("url"))
            if _contains(url, target):
                queued = loc.get("queued")
                visited = loc.get("visited")
                add("queue_admission", {
                    "url": url,
                    "depth": loc.get("depth"),
                    "source": loc.get("source"),
                    "queued": url in queued if isinstance(queued, set) else None,
                    "already_visited": url in visited if isinstance(visited, set) else None,
                })

        return profiler

    old_profile = sys.getprofile()
    old_limit = getattr(ce, "HTML_MAX_PAGES", None)
    old_depth = getattr(ce, "HTML_MAX_DEPTH", None)
    started = time.time()

    try:
        # Diagnostic-only runtime cap. The crawler function itself is unchanged.
        ce.HTML_MAX_PAGES = max_pages
        ce.HTML_MAX_DEPTH = max_depth
        sys.setprofile(profiler)
        result = ce._discover_deloox_catalog(
            seeds,
            time.time() + 45,
        )
    finally:
        sys.setprofile(old_profile)
        if old_limit is not None:
            ce.HTML_MAX_PAGES = old_limit
        if old_depth is not None:
            ce.HTML_MAX_DEPTH = old_depth

    queued_urls = {
        x["url"] for x in report["queue_admission"] if x.get("queued")
    }
    processed_urls = {
        x["url"] for x in report["processed"] if x.get("processed")
    }
    fanout_eliminated = any(
        x.get("eliminated_by_fair_fanout")
        for x in report["add_fair"]
    )

    report["summary"] = {
        "target_found_in_html": bool(report["listing_url_calls"]),
        "target_passed_to_add_fair": any(
            x.get("stage") == "input" for x in report["add_fair"]
        ),
        "target_eliminated_by_fair_fanout": fanout_eliminated,
        "target_added_to_queue": bool(queued_urls),
        "target_processed": bool(processed_urls),
        "target_out_of_budget": bool(queued_urls - processed_urls),
        "queue_target_urls": sorted(queued_urls),
        "processed_target_urls": sorted(processed_urls),
        "crawler_return": {
            "visited": result.get("visited"),
            "successes": result.get("successes"),
            "product_count": len(result.get("product_urls") or {}),
            "error_count": len(result.get("errors") or []),
        },
        "elapsed_sec": round(time.time() - started, 3),
    }
    return report


@router.get("/diagnose-deloox-real-branch")
def diagnose_deloox_real_branch(
    target: str = Query("Rasasi", min_length=2),
    max_pages: int = Query(150, ge=1, le=150),
    max_depth: int = Query(8, ge=0, le=10),
):
    try:
        return _run_trace(target=target, max_pages=max_pages, max_depth=max_depth)
    except Exception as exc:
        return {
            "diagnostic": "deloox-real-crawler-branch-read-only-v3",
            "ok": False,
            "read_only": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
