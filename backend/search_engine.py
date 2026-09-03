"""
ScentHunter - robust live search orchestration.

This module deliberately sits ABOVE the existing store scrapers.  It does not
try to make the eight shops scrape the same way: each scraper remains a store
adapter.  The uniformity is enforced here, at orchestration / result level.

Goals:
- query all stores in parallel;
- keep each store independent;
- distinguish empty results from technical failures;
- do not publish a partial product list;
- keep the raw candidate pool lossless at the orchestration boundary;
- reuse the current central matcher / validation / final-result preparation;
- keep final availability ordering: in_stock, unknown, out_of_stock;
- avoid changing the frontend or Railway contract.
"""

from __future__ import annotations

import concurrent.futures
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


DEFAULT_STORE_TIMEOUT = 40.0
DEFAULT_GLOBAL_TIMEOUT = 45.0


@dataclass
class StoreRun:
    store: str
    status: str = "error"  # ok | empty | timeout | error
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    elapsed: float = 0.0
    error: Optional[str] = None


class SearchEngine:
    """
    Adapter/orchestrator around the current main.py implementation.

    The legacy module is intentionally injected instead of imported by name so
    the existing matcher, catalog, registry and store adapters stay untouched.
    """

    def __init__(
        self,
        legacy_module: Any,
        *,
        store_timeout: float = DEFAULT_STORE_TIMEOUT,
        global_timeout: float = DEFAULT_GLOBAL_TIMEOUT,
    ) -> None:
        self.legacy = legacy_module
        self.store_timeout = float(store_timeout)
        self.global_timeout = float(global_timeout)

        stores = getattr(legacy_module, "STORES", None)
        if stores:
            self.stores = list(stores)
        else:
            self.stores = [
                "bplatz",
                "deloox",
                "parfumcity",
                "parfumzentrum",
                "perfumemarket",
                "sabina",
                "orioudh",
                "notino",
            ]

    # ------------------------------------------------------------------
    # Query analysis
    # ------------------------------------------------------------------

    def analyze_query(self, query: str) -> Dict[str, Any]:
        raw = (query or "").strip()
        norm = self.legacy.norm(raw) if hasattr(self.legacy, "norm") else raw.lower()

        size_ml = None
        try:
            # Reuse the same size syntax already used by main.py.
            m = self.legacy.re.search(
                r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:ml|milliliters?)\b",
                raw,
                self.legacy.re.I,
            )
            if m:
                size_ml = float(m.group(1).replace(",", "."))
        except Exception:
            size_ml = None

        return {
            "raw": raw,
            "normalized": norm,
            "size_ml": size_ml,
        }

    # ------------------------------------------------------------------
    # Store execution
    # ------------------------------------------------------------------

    def _run_one_store(self, store: str, query: str) -> StoreRun:
        started = time.monotonic()

        try:
            # run_store is the existing store adapter boundary in main.py.
            runner = getattr(self.legacy, "run_store", None)
            if runner is None:
                raise RuntimeError("main.run_store is not available")

            raw = runner(store, query)

            if raw is None:
                candidates: List[Dict[str, Any]] = []
            elif isinstance(raw, list):
                candidates = raw
            else:
                # Be tolerant of adapters returning an iterable.
                try:
                    candidates = list(raw)
                except Exception:
                    candidates = []

            # IMPORTANT:
            # No deduplication, identity filtering, availability filtering or
            # ranking happens here.  The central validation layer receives the
            # complete adapter output.
            clean_candidates = [
                item for item in candidates if isinstance(item, dict)
            ]

            return StoreRun(
                store=store,
                status="ok" if clean_candidates else "empty",
                candidates=clean_candidates,
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
        """
        Execute all store adapters concurrently with two independent limits:

        - every store has its own STORE_TIMEOUT budget;
        - the whole research phase has a GLOBAL_TIMEOUT ceiling.

        A timed-out Python thread cannot be force-killed safely.  The future is
        therefore detached from the result set and the executor is shut down
        without waiting.  A late adapter completion is ignored.
        """
        started = time.monotonic()
        results: Dict[str, StoreRun] = {
            store: StoreRun(store=store) for store in self.stores
        }

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, len(self.stores)),
            thread_name_prefix="scenthunter-store",
        )

        futures: Dict[concurrent.futures.Future, str] = {}
        submitted_at: Dict[concurrent.futures.Future, float] = {}

        for store in self.stores:
            future = executor.submit(self._run_one_store, store, query)
            futures[future] = store
            submitted_at[future] = time.monotonic()

        pending = set(futures)
        deadline = started + self.global_timeout

        try:
            while pending and time.monotonic() < deadline:
                now = time.monotonic()

                # Harvest every future that has already completed.
                done = {future for future in pending if future.done()}
                for future in done:
                    pending.remove(future)
                    store = futures[future]
                    try:
                        results[store] = future.result()
                    except Exception as exc:
                        results[store] = StoreRun(
                            store=store,
                            status="error",
                            candidates=[],
                            elapsed=time.monotonic() - submitted_at[future],
                            error=f"{type(exc).__name__}: {exc}",
                        )

                if not pending:
                    break

                # Enforce the per-store timeout independently.
                now = time.monotonic()
                for future in list(pending):
                    store = futures[future]
                    if now - submitted_at[future] >= self.store_timeout:
                        pending.remove(future)
                        results[store] = StoreRun(
                            store=store,
                            status="timeout",
                            candidates=[],
                            elapsed=now - submitted_at[future],
                            error=(
                                f"store exceeded independent timeout "
                                f"({self.store_timeout:.0f}s)"
                            ),
                        )

                if not pending:
                    break

                # Short polling interval keeps timeout enforcement precise
                # without busy-spinning the process.
                remaining_global = deadline - time.monotonic()
                time.sleep(min(0.20, max(0.0, remaining_global)))

            # Anything still pending at the global deadline is a timeout.
            if pending:
                now = time.monotonic()
                for future in pending:
                    store = futures[future]
                    results[store] = StoreRun(
                        store=store,
                        status="timeout",
                        candidates=[],
                        elapsed=now - submitted_at[future],
                        error="global search window expired",
                    )

        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return {
            "stores": results,
            "elapsed": time.monotonic() - started,
        }

    # ------------------------------------------------------------------
    # Central validation / grouping / ranking
    # ------------------------------------------------------------------

    @staticmethod
    def _availability_rank(item: Dict[str, Any]) -> int:
        value = str(
            item.get("availability")
            or item.get("stock_status")
            or item.get("stock")
            or ""
        ).strip().lower()

        if value in {
            "in_stock",
            "available",
            "true",
            "1",
            "yes",
            "in stock",
        }:
            return 0

        if value in {
            "out_of_stock",
            "oos",
            "unavailable",
            "sold_out",
            "sold out",
            "false",
            "0",
        }:
            return 2

        return 1

    def _stable_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deterministic final ordering, including nested merchant offers."""

        def availability_rank(item: Dict[str, Any]) -> int:
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
            return 1

        def price_value(item: Dict[str, Any]) -> float:
            try:
                value = item.get("price")
                if value is None:
                    value = item.get("price_num")
                return float(value)
            except Exception:
                return float("inf")

        def offer_key(item: Dict[str, Any]) -> tuple:
            return (
                availability_rank(item),
                price_value(item),
                str(item.get("store") or item.get("shop") or ""),
                str(item.get("url") or ""),
                str(item.get("title") or item.get("name") or ""),
            )

        output: List[Dict[str, Any]] = []

        for result in results:
            item = dict(result)
            nested = item.get("offers")

            if isinstance(nested, list) and nested:
                offers = [dict(x) for x in nested if isinstance(x, dict)]
                offers.sort(key=offer_key)
                item["offers"] = offers
                item["offer_count"] = len(offers)
                item["stores"] = list(dict.fromkeys(
                    str(x.get("store") or x.get("shop") or "").strip()
                    for x in offers
                    if str(x.get("store") or x.get("shop") or "").strip()
                ))

                # The top-level representative must be the best AVAILABLE
                # offer, not merely the cheapest OOS offer.
                if offers:
                    best = offers[0]
                    for field in ("store", "price", "url", "image", "availability", "available", "size_ml", "concentration", "gender"):
                        if field in best:
                            item[field] = best[field]

            output.append(item)

        def result_key(item: Dict[str, Any]) -> tuple:
            nested = item.get("offers")
            best = nested[0] if isinstance(nested, list) and nested else item
            return offer_key(best if isinstance(best, dict) else item)

        return sorted(output, key=result_key)

    def _validate_candidates_only(
        self,
        query: str,
        raw_candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Run central validation without grouping/preparing the final UI object."""
        pre_rank = getattr(self.legacy, "_pre_rank_candidates", None)
        validate = getattr(self.legacy, "_validate_candidates_parallel", None)

        candidates = list(raw_candidates)
        if pre_rank is not None:
            try:
                candidates = pre_rank(candidates, query)
            except TypeError:
                candidates = pre_rank(candidates)

        if validate is not None:
            try:
                candidates = validate(candidates, query)
            except TypeError:
                candidates = validate(candidates)

        if candidates is None:
            return []
        if not isinstance(candidates, list):
            candidates = list(candidates)
        return [item for item in candidates if isinstance(item, dict)]

    def _validate_and_finalize(
        self,
        query: str,
        raw_candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Reuse the current central validation and finalization functions.

        This is intentionally not duplicated here.  The current matcher,
        family registry, canonical catalog and scraper-specific parsing remain
        the source of truth until those components are independently replaced.
        """

        pre_rank = getattr(self.legacy, "_pre_rank_candidates", None)
        validate = getattr(self.legacy, "_validate_candidates_parallel", None)
        prepare = getattr(self.legacy, "_prepare_final_results", None)

        candidates = list(raw_candidates)

        if pre_rank is not None:
            try:
                candidates = pre_rank(candidates, query)
            except TypeError:
                candidates = pre_rank(candidates)

        if validate is not None:
            try:
                candidates = validate(candidates, query)
            except TypeError:
                candidates = validate(candidates)

        if prepare is not None:
            try:
                final = prepare(candidates, query)
            except TypeError:
                final = prepare(candidates)
        else:
            final = candidates

        if final is None:
            final = []

        if not isinstance(final, list):
            final = list(final)

        return self._stable_results(
            [item for item in final if isinstance(item, dict)]
        )

    # ------------------------------------------------------------------
    # Public synchronous API
    # ------------------------------------------------------------------

    def search(self, query: str) -> Dict[str, Any]:
        analysis = self.analyze_query(query)
        text = analysis["raw"]

        if not text:
            return {
                "query": "",
                "count": 0,
                "results": [],
                "comparisons": [],
                "errors": {},
            }

        store_run = self._run_stores(text)

        raw_pool: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}
        for store in self.stores:
            result = store_run["stores"][store]
            raw_pool.extend(result.candidates)
            if result.error:
                errors[store] = result.error

        final_results = self._validate_and_finalize(text, raw_pool)

        # The central finalizer already returns one canonical product group per
        # result, including its complete retailer-level ``offers`` list.
        # Publish those groups in ``comparisons`` for the frontend, while
        # keeping ``results`` as the flat retailer-offer list for compatibility.
        grouped_results = [dict(item) for item in final_results if isinstance(item, dict)]
        flat_results: List[Dict[str, Any]] = []
        for group in grouped_results:
            offers = group.get("offers")
            if isinstance(offers, list) and offers:
                flat_results.extend(
                    dict(offer)
                    for offer in offers
                    if isinstance(offer, dict)
                )
            else:
                flat_results.append(dict(group))

        flat_results = self._stable_offers(flat_results)

        return {
            "query": text,
            "count": len(grouped_results),
            "offer_count": len(flat_results),
            "results": flat_results,
            "comparisons": grouped_results,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Async job API used by existing /search-start + /search-status routes
    # ------------------------------------------------------------------

    def search_job_snapshot(self, job_id: str) -> Dict[str, Any]:
        jobs = getattr(self.legacy, "SEARCH_JOBS", None)
        lock = getattr(self.legacy, "SEARCH_JOBS_LOCK", None)
        if jobs is None:
            raise RuntimeError("SEARCH_JOBS is not available")

        def read_job() -> Dict[str, Any]:
            job = jobs.get(job_id)
            if job is None:
                raise self.legacy.HTTPException(status_code=404, detail="Job di ricerca non trovato")
            return dict(job)

        if lock is not None:
            with lock:
                job = read_job()
        else:
            job = read_job()

        prepared = self._validate_and_finalize(
            job.get("query", ""),
            list(job.get("results") or []),
        )
        grouped_results = [dict(item) for item in prepared if isinstance(item, dict)]
        flat_results: List[Dict[str, Any]] = []
        for group in grouped_results:
            offers = group.get("offers")
            if isinstance(offers, list) and offers:
                flat_results.extend(
                    dict(offer)
                    for offer in offers
                    if isinstance(offer, dict)
                )
            else:
                flat_results.append(dict(group))

        flat_results = self._stable_offers(flat_results)

        return {
            "job_id": job_id,
            "query": job.get("query", ""),
            "count": len(grouped_results),
            "offer_count": len(flat_results),
            "results": flat_results,
            "comparisons": grouped_results,
            "errors": dict(job.get("errors") or {}),
            "completed": bool(job.get("completed")),
            "status": "completed" if job.get("completed") else "searching",
        }

    def run_job(self, job_id: str, query: str) -> None:
        """
        Drop-in replacement for the existing background search job.

        Critical behavior:
        - technical store progress may be recorded;
        - product results are NOT published progressively;
        - final results are written exactly once after all stores finish or the
          global search window expires.
        """
        jobs = getattr(self.legacy, "SEARCH_JOBS", None)
        lock = getattr(self.legacy, "SEARCH_JOBS_LOCK", None)

        if jobs is None:
            # Fall back to the legacy implementation if the job registry is
            # unavailable rather than crashing application startup.
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

        try:
            update(
                {
                    "status": "searching",
                    "results": [],
                    "store_status": {
                        store: {"status": "searching", "count": 0}
                        for store in self.stores
                    },
                }
            )

            started = time.monotonic()
            run = self._run_stores(query)

            raw_pool: List[Dict[str, Any]] = []
            store_status: Dict[str, Any] = {}

            for store in self.stores:
                result = run["stores"][store]
                raw_pool.extend(result.candidates)
                store_status[store] = {
                    "status": result.status,
                    "count": len(result.candidates),
                    "elapsed": round(result.elapsed, 3),
                    "error": result.error,
                }

            # Validate centrally, but keep the validated candidate objects in
            # the job. The legacy /search-status snapshot calls
            # _prepare_final_results() exactly once; storing already-prepared
            # groups here would make that route prepare the same result twice.
            validated_candidates = self._validate_candidates_only(query, raw_pool)

            # IMPORTANT: this is the first publication of the product list.
            update(
                {
                    "status": "completed",
                    "results": validated_candidates,
                    "store_status": store_status,
                    "elapsed": round(time.monotonic() - started, 3),
                    "raw_candidate_count": len(raw_pool),
                    "phase": "completed",
                    "completed": True,
                }
            )

        except Exception as exc:
            update(
                {
                    "status": "error",
                    "results": [],
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(limit=8),
                }
            )
