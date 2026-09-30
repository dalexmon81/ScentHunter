"""ScentHunter - read-only single-page Deloox branch diagnostic.

This diagnostic intentionally does NOT run the Deloox catalog crawler.
It fetches one catalog page, applies the same listing classification and
current _fair_catalog_links ordering used by _discover_deloox_catalog(), and
reports exactly where a target branch lands in the admission order.
"""
from __future__ import annotations

import time
import traceback
import urllib.parse

from fastapi import APIRouter, Query

router = APIRouter()

DEFAULT_URL = "https://www.deloox.com/en/category/1063858/brands.html"


def _norm(value):
    return str(value or "").split("#", 1)[0]


def _contains(value, target):
    return str(target or "").strip().lower() in str(value or "").lower()


def _same_fair_catalog_links(items):
    """Exact structural ordering used by catalog_engine._discover_deloox_catalog."""
    buckets = {}
    for item in items:
        url = item[0]
        parsed = urllib.parse.urlparse(url)
        parts = [x for x in (parsed.path or '').split('/') if x]
        key = (parts[-1] if parts else parsed.netloc).lower()
        bucket = key[0] if key and key[0].isalnum() else '#'
        buckets.setdefault(bucket, []).append(item)

    ordered = []
    for key in sorted(buckets):
        buckets[key].sort(key=lambda x: x[0])

    while buckets:
        for key in list(sorted(buckets)):
            values = buckets.get(key)
            if not values:
                buckets.pop(key, None)
                continue
            ordered.append(values.pop(0))
            if not values:
                buckets.pop(key, None)
    return ordered


def _run_single_page(target="Rasasi", url=DEFAULT_URL):
    import catalog_engine as ce

    target = str(target or "Rasasi").strip() or "Rasasi"
    url = str(url or DEFAULT_URL).strip() or DEFAULT_URL
    started = time.time()

    report = {
        "diagnostic": "deloox-single-page-branch-read-only-v1",
        "ok": True,
        "read_only": True,
        "store": "Deloox",
        "target": target,
        "url": url,
        "method": "one HTTP fetch + real catalog URL classifiers + exact current _fair_catalog_links ordering",
        "crawler_executed": False,
        "catalog_engine_module": getattr(ce, "__file__", None),
        "http": {},
        "anchors": {
            "total": 0,
            "listing_candidates": 0,
            "target_raw_hits": [],
            "target_listing_hits": [],
        },
        "fair_order": {},
        "queue_admission": {},
        "summary": {},
    }

    requested, final, data, error = ce._fetch_html_page("deloox", url)
    report["http"] = {
        "requested": requested,
        "final": final,
        "bytes": len(data or b""),
        "error": error,
        "elapsed_sec": round(time.time() - started, 3),
    }
    if error:
        report["ok"] = False
        report["summary"] = {"diagnosis": "HTTP_FETCH_FAILED"}
        return report

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(data, "html.parser")
    base = final or requested or url
    listings = []
    raw_target_hits = []
    listing_target_hits = []
    product_target_hits = []

    for index, a in enumerate(soup.find_all("a", href=True)):
        raw = a.get("href")
        label = a.get_text(" ", strip=True)
        report["anchors"]["total"] += 1
        if _contains(raw, target) or _contains(label, target):
            raw_target_hits.append({
                "anchor_position": index,
                "href": _norm(raw),
                "label": label[:300],
            })

        product = ce._html_product_url("deloox", raw, base)
        if product:
            if _contains(product, target) or _contains(label, target):
                product_target_hits.append({
                    "anchor_position": index,
                    "product_url": product,
                    "label": label[:300],
                })
            continue

        listing = ce._html_listing_url("deloox", raw, base, label)
        if not listing:
            continue
        report["anchors"]["listing_candidates"] += 1
        item = (listing, 1, requested or url)
        listings.append(item)
        if _contains(listing, target) or _contains(label, target):
            listing_target_hits.append({
                "pre_fair_position": len(listings) - 1,
                "url": listing,
                "label": label[:300],
            })

    report["anchors"]["target_raw_hits"] = raw_target_hits[:100]
    report["anchors"]["target_listing_hits"] = listing_target_hits[:100]
    report["anchors"]["target_product_hits"] = product_target_hits[:100]

    ordered = _same_fair_catalog_links(listings)
    ordered_target = []
    for position, item in enumerate(ordered):
        listing = item[0]
        if _contains(listing, target):
            parsed = urllib.parse.urlparse(listing)
            parts = [x for x in (parsed.path or '').split('/') if x]
            final_part = (parts[-1] if parts else parsed.netloc).lower()
            bucket = final_part[0] if final_part and final_part[0].isalnum() else '#'
            ordered_target.append({
                "fair_order_position": position,
                "url": listing,
                "bucket": bucket,
            })

    queue_cap = min(800, int(getattr(ce, "HTML_MAX_PAGES", 800))) * 8
    admitted = ordered[:queue_cap]
    admitted_target = [
        {"queue_position": i, "url": item[0], "depth": item[1]}
        for i, item in enumerate(admitted)
        if _contains(item[0], target)
    ]

    report["fair_order"] = {
        "input_count": len(listings),
        "output_count": len(ordered),
        "target": ordered_target[:100],
        "target_in_output": bool(ordered_target),
    }
    report["queue_admission"] = {
        "queue_cap": queue_cap,
        "admitted_count": len(admitted),
        "target_admitted": bool(admitted_target),
        "target": admitted_target[:100],
    }

    report["summary"] = {
        "target_found_in_page": bool(raw_target_hits or listing_target_hits or product_target_hits),
        "target_as_product_url": bool(product_target_hits),
        "target_as_listing_url": bool(listing_target_hits),
        "target_survived_current_fair_order": bool(ordered_target),
        "target_reaches_current_queue_cap": bool(admitted_target),
        "diagnosis": (
            "TARGET_REACHES_QUEUE_ADMISSION"
            if admitted_target
            else "TARGET_NOT_REACHED_BY_CURRENT_PAGE_ADMISSION"
        ),
        "elapsed_sec": round(time.time() - started, 3),
    }
    return report


@router.get("/diagnose-deloox-single-page-branch")
def diagnose_deloox_single_page_branch(
    target: str = Query("Rasasi", min_length=2),
    url: str = Query(DEFAULT_URL, min_length=10),
):
    try:
        return _run_single_page(target=target, url=url)
    except Exception as exc:
        return {
            "diagnostic": "deloox-single-page-branch-read-only-v1",
            "ok": False,
            "read_only": True,
            "crawler_executed": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
