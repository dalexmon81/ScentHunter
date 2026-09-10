"""ScentHunter search orchestration v6.

All eight stores are launched concurrently. Results are published progressively
as each store settles; no store is allowed to block another store.
"""
from __future__ import annotations

import concurrent.futures
import re
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_STORE_TIMEOUT = 18.0
DEFAULT_GLOBAL_TIMEOUT = 30.0
MAX_CONCURRENT_STORES = 8

STORE_PRIORITY = (
    "bplatz",
    "deloox",
    "parfumcity",
    "parfumzentrum",
    "perfumemarket",
    "sabina",
    "orioudh",
    "notino",
)


@dataclass
class StoreRun:
    store: str
    status: str = "error"
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    elapsed: float = 0.0
    error: Optional[str] = None


class SearchEngine:
    def __init__(
        self,
        legacy_module: Any,
        *,
        store_timeout: float = DEFAULT_STORE_TIMEOUT,
        global_timeout: float = DEFAULT_GLOBAL_TIMEOUT,
        max_concurrent_stores: Optional[int] = None,
    ) -> None:
        self.legacy = legacy_module
        self.store_timeout = float(store_timeout)
        self.global_timeout = float(global_timeout)
        configured = list(getattr(legacy_module, "STORES", None) or STORE_PRIORITY)
        configured_set = set(configured)
        self.stores = [s for s in STORE_PRIORITY if s in configured_set]
        self.stores += [s for s in configured if s not in self.stores]
        # The production engine is intentionally always eight-way.
        # main.py from older deployments still passes max_concurrent_stores=4;
        # that legacy value must not reintroduce the old 4+4 barrier.
        self.max_concurrent_stores = min(MAX_CONCURRENT_STORES, len(self.stores) or 1)

    def analyze_query(self, query: str) -> Dict[str, Any]:
        raw = str(query or "").strip()
        norm = self.legacy.norm(raw) if hasattr(self.legacy, "norm") else raw.lower()
        size_ml = None
        match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", raw, re.I)
        if match:
            size_ml = float(match.group(1).replace(",", "."))
            if match.group(2).lower() == "cl":
                size_ml *= 10.0
        return {"raw": raw, "normalized": norm, "size_ml": size_ml}

    @staticmethod
    def _identity_value(item: Dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = item.get(key)
            if isinstance(value, dict):
                value = value.get("value")
            if value not in (None, ""):
                return str(value).strip()

        identity = item.get("identity")
        if isinstance(identity, dict):
            for key in keys:
                value = identity.get(key)
                if isinstance(value, dict):
                    value = value.get("value")
                if value not in (None, ""):
                    return str(value).strip()
        return ""

    @classmethod
    def _candidate_key(cls, item: Dict[str, Any]) -> tuple:
        # The scraper contract allows a structured identity block.  Use it
        # here too, otherwise a retailer candidate can be keyed only by URL
        # while the legacy pipeline keys the same product by store/product id.
        store = str(item.get("store") or item.get("shop") or "").strip().casefold()
        product_id = cls._identity_value(
            item,
            "store_product_id",
            "product_id",
            "catalog_id",
            "sku",
        ).casefold()
        variant_id = cls._identity_value(
            item,
            "store_variant_id",
            "variant_id",
        ).casefold()
        gtin = cls._identity_value(
            item,
            "gtin",
            "ean",
            "ean13",
            "barcode",
            "upc",
        ).casefold()
        url = str(item.get("url") or item.get("source_url") or "").strip().casefold()
        size = item.get("size_ml") or item.get("volume_ml") or item.get("format_ml") or ""

        identity = variant_id or product_id or gtin
        return store, identity, url, str(size).strip().casefold()

    @staticmethod
    def _canonicalize_store_candidate(store: str, item: Dict[str, Any]) -> Dict[str, Any]:
        product = dict(item)
        raw_store = str(product.get("store") or product.get("shop") or "").strip()
        canonical_store = str(store or "").strip().casefold()

        # The eight-store engine uses stable lowercase store ids. Some
        # scrapers return the retailer display name instead (e.g.
        # "ParfumZentrum"). Keep the display value, but make the machine
        # identity deterministic so filtering/dedup/grouping cannot drop the
        # offer because of casing/name differences.
        if raw_store and raw_store.casefold() != canonical_store:
            product.setdefault("store_display_name", raw_store)
        product["store"] = canonical_store
        return product

    def _dedupe_raw(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            key = self._candidate_key(item)
            if key[1] == "" and key[2] == "":
                out.append(item)
            elif key not in seen:
                seen.add(key)
                out.append(item)
        return out

    def _run_one_store(self, store: str, query: str) -> StoreRun:
        started = time.monotonic()
        try:
            runner = getattr(self.legacy, "run_store", None)
            if not callable(runner):
                raise RuntimeError("main.run_store is not available")
            raw = runner(store, query)
            if raw is None:
                candidates = []
            elif isinstance(raw, list):
                candidates = raw
            else:
                try:
                    candidates = list(raw)
                except Exception:
                    candidates = []
            candidates = [
                self._canonicalize_store_candidate(store, x)
                for x in candidates
                if isinstance(x, dict)
            ]
            return StoreRun(
                store=store,
                status="ok" if candidates else "empty",
                candidates=candidates,
                elapsed=time.monotonic() - started,
            )
        except Exception as exc:
            return StoreRun(
                store=store,
                status="error",
                elapsed=time.monotonic() - started,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _run_stores(self, query: str) -> Dict[str, Any]:
        """Run every configured store at once and wait only for the global deadline."""
        started = time.monotonic()
        deadline = started + self.global_timeout
        results: Dict[str, StoreRun] = {s: StoreRun(store=s) for s in self.stores}
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(self.max_concurrent_stores, len(self.stores) or 1),
            thread_name_prefix="scenthunter-store",
        )
        futures: Dict[concurrent.futures.Future, tuple[str, float]] = {}
        try:
            for store in self.stores:
                submitted = time.monotonic()
                futures[executor.submit(self._run_one_store, store, query)] = (store, submitted)

            while futures:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                now = time.monotonic()
                expired = [
                    f for f, (_, submitted) in futures.items()
                    if now - submitted >= self.store_timeout
                ]
                for future in expired:
                    store, submitted = futures.pop(future)
                    results[store] = StoreRun(
                        store=store,
                        status="timeout",
                        elapsed=now - submitted,
                        error="store timeout",
                    )
                    future.cancel()

                if not futures:
                    break
                done, _ = concurrent.futures.wait(
                    list(futures),
                    timeout=min(0.10, remaining),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in list(done):
                    if future not in futures:
                        continue
                    store, submitted = futures.pop(future)
                    try:
                        results[store] = future.result()
                    except Exception as exc:
                        results[store] = StoreRun(
                            store=store,
                            status="error",
                            elapsed=time.monotonic() - submitted,
                            error=f"{type(exc).__name__}: {exc}",
                        )

            now = time.monotonic()
            for future, (store, submitted) in list(futures.items()):
                results[store] = StoreRun(
                    store=store,
                    status="timeout",
                    elapsed=max(0.0, now - submitted),
                    error="global search window expired",
                )
                future.cancel()
                futures.pop(future, None)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return {"stores": results, "elapsed": time.monotonic() - started}

    @staticmethod
    def _availability_rank(item: Dict[str, Any]) -> int:
        value = str(item.get("availability") or item.get("stock_status") or item.get("stock") or "").strip().lower()
        if value in {"in_stock", "available", "true", "1", "yes", "in stock"}:
            return 0
        if value in {"out_of_stock", "oos", "unavailable", "sold_out", "sold out", "false", "0"}:
            return 2
        available = item.get("available")
        if isinstance(available, bool):
            return 0 if available else 2
        return 1

    @staticmethod
    def _price_value(item: Dict[str, Any]) -> float:
        try:
            value = item.get("price", item.get("price_num"))
            return float(value)
        except Exception:
            return float("inf")

    def _stable_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def key(item: Dict[str, Any]) -> tuple:
            return (
                self._availability_rank(item),
                self._price_value(item),
                str(item.get("store") or item.get("shop") or ""),
                str(item.get("url") or ""),
            )

        output = []
        for result in results:
            item = dict(result)
            offers = item.get("offers")
            if isinstance(offers, list) and offers:
                clean = [dict(x) for x in offers if isinstance(x, dict)]
                for offer in clean:
                    if not offer.get("availability") and isinstance(offer.get("available"), bool):
                        offer["availability"] = "in_stock" if offer["available"] else "out_of_stock"
                clean.sort(key=key)
                item["offers"] = clean
                item["offer_count"] = len(clean)
                item["stores"] = list(dict.fromkeys(
                    str(x.get("store") or x.get("shop") or "").strip()
                    for x in clean if str(x.get("store") or x.get("shop") or "").strip()
                ))
                best = clean[0]
                for field in ("store", "price", "url", "image", "availability", "available", "size_ml", "concentration", "gender"):
                    if field in best:
                        item[field] = best[field]
            output.append(item)
        output.sort(key=lambda x: key(x.get("offers", [x])[0] if isinstance(x.get("offers"), list) and x.get("offers") else x))
        return output

    def _validate_candidates_only(self, query: Any, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        validate = getattr(self.legacy, "_validate_candidates_parallel", None)
        if not callable(validate):
            return [x for x in candidates if isinstance(x, dict)]
        try:
            result = validate(candidates, query)
        except TypeError:
            result = validate(candidates)
        if result is None:
            return []
        if not isinstance(result, list):
            result = list(result)
        return [x for x in result if isinstance(x, dict)]

    def _orchestrate(self, query: str, raw_pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        orchestrate = getattr(self.legacy, "_orchestrate_results", None)
        if callable(orchestrate):
            try:
                result = orchestrate(raw_pool, query)
            except TypeError:
                result = orchestrate(raw_pool)
        else:
            validated = self._validate_candidates_only(query, raw_pool)
            prepare = getattr(self.legacy, "_prepare_final_results", None)
            if callable(prepare):
                try:
                    result = prepare(validated, query)
                except TypeError:
                    result = prepare(validated)
            else:
                result = validated
        if result is None:
            return []
        if not isinstance(result, list):
            result = list(result)
        return self._stable_results([x for x in result if isinstance(x, dict)])

    def _finalize(self, query: str, raw_pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self._orchestrate(query, raw_pool)

    @staticmethod
    def _result_identity(item: Dict[str, Any]) -> tuple:
        brand = str(item.get("brand") or "").strip().casefold()
        name = str(item.get("name") or item.get("title") or "").strip().casefold()
        size = str(item.get("size_ml") or item.get("size") or "").strip().casefold()
        return brand, name, size

    def search(self, query: str) -> Dict[str, Any]:
        text = self.analyze_query(query)["raw"]
        if not text:
            return {"query": "", "count": 0, "results": [], "comparisons": [], "errors": {}}
        store_run = self._run_stores(text)
        raw_pool: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}
        for store in self.stores:
            result = store_run["stores"][store]
            raw_pool.extend(result.candidates)
            if result.error:
                errors[store] = result.error
        final = self._finalize(text, self._dedupe_raw(raw_pool))
        return {"query": text, "count": len(final), "results": final, "comparisons": [], "errors": errors}

    def _job_update(self, jobs: Dict[str, Any], lock: Any, job_id: str, payload: Dict[str, Any]) -> None:
        if lock is not None:
            with lock:
                job = jobs.get(job_id)
                if job is not None:
                    job.update(payload)
        else:
            job = jobs.get(job_id)
            if job is not None:
                job.update(payload)

    def search_job_snapshot(self, job_id: str) -> Dict[str, Any]:
        jobs = getattr(self.legacy, "SEARCH_JOBS", None)
        lock = getattr(self.legacy, "SEARCH_JOBS_LOCK", None)
        if jobs is None:
            raise RuntimeError("SEARCH_JOBS is not available")
        if lock is not None:
            with lock:
                job = jobs.get(str(job_id or "").strip())
                if job is None:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=404, detail="Job di ricerca non trovato")
                snapshot = dict(job)
        else:
            snapshot = dict(jobs.get(str(job_id or "").strip()) or {})
            if not snapshot:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Job di ricerca non trovato")

        results = snapshot.get("results") if isinstance(snapshot.get("results"), list) else []
        batch_results = snapshot.get("batch_results") if isinstance(snapshot.get("batch_results"), list) else []
        store_status = snapshot.get("store_status") if isinstance(snapshot.get("store_status"), dict) else {}
        completed_stores = sum(
            1 for info in store_status.values()
            if isinstance(info, dict) and info.get("status") not in ("pending", "searching")
        )
        completed = bool(snapshot.get("completed"))
        return {
            "job_id": str(job_id),
            "query": str(snapshot.get("query") or ""),
            "count": len(results),
            "results": list(results),
            "batch_results": list(batch_results),
            "batch_id": int(snapshot.get("batch_id") or 0),
            "wave": int(snapshot.get("wave") or 0),
            "comparisons": list(snapshot.get("comparisons") or []),
            "errors": dict(snapshot.get("errors") or {}),
            "store_status": dict(store_status),
            "completed_stores": completed_stores,
            "total_stores": len(self.stores),
            "partial_result_count": len(results),
            "phase": snapshot.get("phase", "discovery"),
            "completed": completed,
            "status": "completed" if completed else "searching",
            "elapsed": snapshot.get("elapsed", 0),
            "diagnostic": snapshot.get("diagnostic", {}),
        }

    def run_job(self, job_id: str, query: str) -> None:
        """Run all stores concurrently, collect first, finalize once.

        IMPORTANT: result finalization is deliberately kept OUTSIDE the store
        collection loop.  Validation/grouping can take seconds and must never
        consume the global scraper deadline or prevent a store that already
        returned from being added to the candidate pool.
        """
        jobs = getattr(self.legacy, "SEARCH_JOBS", None)
        lock = getattr(self.legacy, "SEARCH_JOBS_LOCK", None)
        if jobs is None:
            raise RuntimeError("SEARCH_JOBS is not available")

        started = time.monotonic()
        collection_deadline = started + self.global_timeout
        store_status: Dict[str, Any] = {
            s: {"status": "pending", "count": 0} for s in self.stores
        }
        errors: Dict[str, str] = {}
        raw_pool: List[Dict[str, Any]] = []
        raw_lock = threading.Lock()

        self._job_update(jobs, lock, job_id, {
            "status": "searching",
            "phase": "all_stores_searching",
            "completed": False,
            "results": [],
            "batch_results": [],
            "batch_id": 0,
            "wave": 0,
            "comparisons": [],
            "errors": {},
            "store_status": dict(store_status),
            "completed_stores": 0,
            "total_stores": len(self.stores),
            "raw_candidate_count": 0,
            "results_are_final": False,
            "elapsed": 0.0,
        })

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(self.max_concurrent_stores, len(self.stores) or 1),
            thread_name_prefix="scenthunter-store",
        )
        futures: Dict[concurrent.futures.Future, tuple[str, float]] = {}

        try:
            # Start EVERY store immediately.
            for store in self.stores:
                submitted = time.monotonic()
                futures[executor.submit(self._run_one_store, store, query)] = (
                    store, submitted
                )
                store_status[store] = {
                    "status": "searching",
                    "count": 0,
                }

            self._job_update(jobs, lock, job_id, {
                "phase": "all_stores_searching",
                "store_status": dict(store_status),
                "total_stores": len(self.stores),
                "elapsed": round(time.monotonic() - started, 3),
            })

            # COLLECTION ONLY.  No _finalize() is allowed in this loop.
            while futures:
                now = time.monotonic()
                remaining = collection_deadline - now
                if remaining <= 0:
                    break

                expired = [
                    f for f, (_, submitted) in futures.items()
                    if now - submitted >= self.store_timeout
                ]
                for future in expired:
                    store, submitted = futures.pop(future)
                    store_status[store] = {
                        "status": "timeout",
                        "count": 0,
                        "elapsed": round(now - submitted, 3),
                        "error": "store timeout",
                    }
                    errors[store] = "store timeout"
                    future.cancel()

                if not futures:
                    break

                done, _ = concurrent.futures.wait(
                    list(futures),
                    timeout=min(0.10, remaining),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                for future in list(done):
                    if future not in futures:
                        continue

                    store, submitted = futures.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = StoreRun(
                            store=store,
                            status="error",
                            elapsed=time.monotonic() - submitted,
                            error=f"{type(exc).__name__}: {exc}",
                        )

                    candidates = [
                        x for x in result.candidates
                        if isinstance(x, dict)
                    ]

                    with raw_lock:
                        raw_pool.extend(candidates)
                        raw_pool[:] = self._dedupe_raw(raw_pool)
                        raw_count = len(raw_pool)

                    store_status[store] = {
                        "status": result.status,
                        "count": len(candidates),
                        "elapsed": round(result.elapsed, 3),
                    }
                    if result.error:
                        store_status[store]["error"] = result.error
                        errors[store] = result.error

                    # Lightweight progress update only.  This does NOT run
                    # validation/grouping/finalization.
                    completed_stores = sum(
                        1 for info in store_status.values()
                        if info.get("status") not in ("pending", "searching")
                    )
                    self._job_update(jobs, lock, job_id, {
                        "status": "searching",
                        "phase": "collecting_results",
                        "completed": False,
                        "results": [],
                        "batch_results": [],
                        "batch_id": 0,
                        "wave": 0,
                        "comparisons": [],
                        "errors": dict(errors),
                        "store_status": dict(store_status),
                        "completed_stores": completed_stores,
                        "total_stores": len(self.stores),
                        "raw_candidate_count": raw_count,
                        "results_are_final": False,
                        "elapsed": round(time.monotonic() - started, 3),
                    })

            # Anything still running has exceeded its allowed collection window.
            now = time.monotonic()
            for future, (store, submitted) in list(futures.items()):
                store_status[store] = {
                    "status": "timeout",
                    "count": 0,
                    "elapsed": round(max(0.0, now - submitted), 3),
                    "error": "global search window expired",
                }
                errors[store] = "global search window expired"
                future.cancel()
                futures.pop(future, None)

            # Snapshot the COMPLETE collected pool before any expensive work.
            with raw_lock:
                snapshot_raw = self._dedupe_raw(
                    [dict(x) for x in raw_pool if isinstance(x, dict)]
                )

            # Only now, after store collection is over, perform the expensive
            # central validation/grouping once.
            final_results = self._finalize(query, snapshot_raw)

            completed_stores = sum(
                1 for info in store_status.values()
                if info.get("status") not in ("pending", "searching")
            )
            elapsed = round(time.monotonic() - started, 3)

            self._job_update(jobs, lock, job_id, {
                "status": "completed",
                "phase": "completed",
                "completed": True,
                "results": [dict(x) for x in final_results],
                "batch_results": [dict(x) for x in final_results],
                "batch_id": 1,
                "wave": 1,
                "comparisons": [],
                "errors": dict(errors),
                "store_status": dict(store_status),
                "completed_stores": completed_stores,
                "total_stores": len(self.stores),
                "raw_candidate_count": len(snapshot_raw),
                "results_are_final": True,
                "elapsed": elapsed,
            })

        except Exception as exc:
            self._job_update(jobs, lock, job_id, {
                "status": "error",
                "phase": "completed",
                "completed": True,
                "results": [],
                "batch_results": [],
                "batch_id": 0,
                "wave": 0,
                "errors": dict(errors),
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
                "results_are_final": False,
                "elapsed": round(time.monotonic() - started, 3),
            })
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def diagnostic_search(self, query: str) -> Dict[str, Any]:
        """Run all stores concurrently with hard per-store and global deadlines."""
        text = self.analyze_query(query)["raw"]
        started = time.monotonic()
        deadline = started + self.global_timeout
        reports: Dict[str, Any] = {}

        def diagnose(store: str) -> Dict[str, Any]:
            t0 = time.monotonic()
            try:
                result = self._run_one_store(store, text)
                return {
                    "store": store,
                    "status": result.status,
                    "module_load_seconds": 0.0,
                    "attempt_build_seconds": 0.0,
                    "attempts": [{
                        "index": 0,
                        "query": text,
                        "search_call_seconds": round(result.elapsed, 4),
                        "search_call_status": result.status,
                        "returned_count": len(result.candidates),
                        "error": result.error,
                    }],
                    "candidate_count": len(result.candidates),
                    "postprocess_seconds": 0.0,
                    "run_store_equivalent_seconds": round(time.monotonic() - t0, 4),
                    "error": result.error,
                    "candidates": [
                        {
                            "store": x.get("store"),
                            "name": x.get("name"),
                            "price": x.get("price"),
                            "available": x.get("available"),
                            "url": x.get("url"),
                        }
                        for x in result.candidates
                    ],
                }
            except Exception as exc:
                return {
                    "store": store,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(MAX_CONCURRENT_STORES, len(self.stores) or 1),
            thread_name_prefix="scenthunter-diagnostic",
        )
        futures = {
            executor.submit(diagnose, store): (store, time.monotonic())
            for store in self.stores
        }

        try:
            pending = set(futures)
            while pending:
                remaining_global = deadline - time.monotonic()
                if remaining_global <= 0:
                    break

                done, pending = concurrent.futures.wait(
                    pending,
                    timeout=min(0.10, remaining_global),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                for future in done:
                    store, submitted = futures[future]
                    try:
                        reports[store] = future.result()
                    except Exception as exc:
                        reports[store] = {
                            "store": store,
                            "status": "error",
                            "error": f"{type(exc).__name__}: {exc}",
                        }

                # Mark stores that exceeded their individual diagnostic deadline.
                now = time.monotonic()
                for future in list(pending):
                    store, submitted = futures[future]
                    if now - submitted >= self.store_timeout:
                        reports[store] = {
                            "store": store,
                            "status": "timeout",
                            "error": "store diagnostic timeout",
                            "elapsed": round(now - submitted, 3),
                            "attempts": [{
                                "index": 0,
                                "query": text,
                                "search_call_seconds": round(now - submitted, 4),
                                "search_call_status": "timeout",
                                "returned_count": 0,
                                "error": "store diagnostic timeout",
                            }],
                            "candidate_count": 0,
                            "candidates": [],
                        }
                        future.cancel()
                        pending.remove(future)

            # Anything still pending at the global deadline is explicitly reported;
            # never wait indefinitely for a scraper that ignores cancellation.
            now = time.monotonic()
            for future in list(pending):
                store, submitted = futures[future]
                reports[store] = {
                    "store": store,
                    "status": "timeout",
                    "error": "global diagnostic window expired",
                    "elapsed": round(max(0.0, now - submitted), 3),
                    "attempts": [{
                        "index": 0,
                        "query": text,
                        "search_call_seconds": round(max(0.0, now - submitted), 4),
                        "search_call_status": "timeout",
                        "returned_count": 0,
                        "error": "global diagnostic window expired",
                    }],
                    "candidate_count": 0,
                    "candidates": [],
                }
                future.cancel()
                pending.remove(future)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        ordered = {
            store: reports.get(
                store,
                {
                    "store": store,
                    "status": "timeout",
                    "error": "diagnostic deadline expired",
                    "candidate_count": 0,
                    "candidates": [],
                },
            )
            for store in self.stores
        }

        return {
            "ok": True,
            "diagnostic_type": "store_stage_forensics_v5",
            "query": self.analyze_query(text),
            "production_limits": {
                "store_timeout_seconds": self.store_timeout,
                "global_timeout_seconds": self.global_timeout,
                "max_concurrent_stores": self.max_concurrent_stores,
            },
            "total_diagnostic_seconds": round(time.monotonic() - started, 3),
            "stores": ordered,
            "interpretation": {
                "search_call_bottleneck": [
                    name
                    for name, info in ordered.items()
                    if any(
                        float(a.get("search_call_seconds") or 0.0) >= 5.0
                        or a.get("search_call_status") == "timeout"
                        for a in info.get("attempts", [])
                        if isinstance(a, dict)
                    )
                ],
                "stores_with_results": [
                    name
                    for name, info in ordered.items()
                    if int(info.get("candidate_count") or 0) > 0
                ],
                "stores_without_results": [
                    name
                    for name, info in ordered.items()
                    if int(info.get("candidate_count") or 0) == 0
                ],
            },
        }
