"""ScentHunter search orchestration v2.

The live search layer is deliberately boring:
- one request to each of the eight store adapters;
- all stores start independently;
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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_STORE_TIMEOUT = 45.0
DEFAULT_GLOBAL_TIMEOUT = 60.0


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
            # Main legacy owns retailer-specific query expansion through
            # build_search_attempts(). Do not rewrite the user's query here:
            # adding the catalog brand centrally can break retailer search
            # endpoints that already expect the exact product phrase.
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

    def _catalog_variant_formats(self, product: Dict[str, Any], query: str) -> List[float]:
        """Return only formats explicitly verified for a resolved catalog variant.

        Size is an offer attribute, not product identity.  We only use a
        catalog format list as a consistency guard when the candidate itself
        exposes an explicit size.  No size is ever inferred from price/name
        absence, and uncatalogued products are left untouched.
        """
        family_fn = getattr(self.legacy, "_catalog_family_for_query", None)
        variant_fn = getattr(self.legacy, "_catalog_variant_for_product", None)
        if not callable(family_fn) or not callable(variant_fn):
            return []

        try:
            family = family_fn(query)
        except Exception:
            return []
        if not isinstance(family, dict):
            return []

        try:
            variant = variant_fn(product, family)
        except Exception:
            return []
        if not isinstance(variant, dict):
            return []

        values = []
        for raw in variant.get("formats_ml") or []:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in values:
                values.append(value)
        return sorted(values)

    def _enforce_catalog_format_integrity(
        self, query: str, products: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Reject only explicit wrong-size offers for single/multi-format variants.

        The rule is generic: if the authoritative catalog says a resolved
        variant has verified formats, an offer with an explicit size must be
        one of those formats. Offers with no explicit size are not relabelled
        and remain eligible for normal validation.
        """
        size_fn = getattr(self.legacy, "product_size_ml", None)
        if not callable(size_fn):
            def size_fn(item):
                for key in ("size_ml", "volume_ml", "format_ml"):
                    value = item.get(key)
                    if value not in (None, ""):
                        try:
                            return float(value)
                        except (TypeError, ValueError):
                            pass
                return None

        output: List[Dict[str, Any]] = []
        for product in products:
            if not isinstance(product, dict):
                continue
            formats = self._catalog_variant_formats(product, query)
            if not formats:
                output.append(product)
                continue
            try:
                explicit_size = size_fn(product)
            except Exception:
                explicit_size = None
            if explicit_size is None:
                output.append(product)
                continue
            if any(abs(float(explicit_size) - value) < 0.01 for value in formats):
                output.append(product)
        return output

    def _enrich_result_formats(
        self, query: str, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Expose verified/observed ml formats without inventing any size."""
        size_fn = getattr(self.legacy, "product_size_ml", None)

        def observed_sizes(item: Dict[str, Any]) -> List[float]:
            offers = item.get("offers") if isinstance(item.get("offers"), list) else []
            source = offers or [item]
            values = []
            for offer in source:
                if not isinstance(offer, dict):
                    continue
                try:
                    value = size_fn(offer) if callable(size_fn) else None
                except Exception:
                    value = None
                if value is None:
                    for key in ("size_ml", "volume_ml", "format_ml"):
                        raw = offer.get(key)
                        if raw not in (None, ""):
                            try:
                                value = float(raw)
                            except (TypeError, ValueError):
                                value = None
                            break
                if value is not None and value > 0 and value not in values:
                    values.append(float(value))
            return values

        enriched = []
        for result in results:
            item = dict(result)
            values = observed_sizes(item)
            catalog_formats = self._catalog_variant_formats(item, query)
            for value in catalog_formats:
                if value not in values:
                    values.append(value)
            if values:
                item["formats_ml"] = sorted(values)
            enriched.append(item)
        return enriched

    def _finalize(self, query: str, raw_pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        validated = self._validate_candidates_only(query, raw_pool)
        validated = self._enforce_catalog_format_integrity(query, validated)
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
        stable = self._stable_results([x for x in final if isinstance(x, dict)])
        return self._enrich_result_formats(query, stable)

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
        text = self.analyze_query(query)["raw"]
        if not text:
            return {"ok": True, "query": "", "stores": {}, "raw_candidates": [], "validated_candidates": [], "errors": {}}
        started = time.monotonic()
        store_run = self._run_stores(text)
        raw_pool: List[Dict[str, Any]] = []
        stores: Dict[str, Any] = {}
        errors: Dict[str, str] = {}
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
        raw_pool = self._dedupe_raw(raw_pool)
        validated = self._validate_candidates_only(text, raw_pool)
        return {
            "ok": True,
            "query": text,
            "elapsed": round(time.monotonic() - started, 3),
            "store_count": len(self.stores),
            "stores": stores,
            "raw_candidate_count": len(raw_pool),
            "validated_candidate_count": len(validated),
            "raw_candidates": [dict(x) for x in raw_pool],
            "validated_candidates": [dict(x) for x in validated],
            "errors": errors,
        }

    def run_job(self, job_id: str, query: str) -> None:
        """Run one progressive search job with isolated store deadlines.

        A retailer can be slow or blocked without holding the other retailers
        hostage.  Once a store reaches ``store_timeout`` it is marked as
        timed out and removed from the job's pending set.  The underlying
        Python thread cannot be force-killed safely, so the executor is always
        shut down without waiting; late results from an already timed-out
        store are deliberately ignored.
        """
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
            "elapsed": 0.0,
        })

        executor = None
        try:
            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=len(self.stores),
                thread_name_prefix="scenthunter-store",
            )
            futures = {
                executor.submit(self._run_one_store, store, query): store
                for store in self.stores
            }
            future_started = {
                future: time.monotonic()
                for future in futures
            }
            pending = set(futures)
            raw_pool: List[Dict[str, Any]] = []
            errors: Dict[str, str] = {}
            deadline = started + self.global_timeout

            def publish() -> None:
                current_pool = self._dedupe_raw(list(raw_pool))
                # Publish the same progressive behavior as the original
                # SearchEngine: as soon as ANY store finishes, expose the
                # validated/merged results already available. Never wait for
                # the slowest retailer before showing the first products.
                partial = self._finalize(query, current_pool) if current_pool else []
                completed_stores = sum(
                    1
                    for value in store_status.values()
                    if value.get("status") not in {"pending", "searching"}
                )
                update({
                    "completed": False,
                    "phase": "collecting",
                    "status": "searching",
                    "results": partial,
                    "candidates": list(current_pool),
                    "errors": dict(errors),
                    "store_status": dict(store_status),
                    "completed_stores": completed_stores,
                    "total_stores": len(self.stores),
                    "result_count": len(partial),
                    "elapsed": round(time.monotonic() - started, 3),
                })

            while pending:
                now = time.monotonic()
                if now >= deadline:
                    break

                wait_timeout = min(
                    0.10,
                    max(0.01, deadline - now),
                )
                done, _ = concurrent.futures.wait(
                    pending,
                    timeout=wait_timeout,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                changed = False

                for future in done:
                    if future not in pending:
                        continue

                    pending.remove(future)
                    store = futures[future]

                    try:
                        result = future.result()
                    except Exception as exc:
                        result = StoreRun(
                            store=store,
                            status="error",
                            candidates=[],
                            elapsed=time.monotonic() - future_started[future],
                            error=f"{type(exc).__name__}: {exc}",
                        )

                    store_status[store] = {
                        "status": result.status,
                        "count": len(result.candidates),
                        "elapsed": round(result.elapsed, 3),
                        "error": result.error,
                    }
                    raw_pool.extend(result.candidates)

                    if result.error:
                        errors[store] = result.error

                    changed = True

                now = time.monotonic()

                # Enforce the per-store deadline independently of the global
                # search deadline.  This is the key isolation mechanism.
                for future in list(pending):
                    elapsed = now - future_started[future]
                    if elapsed >= self.store_timeout:
                        pending.remove(future)
                        store = futures[future]
                        message = f"store timeout ({self.store_timeout:.0f}s)"
                        store_status[store] = {
                            "status": "timeout",
                            "count": 0,
                            "elapsed": round(elapsed, 3),
                            "error": message,
                        }
                        errors[store] = message
                        future.cancel()
                        changed = True

                if changed:
                    publish()

            if pending:
                now = time.monotonic()
                for future in list(pending):
                    pending.remove(future)
                    store = futures[future]
                    elapsed = now - future_started[future]
                    message = (
                        f"global search window expired "
                        f"({self.global_timeout:.0f}s)"
                    )
                    store_status[store] = {
                        "status": "timeout",
                        "count": 0,
                        "elapsed": round(elapsed, 3),
                        "error": message,
                    }
                    errors[store] = message
                    future.cancel()

                publish()

            raw_pool = self._dedupe_raw(raw_pool)
            final = self._finalize(query, raw_pool)

            update({
                "results": final,
                "candidates": list(raw_pool),
                "errors": dict(errors),
                "store_status": dict(store_status),
                "phase": "completed",
                "status": "completed",
                "completed": True,
                "elapsed": round(time.monotonic() - started, 3),
                "raw_candidate_count": len(raw_pool),
                "result_count": len(final),
                "completed_stores": sum(
                    1
                    for value in store_status.values()
                    if value.get("status") not in {"pending", "searching"}
                ),
                "total_stores": len(self.stores),
            })
        except Exception as exc:
            update({
                "results": [],
                "candidates": [],
                "errors": {
                    "_search": f"{type(exc).__name__}: {exc}"
                },
                "status": "error",
                "completed": True,
                "phase": "error",
                "elapsed": round(time.monotonic() - started, 3),
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
            })
        finally:
            if executor is not None:
                executor.shutdown(
                    wait=False,
                    cancel_futures=True,
                )

