from __future__ import annotations

import importlib
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import Any, Dict, List

import main as scent_main

STORES = list(scent_main.STORES)


def _text(v: Any) -> str:
    return str(v or "").strip()


def _name(p: Dict[str, Any]) -> str:
    return _text(scent_main.product_field(p, "name", "title", "product_name"))


def _brand(p: Dict[str, Any]) -> str:
    return _text(scent_main.product_field(p, "brand", "source_brand"))


def _identity(p: Dict[str, Any]):
    try:
        return list(scent_main.product_identity_key(p))
    except Exception as exc:
        return ["identity_error", type(exc).__name__, str(exc)]


def _compact(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "store": _text(p.get("store")),
        "name": _name(p),
        "brand": _brand(p),
        "url": _text(p.get("url")),
        "price": _text(p.get("price")),
        "size_ml": scent_main.product_size_ml(p),
        "concentration": _text(scent_main.product_concentration(p)),
        "store_product_id": _text(scent_main.identity_value(p, "store_product_id", "product_id", "catalog_id")),
        "store_variant_id": _text(scent_main.identity_value(p, "store_variant_id", "variant_id")),
        "gtin": _text(scent_main.identity_value(p, "gtin", "ean", "ean13", "barcode", "upc")),
        "sku": _text(scent_main.identity_value(p, "sku")),
    }


def _catalog(p: Dict[str, Any], q: str) -> Dict[str, Any]:
    try:
        result = scent_main.catalog_match(dict(p), q)
    except Exception as exc:
        return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    if result is None:
        return {"status": "NOT_APPLICABLE"}
    if isinstance(result, dict) and result.get("_reject"):
        return {"status": "REJECT", "accepted": False}
    if isinstance(result, dict):
        return {
            "status": "ACCEPT",
            "accepted": True,
            "name_before": _name(p),
            "name_after": _name(result),
            "canonical_name": _text(result.get("canonical_name")),
            "catalog_variant": _text(result.get("catalog_variant")),
            "family_id": _text(result.get("_catalog_family_id") or result.get("family_id")),
            "catalog_canonical_name": _text(result.get("_catalog_canonical_name") or result.get("canonical_name")),
        }
    return {"status": "UNKNOWN", "result_type": type(result).__name__}


def _match(p: Dict[str, Any], q: str) -> Dict[str, Any]:
    before = dict(p)
    work = dict(p)
    try:
        accepted = bool(scent_main.matches(work, q))
    except Exception as exc:
        return {"accepted": False, "error": f"{type(exc).__name__}: {exc}", "name_before": _name(before), "name_after": _name(work), "mutated": work != before}
    return {
        "accepted": accepted,
        "name_before": _name(before),
        "name_after": _name(work),
        "mutated": work != before,
        "identity_before": _identity(before),
        "identity_after": _identity(work),
    }


def _discover(store: str, q: str) -> Dict[str, Any]:
    started = time.perf_counter()
    out = {"store": store, "status": "ok", "raw": [], "local": [], "local_duplicates": [], "errors": [], "attempts": []}
    try:
        module = importlib.import_module(f"scrapers.{store}.scraper")
        fn = getattr(module, "search", None) or getattr(module, "scrape", None)
        if not callable(fn):
            raise RuntimeError(f"{store}: scraper senza search()/scrape()")
        attempts = scent_main.build_search_attempts(store, scent_main.norm(q))
        seen = set()
        index = 0
        for attempt in attempts:
            t0 = time.perf_counter()
            try:
                results = fn(attempt) or []
                if not isinstance(results, list):
                    results = []
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    p = dict(item)
                    p.setdefault("store", store)
                    p = scent_main.resolve_actual_price(p)
                    index += 1
                    key = tuple(_identity(p))
                    row = {"raw_index": index, "attempt": attempt, "candidate": _compact(p), "identity_key": list(key), "_product": p}
                    out["raw"].append(row)
                    if key in seen:
                        out["local_duplicates"].append(row)
                    else:
                        seen.add(key)
                        out["local"].append(row)
                out["attempts"].append({"query": attempt, "raw_count": len(results), "duration_ms": round((time.perf_counter()-t0)*1000,2)})
            except Exception as exc:
                out["errors"].append({"stage":"scraper_search","attempt":attempt,"error":f"{type(exc).__name__}: {exc}","traceback":traceback.format_exc()})
    except Exception as exc:
        out["status"] = "error"
        out["errors"].append({"stage":"load_scraper","error":f"{type(exc).__name__}: {exc}","traceback":traceback.format_exc()})
    out["raw_count"] = len(out["raw"])
    out["local_count"] = len(out["local"])
    out["local_duplicates_count"] = len(out["local_duplicates"])
    out["duration_ms"] = round((time.perf_counter()-started)*1000,2)
    return out


