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
import copy
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


DEFAULT_STORE_TIMEOUT = 35.0
DEFAULT_GLOBAL_TIMEOUT = 80.0
RETRY_STORE_TIMEOUT = 30.0
RETRY_GLOBAL_BUDGET = 38.0


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

    def _run_store_wave(
        self,
        stores: List[str],
        query: str,
        timeout: float,
        global_budget: float,
    ) -> Dict[str, StoreRun]:
        """Run one independent parallel wave of store adapters.

        A wave never waits for one slow shop before collecting the others.
        Timed-out futures are detached; their late result is deliberately
        ignored by the wave.
        """
        if not stores:
            return {}

        started = time.monotonic()
        results: Dict[str, StoreRun] = {
            store: StoreRun(store=store) for store in stores
        }

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, len(stores)),
            thread_name_prefix="scenthunter-store",
        )
        futures: Dict[concurrent.futures.Future, str] = {}
        submitted_at: Dict[concurrent.futures.Future, float] = {}

        for store in stores:
            future = executor.submit(self._run_one_store, store, query)
            futures[future] = store
            submitted_at[future] = time.monotonic()

        pending = set(futures)
        deadline = started + min(float(timeout), float(global_budget))

        try:
            while pending and time.monotonic() < deadline:
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

                now = time.monotonic()
                for future in list(pending):
                    store = futures[future]
                    if now - submitted_at[future] >= float(timeout):
                        pending.remove(future)
                        results[store] = StoreRun(
                            store=store,
                            status="timeout",
                            candidates=[],
                            elapsed=now - submitted_at[future],
                            error=f"store exceeded independent timeout ({timeout:.0f}s)",
                        )

                if not pending:
                    break

                remaining = deadline - time.monotonic()
                time.sleep(min(0.20, max(0.0, remaining)))

            if pending:
                now = time.monotonic()
                for future in pending:
                    store = futures[future]
                    results[store] = StoreRun(
                        store=store,
                        status="timeout",
                        candidates=[],
                        elapsed=now - submitted_at[future],
                        error="store wave budget expired",
                    )
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

        return results

    def _run_stores(self, query: str) -> Dict[str, Any]:
        """
        Execute the eight stores in parallel, then retry only inconclusive
        stores in a second independent wave.

        The important distinction is that an empty/error/timeout result from
        one shop is *not* treated as proof that the product is absent there.
        This is what prevents intermittent scraper misses from becoming
        intermittent missing shops in the final answer.

        No result is published during either wave.  The caller receives the
        complete combined candidate pool only after both waves finish.
        """
        started = time.monotonic()

        first_wave_budget = min(
            self.store_timeout,
            45.0,
            self.global_timeout,
        )
        first = self._run_store_wave(
            self.stores,
            query,
            timeout=first_wave_budget,
            global_budget=first_wave_budget,
        )

        # A scraper returning no candidates is inconclusive.  Retry it even
        # when main_legacy.run_store swallowed an underlying HTTP exception.
        retry_stores = [
            store
            for store in self.stores
            if first.get(store, StoreRun(store=store)).status
            in {"empty", "error", "timeout"}
        ]

        remaining = max(0.0, self.global_timeout - (time.monotonic() - started))
        second: Dict[str, StoreRun] = {}
        if retry_stores and remaining > 2.0:
            retry_budget = min(
                RETRY_GLOBAL_BUDGET,
                remaining,
            )
            retry_timeout = min(
                RETRY_STORE_TIMEOUT,
                retry_budget,
            )
            second = self._run_store_wave(
                retry_stores,
                query,
                timeout=retry_timeout,
                global_budget=retry_budget,
            )

        # Keep the best outcome per store.  A successful retry replaces an
        # empty/error first attempt.  If both attempts have candidates, merge
        # them losslessly so a second discovery path can contribute another
        # size/shop offer.
        combined: Dict[str, StoreRun] = {}
        for store in self.stores:
            first_result = first.get(store, StoreRun(store=store))
            retry_result = second.get(store)

            if retry_result is None:
                combined[store] = first_result
                continue

            candidates = list(first_result.candidates) + list(retry_result.candidates)
            if candidates:
                combined[store] = StoreRun(
                    store=store,
                    status="ok",
                    candidates=candidates,
                    elapsed=max(first_result.elapsed, retry_result.elapsed),
                    error=None,
                )
            elif retry_result.status == "timeout" and first_result.status == "empty":
                combined[store] = first_result
            else:
                combined[store] = retry_result

        return {
            "stores": combined,
            "elapsed": time.monotonic() - started,
            "retried_stores": retry_stores,
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
            # Detach the final object from legacy/matcher nested structures.
            item = copy.deepcopy(result)
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

                    # Rebuild the representative from the winning offer.
                    # The legacy grouper may leave top-level metadata (source,
                    # identity, raw_data, etc.) originating from a different
                    # merchant than the top-level store/price/url.  That creates
                    # mixed objects such as "store=Bplatz" with "source=Deloox".
                    #
                    # Keep the group-level fields that belong to the canonical
                    # product, but replace every merchant-owned field with a
                    # deep copy from the actual best offer.
                    merchant_fields = {
                        "store", "shop", "price", "price_num", "url", "image",
                        "image_url", "thumbnail", "availability", "available",
                        "stock_status", "stock", "size_ml", "size",
                        "concentration", "gender", "source", "identity",
                        "raw_data", "sku", "gtin", "product_id", "variant_id",
                        "offer", "offer_data", "merchant", "merchant_data",
                    }

                    for field in merchant_fields:
                        if field in best:
                            item[field] = copy.deepcopy(best[field])
                        else:
                            # A merchant field left behind by the legacy
                            # representative is unsafe: it may belong to the
                            # previous representative rather than the winner.
                            item.pop(field, None)

                    # The nested offers are the authoritative merchant list.
                    # Store them independently so later mutations cannot
                    # cross-contaminate the representative or another group.
                    item["offers"] = [copy.deepcopy(x) for x in offers]

            output.append(item)

        def result_key(item: Dict[str, Any]) -> tuple:
            nested = item.get("offers")
            best = nested[0] if isinstance(nested, list) and nested else item
            return offer_key(best if isinstance(best, dict) else item)

        return [copy.deepcopy(x) for x in sorted(output, key=result_key)]

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

        return {
            "query": text,
            "count": len(final_results),
            "results": final_results,
            "comparisons": [],
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Async job API used by existing /search-start + /search-status routes
    # ------------------------------------------------------------------

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
