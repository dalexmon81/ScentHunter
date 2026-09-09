"""ScentHunter search orchestration v4.

Fixed two-wave scheduler:
  WAVE 1: bplatz, deloox, parfumcity, perfumemarket
  WAVE 2: orioudh, parfumzentrum, sabina, notino

A wave is fully settled (success, empty, error, or per-store timeout)
before the next wave starts. There is no rolling refill.

Store adapters are left untouched. Central validation/grouping/finalization
runs only after both waves have settled.
"""
from __future__ import annotations

import concurrent.futures
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


DEFAULT_STORE_TIMEOUT = 18.0
DEFAULT_GLOBAL_TIMEOUT = 45.0
MAX_CONCURRENT_STORES = 4

STORE_WAVES = (
    ("bplatz", "deloox", "parfumcity", "perfumemarket"),
    ("orioudh", "parfumzentrum", "sabina", "notino"),
)
STORE_PRIORITY = [x for wave in STORE_WAVES for x in wave]


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
        self.global_timeout = max(float(global_timeout), self.store_timeout * 2.0 + 2.0)

        configured = list(getattr(legacy_module, "STORES", None) or STORE_PRIORITY)
        configured_set = set(configured)
        ordered = [s for s in STORE_PRIORITY if s in configured_set]
        ordered += [s for s in configured if s not in ordered]
        self.stores = ordered

        requested = MAX_CONCURRENT_STORES if max_concurrent_stores is None else int(max_concurrent_stores)
        self.max_concurrent_stores = max(1, min(requested, 4, len(self.stores) or 1))

    def analyze_query(self, query: str) -> Dict[str, Any]:
        raw = str(query or "").strip()
        norm = self.legacy.norm(raw) if hasattr(self.legacy, "norm") else raw.lower()
        size_ml = None
        m = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", raw, re.I)
        if m:
            size_ml = float(m.group(1).replace(",", "."))
            if m.group(2).lower() == "cl":
                size_ml *= 10.0
        return {"raw": raw, "normalized": norm, "size_ml": size_ml}

    @staticmethod
    def _candidate_key(item: Dict[str, Any]) -> tuple:
        store = str(item.get("store") or item.get("shop") or "").strip().casefold()
        url = str(item.get("url") or item.get("source_url") or "").strip().casefold()
        product_id = str(item.get("product_id") or item.get("sku") or "").strip().casefold()
        size = item.get("size_ml") or item.get("volume_ml") or item.get("format_ml") or ""
        return (store, product_id, url, str(size).strip().casefold())

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
                elapsed=time.monotonic() - started,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _run_stores(self, query: str) -> Dict[str, Any]:
        started = time.monotonic()
        deadline = started + self.global_timeout
        results: Dict[str, StoreRun] = {store: StoreRun(store=store) for store in self.stores}

        for wave in STORE_WAVES:
            active = [s for s in wave if s in self.stores]
            if not active:
                continue
            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=min(self.max_concurrent_stores, len(active)),
                thread_name_prefix="scenthunter-store",
            )
            futures: Dict[concurrent.futures.Future, tuple[str, float]] = {}
            try:
                for store in active:
                    if time.monotonic() >= deadline:
                        results[store] = StoreRun(
                            store=store,
                            status="timeout",
                            elapsed=time.monotonic() - started,
                            error="global search window expired before wave start",
                        )
                        continue
                    future = executor.submit(self._run_one_store, store, query)
                    futures[future] = (store, time.monotonic())

                while futures:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break

                    now = time.monotonic()
                    expired = [
                        future
                        for future, (store, submitted) in futures.items()
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
                        timeout=min(0.10, remaining, self.store_timeout),
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                    done.update(f for f in list(futures) if f.done())
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
                        elapsed=now - submitted,
                        error="global search window expired",
                    )
                    future.cancel()
                    futures.pop(future, None)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            # STRICT BARRIER: no store from the next wave is submitted until
            # every store in this wave is settled.
        return {"stores": results, "elapsed": time.monotonic() - started}

    @staticmethod
    def _availability_rank(item: Dict[str, Any]) -> int:
        value = str(
            item.get("availability")
            or item.get("stock_status")
            or item.get("stock")
            or ""
        ).strip().lower()
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
                for field in (
                    "store", "price", "url", "image", "availability",
                    "available", "size_ml", "concentration", "gender",
                ):
                    if field in best:
                        item[field] = best[field]
            output.append(item)

        output.sort(key=lambda x: offer_key(
            x.get("offers", [x])[0]
            if isinstance(x.get("offers"), list) and x.get("offers")
            else x
        ))
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

    def _publish_results(self, query: str, raw_pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self._orchestrate(query, raw_pool)

    def _publish_validated_results(self, query: str, validated_pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        prepare = getattr(self.legacy, "_prepare_final_results", None)
        if callable(prepare):
            try:
                result = prepare(validated_pool, query)
            except TypeError:
                result = prepare(validated_pool)
        else:
            result = validated_pool
        if result is None:
            return []
        if not isinstance(result, list):
            result = list(result)
        return self._stable_results([x for x in result if isinstance(x, dict)])

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
        """Read-only per-store forensic diagnostic.

        This keeps the existing diagnostic endpoint alive while making the
        scheduler itself independent from it.
        """
        text = self.analyze_query(query)["raw"]
        started = time.monotonic()
        reports: Dict[str, Any] = {}

        def diagnose(store: str) -> Dict[str, Any]:
            t0 = time.monotonic()
            info: Dict[str, Any] = {
                "store": store,
                "status": "error",
                "module_load_seconds": None,
                "attempt_build_seconds": None,
                "attempts": [],
                "candidate_count": 0,
                "postprocess_seconds": 0.0,
                "run_store_equivalent_seconds": None,
                "error": None,
            }
            try:
                loader = getattr(self.legacy, "load_scraper")
                module_t = time.monotonic()
                module = loader(store)
                info["module_load_seconds"] = round(time.monotonic() - module_t, 4)
                search_fn = getattr(module, "search", None) or getattr(module, "scrape", None)
                if not callable(search_fn):
                    raise RuntimeError("scraper senza funzione search()/scrape()")

                builder = getattr(self.legacy, "build_search_attempts", None)
                attempts = list(builder(store, text) or []) if callable(builder) else [text]
                info["attempt_build_seconds"] = 0.0

                raw: List[Dict[str, Any]] = []
                for index, attempt in enumerate(attempts):
                    attempt_t = time.monotonic()
                    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    future = executor.submit(search_fn, attempt)
                    try:
                        payload = future.result(timeout=self.store_timeout + 2.0)
                        items = payload or []
                        if not isinstance(items, list):
                            items = list(items)
                        items = [x for x in items if isinstance(x, dict)]
                        info["attempts"].append({
                            "index": index,
                            "query": attempt,
                            "search_call_seconds": round(time.monotonic() - attempt_t, 4),
                            "search_call_status": "ok",
                            "returned_count": len(items),
                            "error": None,
                        })
                        raw.extend(items)
                        if raw:
                            break
                    except concurrent.futures.TimeoutError:
                        info["attempts"].append({
                            "index": index,
                            "query": attempt,
                            "search_call_seconds": round(time.monotonic() - attempt_t, 4),
                            "search_call_status": "timeout",
                            "returned_count": 0,
                            "error": f"search call exceeded {self.store_timeout + 2.0:.0f}s diagnostic deadline",
                        })
                        info["status"] = "timeout"
                        info["error"] = info["attempts"][-1]["error"]
                        future.cancel()
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    except Exception as exc:
                        info["attempts"].append({
                            "index": index,
                            "query": attempt,
                            "search_call_seconds": round(time.monotonic() - attempt_t, 4),
                            "search_call_status": "error",
                            "returned_count": 0,
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                    finally:
                        if future.done():
                            executor.shutdown(wait=True, cancel_futures=True)
                        else:
                            executor.shutdown(wait=False, cancel_futures=True)

                info["candidate_count"] = len(raw)
                if info["status"] != "timeout":
                    info["status"] = "ok" if raw else "empty"
                info["run_store_equivalent_seconds"] = round(time.monotonic() - t0, 4)
                info["candidates"] = [
                    {
                        "store": x.get("store"),
                        "name": x.get("name"),
                        "price": x.get("price"),
                        "available": x.get("available"),
                        "url": x.get("url"),
                    }
                    for x in raw
                ]
                return info
            except Exception as exc:
                info["error"] = f"{type(exc).__name__}: {exc}"
                info["run_store_equivalent_seconds"] = round(time.monotonic() - t0, 4)
                return info

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(self.stores) or 1)
        futures = {executor.submit(diagnose, store): store for store in self.stores}
        try:
            for future in concurrent.futures.as_completed(futures):
                store = futures[future]
                try:
                    reports[store] = future.result()
                except Exception as exc:
                    reports[store] = {
                        "store": store,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        ordered = {store: reports.get(store, {"store": store, "status": "missing"}) for store in self.stores}
        return {
            "ok": True,
            "diagnostic_type": "store_stage_forensics_v3",
            "query": self.analyze_query(text),
            "production_limits": {
                "store_timeout_seconds": self.store_timeout,
                "global_timeout_seconds": self.global_timeout,
                "diagnostic_attempt_deadline_seconds": self.store_timeout + 2.0,
            },
            "total_diagnostic_seconds": round(time.monotonic() - started, 3),
            "stores": ordered,
            "interpretation": {
                "search_call_bottleneck": [
                    name for name, info in ordered.items()
                    if any(
                        float(a.get("search_call_seconds") or 0.0) >= 5.0
                        or a.get("search_call_status") == "timeout"
                        for a in info.get("attempts", [])
                        if isinstance(a, dict)
                    )
                ]
            },
        }

    @staticmethod
    def _result_identity(item: Dict[str, Any]) -> tuple:
        brand = str(item.get("brand") or "").strip().casefold()
        name = str(item.get("name") or item.get("title") or "").strip().casefold()
        size = str(item.get("size_ml") or item.get("size") or "").strip().casefold()
        return (brand, name, size)

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
            job = jobs.get(str(job_id or "").strip())
            if job is None:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Job di ricerca non trovato")
            snapshot = dict(job)

        results = snapshot.get("results")
        if not isinstance(results, list):
            results = []
        batch_results = snapshot.get("batch_results")
        if not isinstance(batch_results, list):
            batch_results = []
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
        jobs = getattr(self.legacy, "SEARCH_JOBS", None)
        lock = getattr(self.legacy, "SEARCH_JOBS_LOCK", None)
        if jobs is None:
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
        store_status: Dict[str, Any] = {
            store: {"status": "pending", "count": 0} for store in self.stores
        }
        errors: Dict[str, str] = {}
        raw_pool: List[Dict[str, Any]] = []
        raw_lock = __import__("threading").Lock()
        previous_results: List[Dict[str, Any]] = []

        update({
            "status": "searching",
            "phase": "discovery",
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
            "results_are_final": True,
            "elapsed": 0.0,
        })

        def publish_wave(wave_number: int) -> None:
            nonlocal previous_results
            with raw_lock:
                wave_raw = [dict(x) for x in raw_pool if isinstance(x, dict)]
            final_results = self._finalize(query, wave_raw)

            # Publish exactly one immutable UI batch per wave.
            # Wave 1 publishes its complete result set. Wave 2 publishes only
            # the newly introduced product groups, while `results` remains the
            # cumulative list for consumers that want the full set.
            previous_keys = {self._result_identity(x) for x in previous_results}
            batch_results = [
                dict(x) for x in final_results
                if self._result_identity(x) not in previous_keys
            ]
            if wave_number == 1 and not previous_results:
                batch_results = [dict(x) for x in final_results]

            previous_results = [dict(x) for x in final_results]
            update({
                "status": "searching",
                "phase": f"wave_{wave_number}_published",
                "completed": False,
                "results": [dict(x) for x in final_results],
                "batch_results": batch_results,
                "batch_id": wave_number,
                "wave": wave_number,
                "comparisons": [],
                "errors": dict(errors),
                "store_status": dict(store_status),
                "completed_stores": sum(
                    1 for info in store_status.values()
                    if isinstance(info, dict)
                    and info.get("status") not in ("pending", "searching")
                ),
                "total_stores": len(self.stores),
                "raw_candidate_count": len(wave_raw),
                "results_are_final": True,
                "elapsed": round(time.monotonic() - started, 3),
            })

        try:
            for wave_number, wave in enumerate(STORE_WAVES, start=1):
                active = [s for s in wave if s in self.stores]
                if not active:
                    continue

                # Each wave gets its own hard timeout. The second wave does not
                # inherit remaining time from the first wave.
                wave_started = time.monotonic()
                wave_deadline = wave_started + self.store_timeout

                for store in active:
                    store_status[store] = {"status": "searching", "count": 0}
                update({
                    "phase": f"discovery_wave_{wave_number}",
                    "wave": wave_number,
                    "store_status": dict(store_status),
                    "elapsed": round(time.monotonic() - started, 3),
                })

                executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(self.max_concurrent_stores, len(active)),
                    thread_name_prefix="scenthunter-store",
                )
                futures: Dict[concurrent.futures.Future, tuple[str, float]] = {}
                try:
                    for store in active:
                        future = executor.submit(self._run_one_store, store, query)
                        futures[future] = (store, time.monotonic())

                    while futures:
                        remaining = wave_deadline - time.monotonic()
                        if remaining <= 0:
                            break

                        done, _ = concurrent.futures.wait(
                            list(futures),
                            timeout=min(0.10, remaining),
                            return_when=concurrent.futures.FIRST_COMPLETED,
                        )
                        done.update(f for f in list(futures) if f.done())

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

                            candidates = [x for x in (result.candidates or []) if isinstance(x, dict)]
                            with raw_lock:
                                raw_pool.extend(candidates)
                                raw_pool[:] = self._dedupe_raw(raw_pool)

                            store_status[store] = {
                                "status": result.status,
                                "count": len(candidates),
                                "elapsed": round(result.elapsed, 3),
                            }
                            if result.error:
                                store_status[store]["error"] = result.error
                                errors[store] = result.error

                    now = time.monotonic()
                    for future, (store, submitted) in list(futures.items()):
                        error = "store timeout"
                        store_status[store] = {
                            "status": "timeout",
                            "count": 0,
                            "elapsed": round(max(0.0, now - submitted), 3),
                            "error": error,
                        }
                        errors[store] = error
                        future.cancel()
                        futures.pop(future, None)
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)

                # This is the ONLY publication point for this wave. Nothing is
                # sent to the frontend while individual stores finish.
                publish_wave(wave_number)

            with raw_lock:
                final_raw = list(raw_pool)
            final_results = self._finalize(query, final_raw)

            update({
                "status": "completed",
                "phase": "completed",
                "completed": True,
                "results": [dict(x) for x in final_results],
                "batch_results": [],
                "batch_id": 2,
                "wave": 2,
                "comparisons": [],
                "errors": dict(errors),
                "store_status": dict(store_status),
                "completed_stores": sum(
                    1 for info in store_status.values()
                    if isinstance(info, dict)
                    and info.get("status") not in ("pending", "searching")
                ),
                "total_stores": len(self.stores),
                "raw_candidate_count": len(final_raw),
                "results_are_final": True,
                "elapsed": round(time.monotonic() - started, 3),
            })
        except Exception as exc:
            update({
                "status": "error",
                "phase": "completed",
                "completed": True,
                "results": [dict(x) for x in previous_results],
                "batch_results": [],
                "batch_id": 0,
                "wave": 0,
                "comparisons": [],
                "error": f"{type(exc).__name__}: {exc}",
                "errors": dict(errors),
                "traceback": traceback.format_exc(limit=8),
                "results_are_final": True,
                "elapsed": round(time.monotonic() - started, 3),
            })