def diagnostic(q: str, timeout: float = 60.0) -> Dict[str, Any]:
    q = str(q or "").strip()
    if not q:
        return {"ok": False, "error": "Parametro q mancante"}
    started = time.perf_counter()
    timeout = max(5.0, min(float(timeout), 120.0))
    reports: Dict[str, Dict[str, Any]] = {}
    local: List[Dict[str, Any]] = []
    executor = ThreadPoolExecutor(max_workers=len(STORES), thread_name_prefix="scent_candidate_diag")
    futures = {executor.submit(_discover, store, q): store for store in STORES}
    try:
        try:
            iterator = as_completed(futures, timeout=timeout)
            for future in iterator:
                store = futures[future]
                try:
                    report = future.result()
                except Exception as exc:
                    report = {"store":store,"status":"error","raw":[],"local":[],"local_duplicates":[],"errors":[{"stage":"future","error":f"{type(exc).__name__}: {exc}"}]}
                reports[store] = report
                local.extend(report.get("local", []))
        except TimeoutError:
            for future, store in futures.items():
                if store in reports:
                    continue
                if future.done():
                    try: report = future.result()
                    except Exception as exc: report = {"store":store,"status":"error","raw":[],"local":[],"local_duplicates":[],"errors":[{"stage":"future","error":f"{type(exc).__name__}: {exc}"}]}
                    reports[store] = report
                    local.extend(report.get("local", []))
                else:
                    reports[store] = {"store":store,"status":"timeout","raw":[],"local":[],"local_duplicates":[],"errors":[{"stage":"timeout","error":f"Store non terminato entro {timeout:.1f}s"}]}
    finally:
        for future in futures:
            if not future.done(): future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    global_seen = {}
    accepted = []
    trace = []
    for seq, entry in enumerate(local, 1):
        p = dict(entry["_product"])
        key = tuple(_identity(p))
        duplicate_of = global_seen.get(key)
        global_dup = duplicate_of is not None
        cat = _catalog(p, q)
        if global_dup:
            match = {"accepted": False, "skipped": True, "reason":"global_dedup_before_match", "name_before":_name(p), "name_after":_name(p), "mutated":False, "identity_before":list(key), "identity_after":list(key)}
        else:
            match = _match(p, q)
        row = {
            "sequence": seq,
            "store": _text(p.get("store")),
            "product": _compact(p),
            "raw_name": _name(p),
            "url": _text(p.get("url")),
            "identity_key_before": list(key),
            "local_dedup":"KEPT",
            "global_dedup":"DUPLICATE" if global_dup else "KEPT",
            "global_duplicate_of_sequence": duplicate_of,
            "catalog": cat,
            "matches": match,
            "identity_key_after_match": None,
            "final_dedup": None,
            "final": False,
            "reason": None,
            "_accepted_product": None,
        }
        if global_dup:
            row["reason"] = "GLOBAL_DEDUP"
        elif match.get("error"):
            row["reason"] = "MATCH_ERROR"
        elif not match.get("accepted"):
            row["reason"] = "CATALOG_REJECT" if cat.get("status") == "REJECT" else "MATCH_REJECT"
        else:
            accepted_product = dict(p)
            scent_main.matches(accepted_product, q)
            row["_accepted_product"] = accepted_product
            accepted.append(row)
        if not global_dup:
            global_seen[key] = seq
        trace.append(row)

    final_seen = {}
    final_results = []
    for row in accepted:
        p = row["_accepted_product"]
        final_key = tuple(_identity(p))
        row["identity_key_after_match"] = list(final_key)
        duplicate_of = final_seen.get(final_key)
        if duplicate_of is not None:
            row["final_dedup"] = "DUPLICATE"
            row["final_duplicate_of_sequence"] = duplicate_of
            row["reason"] = "FINAL_DEDUP"
        else:
            final_seen[final_key] = row["sequence"]
            row["final_dedup"] = "KEPT"
            row["final"] = True
            row["reason"] = "KEPT_FINAL"
            row["final_product"] = _compact(p)
            final_results.append(p)

    for store, report in reports.items():
        for dup in report.get("local_duplicates", []):
            p = dup["candidate"]
            trace.append({"sequence":None,"store":store,"product":p,"raw_name":p.get("name",""),"url":p.get("url",""),"identity_key_before":dup.get("identity_key"),"local_dedup":"DUPLICATE","global_dedup":"NOT_REACHED","global_duplicate_of_sequence":None,"catalog":None,"matches":None,"identity_key_after_match":None,"final_dedup":"NOT_REACHED","final":False,"reason":"LOCAL_DEDUP"})

    trace.sort(key=lambda r:(r["store"], r["sequence"] is None, r["sequence"] if r["sequence"] is not None else 10**9))
    reason_counts = {}
    for row in trace:
        reason_counts[row["reason"]] = reason_counts.get(row["reason"], 0) + 1
    final_results.sort(key=scent_main.deterministic_result_key)

    counts = {
        "raw_candidates": sum(r.get("raw_count",0) for r in reports.values()),
        "local_unique_candidates": sum(r.get("local_count",0) for r in reports.values()),
        "local_duplicates": sum(r.get("local_duplicates_count",0) for r in reports.values()),
        "global_unique_candidates": sum(1 for r in trace if r.get("global_dedup") == "KEPT"),
        "matches_accepted": sum(1 for r in trace if isinstance(r.get("matches"),dict) and r["matches"].get("accepted") is True),
        "final_dedup_duplicates": sum(1 for r in trace if r.get("final_dedup") == "DUPLICATE"),
        "final_results": len(final_results),
    }
    return {
        "ok": True,
        "diagnostic": "candidate_level_pipeline",
        "query": q,
        "stores": STORES,
        "counts": counts,
        "reason_counts": reason_counts,
        "stores_detail": {s:{"status":r.get("status"),"raw_count":r.get("raw_count",0),"local_count":r.get("local_count",0),"local_duplicates":r.get("local_duplicates_count",0),"duration_ms":r.get("duration_ms"),"errors":r.get("errors",[])} for s,r in reports.items()},
        "candidates":[{k:v for k,v in row.items() if not k.startswith("_")} for row in trace],
        "final_results":[_compact(p) for p in final_results],
        "duration_ms": round((time.perf_counter()-started)*1000,2),
    }


@scent_main.app.get("/diagnostic-search-candidates")
def diagnostic_search_candidates(q: str = "Hawas", timeout: float = 60.0):
    return diagnostic(q, timeout)
