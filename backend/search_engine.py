"""ScentHunter search orchestration v2.

The live search layer is deliberately controlled:
- the eight store adapters run in two fixed waves of four;
- wave 1 preserves the historical priority order;
- only one complete search job is active at a time;
- no central query rewriting;
- no central retries (store adapters own their retry/rate-limit policy);
- raw candidates are collected losslessly;
- validation/grouping/ranking happens once, after collection;
- progress never publishes a partial final product list.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import time
import traceback
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_STORE_TIMEOUT = 15.0
DEFAULT_GLOBAL_TIMEOUT = 35.0


@dataclass
class StoreRun:
    store: str
    status: str = "error"  # ok | empty | timeout | error
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    elapsed: float = 0.0
    error: Optional[str] = None


class SearchEngine:
    def __init__(self, legacy_module: Any, *, store_timeout: float = DEFAULT_STORE_TIMEOUT,
                 global_timeout: float = DEFAULT_GLOBAL_TIMEOUT) -> None:
        self.legacy = legacy_module
        self.store_timeout = float(store_timeout)
        self.global_timeout = float(global_timeout)
        self._execution_lock = threading.Lock()
        stores = getattr(legacy_module, "STORES", None)
        self.stores = list(stores) if stores else [
            "bplatz", "deloox", "parfumcity", "parfumzentrum",
            "perfumemarket", "sabina", "orioudh", "notino",
        ]

    def analyze_query(self, query: str) -> Dict[str, Any]:
        raw = str(query or "").strip()
        norm = self.legacy.norm(raw) if hasattr(self.legacy, "norm") else raw.lower()
        size_ml = None
        try:
            m = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", raw, re.I)
            if m:
                size_ml = float(m.group(1).replace(",", "."))
                if m.group(2).lower() == "cl":
                    size_ml *= 10.0
        except Exception:
            pass
        return {"raw": raw, "normalized": norm, "size_ml": size_ml}

    @staticmethod
    def _safe_query(query: Any) -> str:
        return str(query or "").strip()

    @staticmethod
    def _candidate_key(item: Dict[str, Any]) -> tuple:
        store = str(item.get("store") or item.get("shop") or "").strip().casefold()
        url = str(item.get("url") or item.get("source_url") or "").strip().casefold()
        product_id = str(item.get("product_id") or item.get("sku") or "").strip().casefold()
        size = item.get("size_ml") or item.get("volume_ml") or item.get("format_ml")
        if size in (None, ""):
            size = ""
        return (store, product_id, url, str(size).strip().casefold())

    def _dedupe_raw(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove only true duplicate observations; never dedupe by product name."""
        out: List[Dict[str, Any]] = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            key = self._candidate_key(item)
            # If no URL/id exists, keep the observation. The matcher owns
            # identity decisions later and must see the complete evidence.
            if key[1] == "" and key[2] == "":
                out.append(item)
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _store_query(self, query: str) -> str:
        """Qualify one retailer query with the catalog brand, without extra calls."""
        raw = str(query or "").strip()
        if not raw:
            return raw
        try:
            family = self.legacy._catalog_family_for_query(raw)
        except Exception:
            family = None
        if not isinstance(family, dict):
            return raw
        brand = str(family.get("brand") or "").strip()
        if not brand:
            return raw
        norm = self.legacy.norm if hasattr(self.legacy, "norm") else lambda x: str(x).casefold()
        if norm(brand) in norm(raw).split():
            return raw
        return f"{brand} {raw}".strip()

    def _run_one_store(self, store: str, query: str) -> StoreRun:
        started = time.monotonic()
        try:
            runner = getattr(self.legacy, "run_store", None)
            if not callable(runner):
                raise RuntimeError("main.run_store is not available")
            store_query = self._store_query(query)
            raw = runner(store, store_query)
            if raw is None:
                candidates = []
            elif isinstance(raw, list):
                candidates = raw
            else:
                try:
                    candidates = list(raw)
                except Exception:
                    candidates = []
            candidates = [x for x in candidates if isinstance(x, dict)]
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
                candidates=[],
                elapsed=time.monotonic() - started,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _run_stores(self, query: str) -> Dict[str, Any]:
        """Start all stores immediately; each store has its own deadline."""
        started = time.monotonic()
        global_deadline = started + self.global_timeout
        results = {store: StoreRun(store=store) for store in self.stores}

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=len(self.stores),
            thread_name_prefix="scenthunter-store",
        )
        futures = {executor.submit(self._run_one_store, store, query): store for store in self.stores}
        future_started = {future: time.monotonic() for future in futures}
        pending = set(futures)

        try:
            while pending:
                now = time.monotonic()
                if now >= global_deadline:
                    break

                done = {future for future in pending if future.done()}
                for future in done:
                    pending.remove(future)
                    store = futures[future]
                    try:
                        results[store] = future.result()
                    except Exception as exc:
                        results[store] = StoreRun(
                            store=store, status="error",
                            elapsed=time.monotonic() - future_started[future],
                            error=f"{type(exc).__name__}: {exc}",
                        )

                now = time.monotonic()
                for future in list(pending):
                    if now - future_started[future] >= self.store_timeout:
                        pending.remove(future)
                        store = futures[future]
                        results[store] = StoreRun(
                            store=store, status="timeout", candidates=[],
                            elapsed=now - future_started[future],
                            error=f"store timeout ({self.store_timeout:.0f}s)",
                        )

                if pending:
                    time.sleep(0.05)

            if pending:
                now = time.monotonic()
                for future in pending:
                    store = futures[future]
                    results[store] = StoreRun(
                        store=store, status="timeout", candidates=[],
                        elapsed=now - future_started[future],
                        error=f"global search window expired ({self.global_timeout:.0f}s)",
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return {"stores": results, "elapsed": time.monotonic() - started}

    def _validate_candidates_only(self, query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
            value = item.get("price")
            if value is None:
                value = item.get("price_num")
            return float(value)
        except Exception:
            return float("inf")

    def _stable_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def offer_key(item: Dict[str, Any]) -> tuple:
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
                clean.sort(key=offer_key)
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
        output.sort(key=lambda x: offer_key(x.get("offers", [x])[0] if isinstance(x.get("offers"), list) and x.get("offers") else x))
        return output

    def _finalize(self, query: str, raw_pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        validated = self._validate_candidates_only(query, raw_pool)
        prepare = getattr(self.legacy, "_prepare_final_results", None)
        if callable(prepare):
            try:
                final = prepare(validated, query)
            except TypeError:
                final = prepare(validated)
        else:
            final = validated
        if final is None:
            final = []
        if not isinstance(final, list):
            final = list(final)
        return self._stable_results([x for x in final if isinstance(x, dict)])

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
        raw_pool = self._dedupe_raw(raw_pool)
        final = self._finalize(text, raw_pool)
        return {
            "query": text,
            "count": len(final),
            "results": final,
            "comparisons": [],
            "errors": errors,
        }

    def diagnostic_search(self, query: str) -> Dict[str, Any]:
        """Forensic read-only diagnostic of the REAL search pipeline.

        This intentionally measures every phase separately so we can distinguish:
        - retailer execution time;
        - orchestration/waiting time;
        - raw deduplication;
        - candidate validation;
        - final grouping/ranking.
        It never changes search results or job state.
        """
        text = self.analyze_query(query)["raw"]
        if not text:
            return {
                "ok": True,
                "diagnostic": "search-forensics-v1",
                "query": "",
                "timings": {},
                "stores": {},
                "raw_candidates": [],
                "validated_candidates": [],
                "errors": {},
            }

        started = time.monotonic()
        timings: Dict[str, float] = {}
        stores: Dict[str, Any] = {}
        errors: Dict[str, str] = {}

        t0 = time.monotonic()
        store_run = self._run_stores(text)
        timings["stores_wall_time"] = round(time.monotonic() - t0, 3)
        timings["orchestrator_total_store_phase"] = round(store_run.get("elapsed", 0.0), 3)

        raw_pool: List[Dict[str, Any]] = []
        for store in self.stores:
            result = store_run["stores"][store]
            raw_pool.extend(result.candidates)
            stores[store] = {
                "status": result.status,
                "count": len(result.candidates),
                "elapsed": round(result.elapsed, 3),
                "error": result.error,
                "candidates": [dict(x) for x in result.candidates],
            }
            if result.error:
                errors[store] = result.error

        t0 = time.monotonic()
        before_dedupe = len(raw_pool)
        raw_pool = self._dedupe_raw(raw_pool)
        timings["dedupe"] = round(time.monotonic() - t0, 3)

        t0 = time.monotonic()
        validated = self._validate_candidates_only(text, raw_pool)
        timings["validation"] = round(time.monotonic() - t0, 3)

        t0 = time.monotonic()
        prepare = getattr(self.legacy, "_prepare_final_results", None)
        if callable(prepare):
            try:
                prepared = prepare(validated, text)
            except TypeError:
                prepared = prepare(validated)
        else:
            prepared = validated
        if prepared is None:
            prepared = []
        if not isinstance(prepared, list):
            prepared = list(prepared)
        prepared = [x for x in prepared if isinstance(x, dict)]
        timings["final_prepare"] = round(time.monotonic() - t0, 3)

        t0 = time.monotonic()
        final = self._stable_results(prepared)
        timings["stable_sort"] = round(time.monotonic() - t0, 3)
        timings["total"] = round(time.monotonic() - started, 3)

        slowest_store = max(
            stores.items(),
            key=lambda pair: float(pair[1].get("elapsed") or 0.0),
            default=(None, {"elapsed": 0}),
        )
        timed_out = [
            name for name, info in stores.items()
            if info.get("status") == "timeout"
        ]

        return {
            "ok": True,
            "diagnostic": "search-forensics-v1",
            "query": text,
            "timings": timings,
            "store_count": len(self.stores),
            "stores": stores,
            "slowest_store": slowest_store[0],
            "slowest_store_seconds": slowest_store[1].get("elapsed", 0),
            "timed_out_stores": timed_out,
            "raw_candidate_count_before_dedupe": before_dedupe,
            "raw_candidate_count": len(raw_pool),
            "validated_candidate_count": len(validated),
            "final_result_count": len(final),
            "raw_candidates": [dict(x) for x in raw_pool],
            "validated_candidates": [dict(x) for x in validated],
            "errors": errors,
            "interpretation": {
                "store_bottleneck": bool(timed_out) or timings["stores_wall_time"] >= 10.0,
                "validation_bottleneck": timings["validation"] >= 2.0,
                "finalization_bottleneck": (timings["final_prepare"] + timings["stable_sort"]) >= 2.0,
            },
        }

    def search_job_snapshot(self, job_id: str) -> Dict[str, Any]:
        """Return the live progressive job state without re-running finalization.

        ``main_legacy._search_job_snapshot`` historically re-applied its own
        finalizer to ``job["results"]``. The progressive SearchEngine already
        stores canonical final groups at every publication step, so reprocessing
        them would add latency and could distort partial results.
        """
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
            job = jobs.get(str(job_id or "").strip())
            if job is None:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Job di ricerca non trovato")
            snapshot = dict(job)

        results = snapshot.get("results")
        if not isinstance(results, list):
            results = []

        store_status = snapshot.get("store_status")
        if not isinstance(store_status, dict):
            store_status = {}

        completed_stores = sum(
            1 for info in store_status.values()
            if isinstance(info, dict)
            and info.get("status") not in ("pending", "searching")
        )

        completed = bool(snapshot.get("completed"))
        return {
            "job_id": str(job_id),
            "query": str(snapshot.get("query") or ""),
            "count": len(results),
            "results": list(results),
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

    def _run_job_impl(self, job_id: str, query: str) -> None:
        jobs = getattr(self.legacy, "SEARCH_JOBS", None)
        lock = getattr(self.legacy, "SEARCH_JOBS_LOCK", None)
        if jobs is None:
            legacy_runner = getattr(self.legacy, "_run_search_job_legacy", None)
            if callable(legacy_runner):
                return legacy_runner(job_id, query)
            raise RuntimeError("SEARCH_JOBS is not available")

        def update(payload: Dict[str, Any]) -> None:
            if lock is not None:
                with lock:
                    job = jobs.get(job_id)
                    if job is not None:
                        job.update(payload)
            else:
                job = jobs.get(job_id)
                if job is not None:
                    job.update(payload)

        started = time.monotonic()
        phase_timings: Dict[str, Any] = {
            "job_started_monotonic": started,
            "store_execution": {},
            "job_update_count": 0,
            "waves": [],
        }

        # Deliberate two-wave scheduling.
        # Wave 1 is the historical fast/priority group.  Wave 2 starts only
        # after Wave 1 has released its four connections.  This avoids the
        # eight-way connection burst that was causing 502/503/429 cascades,
        # while preserving the old visible order: first four, then the other four.
        priority_wave = [
            store for store in (
                "bplatz", "deloox", "parfumzentrum", "parfumcity"
            ) if store in self.stores
        ]
        second_wave = [
            store for store in self.stores if store not in priority_wave
        ]
        waves = [priority_wave, second_wave]
        waves = [wave for wave in waves if wave]

        store_status = {
            store: {"status": "pending", "count": 0}
            for store in self.stores
        }
        update({
            "completed": False,
            "phase": "discovery",
            "status": "searching",
            "results": [],
            "candidates": [],
            "errors": {},
            "store_status": store_status,
            "completed_stores": 0,
            "total_stores": len(self.stores),
        })

        raw_pool: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}
        last_partial_finalize = 0.0
        last_partial_results: List[Dict[str, Any]] = []
        deadline = started + self.global_timeout

        def publish_store_result(store: str, result: StoreRun, wave_index: int) -> None:
            nonlocal raw_pool, last_partial_finalize, last_partial_results

            store_status[store] = {
                "status": result.status,
                "count": len(result.candidates),
                "elapsed": round(result.elapsed, 3),
                "error": result.error,
                "wave": wave_index + 1,
            }
            phase_timings["store_execution"][store] = {
                "status": result.status,
                "elapsed": round(result.elapsed, 3),
                "count": len(result.candidates),
                "wave": wave_index + 1,
            }
            raw_pool.extend(result.candidates)
            if result.error:
                errors[store] = result.error

            partial_raw = self._dedupe_raw(list(raw_pool))
            # Canonicalize immediately for the first result, then at most every
            # 250 ms.  The first store result must reach the UI without waiting
            # for the other stores or for the whole wave.
            should_finalize = (
                bool(partial_raw)
                and (
                    not last_partial_results
                    or (time.monotonic() - last_partial_finalize) >= 0.25
                )
            )
            if should_finalize:
                try:
                    last_partial_results = list(
                        self._finalize(query, partial_raw)
                    )
                    last_partial_finalize = time.monotonic()
                except Exception as exc:
                    phase_timings.setdefault(
                        "partial_finalize_errors", []
                    ).append(f"{type(exc).__name__}: {exc}")

            completed_stores = sum(
                1 for info in store_status.values()
                if info.get("status") not in ("pending", "searching")
            )
            update({
                "completed": False,
                "phase": "collecting",
                "status": "searching",
                "results": list(last_partial_results),
                "candidates": list(partial_raw),
                "errors": dict(errors),
                "store_status": dict(store_status),
                "completed_stores": completed_stores,
                "total_stores": len(self.stores),
                "partial_result_count": len(last_partial_results),
                "elapsed": round(time.monotonic() - started, 3),
                "wave": wave_index + 1,
            })

        try:
            for wave_index, wave in enumerate(waves):
                if time.monotonic() >= deadline:
                    break

                wave_started = time.monotonic()
                wave_deadline = min(deadline, wave_started + self.store_timeout)
                for store in wave:
                    store_status[store] = {
                        "status": "searching",
                        "count": 0,
                        "wave": wave_index + 1,
                    }

                executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=len(wave),
                    thread_name_prefix=f"scenthunter-wave{wave_index + 1}",
                )
                futures = {
                    executor.submit(self._run_one_store, store, query): store
                    for store in wave
                }
                pending = set(futures)

                try:
                    while pending and time.monotonic() < wave_deadline:
                        done, pending = concurrent.futures.wait(
                            pending,
                            timeout=min(
                                0.10,
                                max(0.01, wave_deadline - time.monotonic()),
                            ),
                            return_when=concurrent.futures.FIRST_COMPLETED,
                        )
                        for future in done:
                            store = futures[future]
                            try:
                                result = future.result()
                            except Exception as exc:
                                result = StoreRun(
                                    store=store,
                                    status="error",
                                    error=f"{type(exc).__name__}: {exc}",
                                )
                            publish_store_result(store, result, wave_index)

                    if pending:
                        now = time.monotonic()
                        for future in pending:
                            store = futures[future]
                            result = StoreRun(
                                store=store,
                                status="timeout",
                                candidates=[],
                                elapsed=now - wave_started,
                                error=(
                                    f"store timeout ({self.store_timeout:.0f}s)"
                                ),
                            )
                            publish_store_result(store, result, wave_index)
                finally:
                    executor.shutdown(wait=True, cancel_futures=True)

                phase_timings["waves"].append({
                    "wave": wave_index + 1,
                    "stores": list(wave),
                    "elapsed": round(time.monotonic() - wave_started, 3),
                })

                # Do not start wave 2 if the global window has expired.
                if time.monotonic() >= deadline:
                    break

            # Any store not reached because the global window expired is marked
            # explicitly instead of silently disappearing from the final state.
            for store, info in store_status.items():
                if info.get("status") in ("pending", "searching"):
                    store_status[store] = {
                        "status": "timeout",
                        "count": 0,
                        "elapsed": round(time.monotonic() - started, 3),
                        "error": (
                            f"global search window expired ({self.global_timeout:.0f}s)"
                        ),
                    }
                    errors[store] = store_status[store]["error"]

            t0 = time.monotonic()
            raw_before_dedupe = len(raw_pool)
            raw_pool = self._dedupe_raw(raw_pool)
            phase_timings["dedupe"] = round(time.monotonic() - t0, 3)
            phase_timings["raw_candidates_before_dedupe"] = raw_before_dedupe
            phase_timings["raw_candidates"] = len(raw_pool)

            t0 = time.monotonic()
            validated = self._validate_candidates_only(query, raw_pool)
            phase_timings["validation"] = round(time.monotonic() - t0, 3)
            phase_timings["validated_candidates"] = len(validated)

            t0 = time.monotonic()
            prepare = getattr(self.legacy, "_prepare_final_results", None)
            if callable(prepare):
                try:
                    prepared = prepare(validated, query)
                except TypeError:
                    prepared = prepare(validated)
            else:
                prepared = validated
            if prepared is None:
                prepared = []
            if not isinstance(prepared, list):
                prepared = list(prepared)
            prepared = [x for x in prepared if isinstance(x, dict)]
            phase_timings["final_prepare"] = round(time.monotonic() - t0, 3)

            t0 = time.monotonic()
            final = self._stable_results(prepared)
            phase_timings["stable_sort"] = round(time.monotonic() - t0, 3)

            elapsed = round(time.monotonic() - started, 3)
            phase_timings["total_before_final_update"] = elapsed
            update({
                "results": final,
                "candidates": list(raw_pool),
                "errors": dict(errors),
                "store_status": dict(store_status),
                "phase": "completed",
                "status": "completed",
                "completed": True,
                "elapsed": elapsed,
                "raw_candidate_count": len(raw_pool),
                "result_count": len(final),
                "diagnostic": {
                    **phase_timings,
                    "total": elapsed,
                },
            })
        except Exception as exc:
            update({
                "results": [],
                "candidates": [],
                "errors": {"_search": f"{type(exc).__name__}: {exc}"},
                "status": "error",
                "completed": True,
                "phase": "error",
                "elapsed": round(time.monotonic() - started, 3),
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
                "diagnostic": {
                    **phase_timings,
                    "total": round(time.monotonic() - started, 3),
                },
            })

    def run_job(self, job_id: str, query: str) -> None:
        # Only one complete search may actively hit the eight shops at a time.
        # A second search is queued instead of creating overlapping scraper
        # waves, which was the source of the observed 502/503/429 cascade.
        with self._execution_lock:
            return self._run_job_impl(job_id, query)
