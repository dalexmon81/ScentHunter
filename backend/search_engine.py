"""ScentHunter search orchestration v2.

The live search layer is deliberately simple:
- one request to each of the eight store adapters;
- all stores start independently and concurrently;
- no central query rewriting;
- no central retries (store adapters own their retry/rate-limit policy);
- raw candidates are collected losslessly;
- validation/grouping/ranking is applied to the candidates received so far;
- completed stores are published progressively to the frontend;
- the final result is finalized once all stores finish or the global window expires.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_STORE_TIMEOUT = 26.0
DEFAULT_GLOBAL_TIMEOUT = 30.0


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

    def _orchestrate(self, query: str, raw_pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run the legacy central validation/grouping pipeline on current evidence.

        The store adapters only discover offers. Identity, format grouping,
        availability ordering and catalog rules remain centralized in legacy.
        """
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

    def _publish_results(
        self,
        query: str,
        raw_pool: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Build the exact frontend result shape from the evidence received so far."""
        return self._orchestrate(query, raw_pool)

    def _publish_validated_results(
        self,
        query: str,
        validated_pool: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Prepare already-validated evidence without validating old offers again."""
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
        """Read-only forensic diagnostic of the store stage internals.

        Unlike the normal production runner, this diagnostic intentionally
        breaks each store into measurable stages:

        1. scraper module load;
        2. search function resolution;
        3. construction of the normal production attempts;
        4. each individual search() / scrape() call;
        5. post-processing of returned candidates (price/image/identity);
        6. duplicate filtering and total run_store-equivalent time.

        Each individual search attempt is executed in its own worker with a
        deadline slightly above the production per-store timeout. The
        diagnostic is read-only and does not alter SEARCH_JOBS or production
        search behavior.
        """
        text = self.analyze_query(query)["raw"]
        if not text:
            return {
                "ok": True,
                "diagnostic_type": "store_stage_forensics_v2",
                "query": self.analyze_query(query),
                "stores": {},
                "timings": {},
            }

        diagnostic_started = time.monotonic()
        attempts_builder = getattr(self.legacy, "build_search_attempts", None)
        loader = getattr(self.legacy, "load_scraper", None)
        price_resolver = getattr(self.legacy, "resolve_actual_price", None)
        image_resolver = getattr(self.legacy, "product_image", None)
        identity_builder = getattr(self.legacy, "product_identity_key", None)

        if not callable(loader):
            raise RuntimeError("legacy.load_scraper is not available")
        if not callable(attempts_builder):
            raise RuntimeError("legacy.build_search_attempts is not available")
        if not callable(price_resolver):
            raise RuntimeError("legacy.resolve_actual_price is not available")
        if not callable(image_resolver):
            raise RuntimeError("legacy.product_image is not available")
        if not callable(identity_builder):
            raise RuntimeError("legacy.product_identity_key is not available")

        def diagnose_store(store: str) -> Dict[str, Any]:
            store_started = time.monotonic()
            info: Dict[str, Any] = {
                "store": store,
                "status": "error",
                "module_load_seconds": None,
                "attempt_build_seconds": None,
                "attempts": [],
                "candidate_count": 0,
                "postprocess_seconds": 0.0,
                "dedupe_seconds": 0.0,
                "run_store_equivalent_seconds": None,
                "error": None,
            }

            try:
                t0 = time.monotonic()
                module = loader(store)
                info["module_load_seconds"] = round(time.monotonic() - t0, 4)
            except Exception as exc:
                info["error"] = f"module_load: {type(exc).__name__}: {exc}"
                info["status"] = "error"
                info["run_store_equivalent_seconds"] = round(time.monotonic() - store_started, 4)
                return info

            search_fn = getattr(module, "search", None)
            if not callable(search_fn):
                search_fn = getattr(module, "scrape", None)
            diagnostic_fn = getattr(module, "diagnostic_search", None)
            if not callable(search_fn):
                info["error"] = "scraper senza funzione search()/scrape()"
                info["status"] = "error"
                info["run_store_equivalent_seconds"] = round(time.monotonic() - store_started, 4)
                return info
            # Some adapters expose an opt-in internal forensic function.
            # It executes the same real search but also reports every
            # network request and internal stage. Normal production search
            # never calls this function.

            try:
                t0 = time.monotonic()
                attempts = list(attempts_builder(store, text) or [])
                info["attempt_build_seconds"] = round(time.monotonic() - t0, 4)
            except Exception as exc:
                info["error"] = f"attempt_build: {type(exc).__name__}: {exc}"
                info["status"] = "error"
                info["run_store_equivalent_seconds"] = round(time.monotonic() - store_started, 4)
                return info

            raw_output: List[Dict[str, Any]] = []
            seen = set()

            for attempt_index, attempt in enumerate(attempts):
                attempt_started = time.monotonic()
                attempt_info: Dict[str, Any] = {
                    "index": attempt_index,
                    "query": attempt,
                    "search_call_seconds": None,
                    "search_call_status": "pending",
                    "returned_count": 0,
                    "postprocess_seconds": 0.0,
                    "postprocess": {
                        "resolve_actual_price_seconds": 0.0,
                        "product_image_seconds": 0.0,
                        "product_identity_key_seconds": 0.0,
                    },
                    "dedupe_seconds": 0.0,
                    "accepted_count": 0,
                    "error": None,
                }

                # Use a one-shot worker so a hanging shop search can be
                # identified without blocking the whole diagnostic endpoint.
                executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix=f"scenthunter-diag-{store}",
                )
                use_internal_trace = callable(diagnostic_fn)
                future = executor.submit(
                    diagnostic_fn if use_internal_trace else search_fn,
                    attempt,
                )
                try:
                    payload = future.result(timeout=self.store_timeout + 2.0)
                    if use_internal_trace and isinstance(payload, dict) and "results" in payload:
                        results = payload.get("results") or []
                        attempt_info["internal_trace"] = payload.get("trace") or {}
                    else:
                        results = payload or []
                    attempt_info["search_call_seconds"] = round(time.monotonic() - attempt_started, 4)
                    attempt_info["search_call_status"] = "ok"
                except concurrent.futures.TimeoutError:
                    attempt_info["search_call_seconds"] = round(time.monotonic() - attempt_started, 4)
                    attempt_info["search_call_status"] = "timeout"
                    attempt_info["error"] = f"search call exceeded {self.store_timeout + 2.0:.0f}s diagnostic deadline"
                    info["attempts"].append(attempt_info)
                    executor.shutdown(wait=False, cancel_futures=True)
                    info["status"] = "timeout"
                    info["error"] = attempt_info["error"]
                    break
                except Exception as exc:
                    attempt_info["search_call_seconds"] = round(time.monotonic() - attempt_started, 4)
                    attempt_info["search_call_status"] = "error"
                    attempt_info["error"] = f"{type(exc).__name__}: {exc}"
                    info["attempts"].append(attempt_info)
                    executor.shutdown(wait=False, cancel_futures=True)
                    continue
                finally:
                    if not future.done():
                        executor.shutdown(wait=False, cancel_futures=True)
                    else:
                        executor.shutdown(wait=True, cancel_futures=True)

                if results is None:
                    results = []
                if not isinstance(results, list):
                    try:
                        results = list(results)
                    except Exception:
                        results = []

                results = [x for x in results if isinstance(x, dict)]
                attempt_info["returned_count"] = len(results)

                for item in results:
                    product = dict(item)
                    product.setdefault("store", store)

                    t0 = time.monotonic()
                    try:
                        product = price_resolver(product)
                    except Exception as exc:
                        attempt_info.setdefault("postprocess_errors", []).append(
                            f"resolve_actual_price: {type(exc).__name__}: {exc}"
                        )
                    attempt_info["postprocess"]["resolve_actual_price_seconds"] += time.monotonic() - t0

                    t0 = time.monotonic()
                    try:
                        image = image_resolver(product)
                        if image:
                            product["image"] = image
                    except Exception as exc:
                        attempt_info.setdefault("postprocess_errors", []).append(
                            f"product_image: {type(exc).__name__}: {exc}"
                        )
                    attempt_info["postprocess"]["product_image_seconds"] += time.monotonic() - t0

                    t0 = time.monotonic()
                    try:
                        key = identity_builder(product)
                    except Exception as exc:
                        attempt_info.setdefault("postprocess_errors", []).append(
                            f"product_identity_key: {type(exc).__name__}: {exc}"
                        )
                        key = None
                    attempt_info["postprocess"]["product_identity_key_seconds"] += time.monotonic() - t0

                    if key in seen:
                        continue
                    seen.add(key)
                    raw_output.append(product)

                attempt_info["postprocess_seconds"] = round(
                    sum(float(v or 0.0) for v in attempt_info["postprocess"].values()),
                    4,
                )
                t0 = time.monotonic()
                attempt_info["accepted_count"] = len(raw_output)
                attempt_info["dedupe_seconds"] = round(time.monotonic() - t0, 4)
                info["attempts"].append(attempt_info)

                # Exactly mirrors the current production run_store behavior:
                # stop after the first attempt that produced candidates.
                if raw_output:
                    break

            info["candidate_count"] = len(raw_output)
            info["postprocess_seconds"] = round(
                sum(float(a.get("postprocess_seconds") or 0.0) for a in info["attempts"]),
                4,
            )
            info["dedupe_seconds"] = round(
                sum(float(a.get("dedupe_seconds") or 0.0) for a in info["attempts"]),
                4,
            )
            if info["status"] != "timeout":
                info["status"] = "ok" if raw_output else "empty"
            info["run_store_equivalent_seconds"] = round(time.monotonic() - store_started, 4)
            info["candidates"] = [
                {
                    "store": x.get("store"),
                    "name": x.get("name"),
                    "price": x.get("price"),
                    "available": x.get("available"),
                    "url": x.get("url"),
                }
                for x in raw_output
            ]
            return info

        # All eight stores are diagnosed concurrently, just like production.
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, len(self.stores)),
            thread_name_prefix="scenthunter-diagnostic-store",
        )
        futures = {executor.submit(diagnose_store, store): store for store in self.stores}
        diagnosed: Dict[str, Any] = {}
        try:
            for future in concurrent.futures.as_completed(futures):
                store = futures[future]
                try:
                    diagnosed[store] = future.result()
                except Exception as exc:
                    diagnosed[store] = {
                        "store": store,
                        "status": "error",
                        "error": f"diagnostic worker: {type(exc).__name__}: {exc}",
                    }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        total = round(time.monotonic() - diagnostic_started, 3)
        ordered = {store: diagnosed.get(store, {"store": store, "status": "missing"}) for store in self.stores}

        return {
            "ok": True,
            "diagnostic_type": "store_stage_forensics_v2",
            "query": self.analyze_query(text),
            "production_limits": {
                "store_timeout_seconds": self.store_timeout,
                "global_timeout_seconds": self.global_timeout,
                "diagnostic_attempt_deadline_seconds": self.store_timeout + 2.0,
            },
            "total_diagnostic_seconds": total,
            "stores": ordered,
            "interpretation": {
                "search_call_bottleneck": [
                    name for name, info in ordered.items()
                    if any(
                        isinstance(attempt, dict)
                        and (
                            float(attempt.get("search_call_seconds") or 0.0) >= 5.0
                            or attempt.get("search_call_status") == "timeout"
                        )
                        for attempt in info.get("attempts", [])
                    )
                ],
                "postprocess_bottleneck": [
                    name for name, info in ordered.items()
                    if float(info.get("postprocess_seconds") or 0.0) >= 1.0
                ],
                "module_load_bottleneck": [
                    name for name, info in ordered.items()
                    if float(info.get("module_load_seconds") or 0.0) >= 1.0
                ],
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

    def run_job(self, job_id: str, query: str) -> None:
        """Execute all stores concurrently and publish each completed store immediately."""
        jobs = getattr(self.legacy, "SEARCH_JOBS", None)
        lock = getattr(self.legacy, "SEARCH_JOBS_LOCK", None)

        if jobs is None:
            legacy_runner = getattr(self.legacy, "_run_search_job_legacy", None)
            if legacy_runner is not None:
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
        executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

        try:
            store_status: Dict[str, Any] = {
                store: {"status": "searching", "count": 0}
                for store in self.stores
            }
            errors: Dict[str, str] = {}

            update({
                "status": "searching",
                "phase": "discovery",
                "completed": False,
                "results": [],
                "errors": {},
                "store_status": dict(store_status),
                "completed_stores": 0,
                "total_stores": len(self.stores),
                "raw_candidate_count": 0,
                "elapsed": 0.0,
            })

            # IMPORTANT: submit every store before waiting for any result.
            # A slow store therefore cannot serialize the search or delay the
            # first completed store from being published.
            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, len(self.stores)),
                thread_name_prefix="scenthunter-store",
            )
            futures = {
                executor.submit(self._run_one_store, store, query): store
                for store in self.stores
            }
            submitted_at = {future: time.monotonic() for future in futures}
            pending = set(futures)
            raw_pool: List[Dict[str, Any]] = []
            validated_pool: List[Dict[str, Any]] = []
            deadline = started + self.global_timeout

            while pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break

                # FIRST_COMPLETED is the key: never wait for all stores before
                # entering the publication path.
                done, _ = concurrent.futures.wait(
                    pending,
                    timeout=min(0.10, remaining),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                now = time.monotonic()

                # Catch futures that completed while wait() was returning.
                done.update(f for f in pending if f.done())

                for future in list(done):
                    if future not in pending:
                        continue

                    pending.remove(future)
                    store = futures[future]

                    try:
                        result = future.result()
                        new_candidates = [
                            item for item in (result.candidates or [])
                            if isinstance(item, dict)
                        ]
                        if new_candidates:
                            raw_pool.extend(new_candidates)
                            raw_pool = self._dedupe_raw(raw_pool)

                            # Validate only the newly arrived store evidence.
                            # Re-validating the whole accumulated pool on every
                            # completion was unnecessary work and delayed the
                            # first visible result as the pool grew.
                            newly_validated = self._validate_candidates_only(
                                query,
                                self._dedupe_raw(new_candidates),
                            )
                            if newly_validated:
                                validated_pool.extend(newly_validated)

                        store_status[store] = {
                            "status": result.status,
                            "count": len(result.candidates),
                            "elapsed": round(result.elapsed, 3),
                        }
                        if result.error:
                            store_status[store]["error"] = result.error
                            errors[store] = result.error

                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        store_status[store] = {
                            "status": "error",
                            "count": 0,
                            "elapsed": round(now - submitted_at[future], 3),
                            "error": error,
                        }
                        errors[store] = error

                    # CRITICAL LATENCY PATH:
                    # publish the current canonical/grouped result immediately
                    # after this store finishes. No final global wait.
                    try:
                        progressive_results = self._publish_validated_results(
                            query,
                            validated_pool,
                        )
                    except Exception as exc:
                        # A formatting/finalization error must not kill the
                        # search. The already validated candidates remain usable.
                        progressive_results = list(validated_pool)
                        errors.setdefault(
                            "_orchestration",
                            f"{type(exc).__name__}: {exc}",
                        )

                    update({
                        "status": "searching",
                        "phase": "discovery",
                        "completed": False,
                        "results": progressive_results,
                        "errors": dict(errors),
                        "store_status": dict(store_status),
                        "completed_stores": len(self.stores) - len(pending),
                        "total_stores": len(self.stores),
                        "raw_candidate_count": len(raw_pool),
                        "elapsed": round(time.monotonic() - started, 3),
                    })

                if not pending:
                    break

                # Mark only stores that actually exceeded their own deadline.
                now = time.monotonic()
                for future in list(pending):
                    if now - submitted_at[future] >= self.store_timeout:
                        pending.remove(future)
                        store = futures[future]
                        error = f"store exceeded independent timeout ({self.store_timeout:.0f}s)"
                        store_status[store] = {
                            "status": "timeout",
                            "count": 0,
                            "elapsed": round(now - submitted_at[future], 3),
                            "error": error,
                        }
                        errors[store] = error

                        # Publish the timeout state too, so the frontend sees
                        # that this store is no longer blocking the search.
                        update({
                            "status": "searching",
                            "phase": "discovery",
                            "completed": False,
                            "results": self._publish_validated_results(query, validated_pool),
                            "errors": dict(errors),
                            "store_status": dict(store_status),
                            "completed_stores": len(self.stores) - len(pending),
                            "total_stores": len(self.stores),
                            "raw_candidate_count": len(raw_pool),
                            "elapsed": round(time.monotonic() - started, 3),
                        })

            # The global window is over: remaining stores are no longer part of
            # this request's result set. Their worker threads are cancelled when
            # possible; running Python calls are left to finish outside the job.
            if pending:
                for future in pending:
                    store = futures[future]
                    store_status[store] = {
                        "status": "timeout",
                        "count": 0,
                        "elapsed": round(time.monotonic() - submitted_at[future], 3),
                        "error": "global search window expired",
                    }
                    errors[store] = "global search window expired"
                    future.cancel()
                pending.clear()

            final_results = self._finalize(query, raw_pool)

            update({
                "status": "completed",
                "phase": "completed",
                "completed": True,
                "results": final_results,
                "errors": dict(errors),
                "store_status": dict(store_status),
                "completed_stores": len(self.stores),
                "total_stores": len(self.stores),
                "raw_candidate_count": len(raw_pool),
                "elapsed": round(time.monotonic() - started, 3),
            })

        except Exception as exc:
            update({
                "status": "error",
                "phase": "completed",
                "completed": True,
                "results": [],
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
                "elapsed": round(time.monotonic() - started, 3),
            })
        finally:
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
