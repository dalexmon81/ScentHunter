"""
ScentHunter - search orchestration.

Important invariant:
once a store candidate has been accepted, a later wave is never allowed to
remove it. Store identity is part of the deduplication key, so two different
shops can never collapse into one offer merely because they have the same
product URL/name.
"""

from __future__ import annotations

import concurrent.futures
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_STORE_TIMEOUT = 65.0
DEFAULT_GLOBAL_TIMEOUT = 145.0
STORE_RETRIES = 2
RETRY_DELAYS = (1.25, 3.0)


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
    ) -> None:
        self.legacy = legacy_module
        self.store_timeout = float(store_timeout)
        self.global_timeout = float(global_timeout)

        stores = getattr(legacy_module, "STORES", None)
        self.stores = list(stores) if stores else [
            "bplatz",
            "deloox",
            "parfumcity",
            "parfumzentrum",
            "perfumemarket",
            "sabina",
            "orioudh",
            "notino",
        ]

    # ---------------------------------------------------------------
    # Basic helpers
    # ---------------------------------------------------------------

    def _norm(self, value: Any) -> str:
        fn = getattr(self.legacy, "norm", None)
        if callable(fn):
            try:
                return str(fn(str(value or ""))).strip().casefold()
            except Exception:
                pass
        return re.sub(r"\s+", " ", str(value or "").strip()).casefold()

    def _store_name(self, item: Dict[str, Any], fallback: str = "") -> str:
        return str(
            item.get("store")
            or item.get("shop")
            or item.get("source")
            or fallback
            or ""
        ).strip().casefold()

    def _size_ml(self, item: Dict[str, Any]) -> Optional[float]:
        fn = getattr(self.legacy, "product_size_ml", None)
        if callable(fn):
            try:
                value = fn(item)
                if value is not None:
                    return float(value)
            except Exception:
                pass

        values = []
        for key in (
            "size_ml", "volume_ml", "format_ml", "size", "format",
            "volume", "name", "title", "product_name", "canonical_name",
            "catalog_variant", "url",
        ):
            if item.get(key) not in (None, ""):
                values.append(str(item.get(key)))

        attrs = item.get("attributes")
        if isinstance(attrs, dict):
            value = attrs.get("size_ml")
            if isinstance(value, dict):
                value = value.get("value")
            if value not in (None, ""):
                values.append(str(value))

        text = " ".join(values)
        match = re.search(
            r"(?<!\d)(\d+(?:[.,]\d+)?)\s*[-_/]?\s*(ml|cl)\b",
            text,
            re.I,
        )
        if not match:
            return None

        try:
            number = float(match.group(1).replace(",", "."))
            return number * 10 if match.group(2).lower() == "cl" else number
        except Exception:
            return None

    def _candidate_key(self, item: Dict[str, Any], fallback_store: str = "") -> Tuple[str, ...]:
        """
        Store is deliberately the FIRST component.

        This is the critical protection against cross-store deduplication:
        Deloox and Bplatz can have identical names, URLs or canonical IDs and
        they must still remain two independent offers.
        """
        store = self._store_name(item, fallback_store)
        size = self._size_ml(item)
        size_key = f"{size:.4f}" if size is not None else ""

        product_id = str(
            item.get("product_id")
            or item.get("catalog_id")
            or item.get("gtin")
            or item.get("mpn")
            or ""
        ).strip().casefold()

        url = str(item.get("url") or "").strip().casefold()
        name = self._norm(
            item.get("canonical_name")
            or item.get("product_name")
            or item.get("title")
            or item.get("name")
            or ""
        )

        # Prefer the strongest identity available, but NEVER omit store.
        identity = product_id or url or name
        return (store, identity, size_key)

    def _merge_unique(
        self,
        destination: List[Dict[str, Any]],
        incoming: List[Dict[str, Any]],
        fallback_store: str = "",
    ) -> int:
        existing: Dict[Tuple[str, ...], int] = {}

        for index, item in enumerate(destination):
            if isinstance(item, dict):
                existing[self._candidate_key(item, fallback_store)] = index

        added = 0
        for item in incoming:
            if not isinstance(item, dict):
                continue

            key = self._candidate_key(item, fallback_store)
            old_index = existing.get(key)

            if old_index is None:
                destination.append(dict(item))
                existing[key] = len(destination) - 1
                added += 1
                continue

            # Merge useful fields without replacing a valid candidate with an
            # empty/partial later scrape response.
            current = destination[old_index]
            for field, value in item.items():
                if value in (None, "", [], {}):
                    continue
                if current.get(field) in (None, "", [], {}):
                    current[field] = value

        return added

    def _availability_rank(self, item: Dict[str, Any]) -> int:
        value = str(
            item.get("availability")
            or item.get("stock_status")
            or item.get("stock")
            or ""
        ).strip().casefold()

        if value in {
            "in_stock", "available", "true", "1", "yes", "in stock"
        }:
            return 0

        if value in {
            "unknown", "pending", "unconfirmed", ""
        }:
            return 1

        if value in {
            "out_of_stock", "oos", "unavailable", "sold_out",
            "sold out", "false", "0", "out of stock",
        }:
            return 2

        return 1

    def _price_value(self, item: Dict[str, Any]) -> float:
        value = item.get("price_num")
        if value is None:
            value = item.get("price_value")
        if value is None:
            value = item.get("price")

        if isinstance(value, str):
            value = re.sub(r"[^\d,.]", "", value).replace(",", ".")
        try:
            return float(value)
        except Exception:
            return float("inf")

    def _stable_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Final ordering only. This function does NOT validate, filter or dedupe.
        Therefore final sorting can never make a previously accepted store
        disappear.
        """
        output = [dict(x) for x in results if isinstance(x, dict)]

        for item in output:
            if isinstance(item.get("offers"), list):
                offers = [
                    dict(x) for x in item["offers"]
                    if isinstance(x, dict)
                ]
                offers.sort(
                    key=lambda x: (
                        self._availability_rank(x),
                        self._price_value(x),
                        self._store_name(x),
                        str(x.get("url") or ""),
                    )
                )
                item["offers"] = offers
                item["offer_count"] = len(offers)

        output.sort(
            key=lambda x: (
                self._availability_rank(x),
                self._price_value(x),
                self._store_name(x),
                str(x.get("url") or ""),
                str(x.get("title") or x.get("name") or ""),
            )
        )
        return output

    # ---------------------------------------------------------------
    # Query / discovery
    # ---------------------------------------------------------------

    def analyze_query(self, query: str) -> Dict[str, Any]:
        raw = str(query or "").strip()
        return {
            "raw": raw,
            "normalized": self._norm(raw),
            "size_ml": None,
        }

    def _query_flags(self, query: str) -> Dict[str, Any]:
        raw = str(query or "").strip()
        normalized = self._norm(raw)

        size_ml = None
        match = re.search(
            r"(?<!\d)(\d+(?:[.,]\d+)?)\s*[-_/]?\s*(ml|cl)\b",
            normalized,
            re.I,
        )
        if match:
            try:
                size_ml = float(match.group(1).replace(",", "."))
                if match.group(2).lower() == "cl":
                    size_ml *= 10
            except Exception:
                size_ml = None

        sample_tokens = {
            "sample", "samples", "campione", "campioncino",
            "echantillon", "muestra",
        }
        requests_sample = bool(set(normalized.split()) & sample_tokens)

        base = re.sub(
            r"\b(?:sample|samples|campione|campioncino|echantillon|muestra)\b",
            " ",
            normalized,
            flags=re.I,
        )
        base = re.sub(
            r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
            " ",
            base,
            flags=re.I,
        )
        base = re.sub(r"\s+", " ", base).strip()

        return {
            "raw": raw,
            "normalized": normalized,
            "size_ml": size_ml,
            "requests_sample": requests_sample,
            "requests_small": requests_sample or (
                size_ml is not None and size_ml <= 10
            ),
            "base_query": base,
        }

    def _discovery_queries(self, query: str) -> List[str]:
        flags = self._query_flags(query)
        raw = flags["raw"]
        base = flags["base_query"]

        queries: List[str] = []
        seen = set()

        def add(value: Any) -> None:
            value = str(value or "").strip()
            key = self._norm(value)
            if value and key and key not in seen:
                seen.add(key)
                queries.append(value)

        # Use the catalog's canonical family when the current main.py exposes
        # it. This improves recall but does not change validation.
        family = None
        try:
            fn = getattr(self.legacy, "_catalog_family_for_query", None)
            if callable(fn):
                family = fn(raw)
        except Exception:
            family = None

        if isinstance(family, dict):
            brand = str(family.get("brand") or "").strip()
            variant = ""

            try:
                fn = getattr(self.legacy, "_catalog_requested_variant", None)
                if callable(fn):
                    requested = fn(raw, family)
                    if isinstance(requested, dict):
                        variant = str(
                            requested.get("canonical_name") or ""
                        ).strip()
            except Exception:
                pass

            if brand and variant:
                add(f"{brand} {variant}")
            elif brand and base:
                add(f"{brand} {base}")

        add(raw)

        if flags["requests_small"] and base:
            add(base)
            if flags["requests_sample"]:
                add(f"{base} sample")
                add(f"{base} 10 ml")

        return queries

    def _filter_requested_format(
        self,
        candidates: List[Dict[str, Any]],
        query: str,
    ) -> List[Dict[str, Any]]:
        flags = self._query_flags(query)
        if not flags["requests_small"]:
            return list(candidates)

        requested = flags["size_ml"]
        result = []

        for item in candidates:
            size = self._size_ml(item)

            if flags["requests_sample"] and requested is None:
                if size is None or size > 10:
                    continue

            if requested is not None:
                if size is None or abs(size - requested) > 0.01:
                    continue

            result.append(item)

        return result

    # ---------------------------------------------------------------
    # Store execution
    # ---------------------------------------------------------------

    def _run_one_store(self, store: str, query: str) -> StoreRun:
        started = time.monotonic()

        try:
            runner = getattr(self.legacy, "run_store", None)
            if not callable(runner):
                raise RuntimeError("main.run_store is not available")

            candidates: List[Dict[str, Any]] = []
            seen: set = set()

            for discovery_query in self._discovery_queries(query):
                try:
                    raw = runner(store, discovery_query)

                    if raw is None:
                        batch = []
                    elif isinstance(raw, list):
                        batch = raw
                    else:
                        try:
                            batch = list(raw)
                        except Exception:
                            batch = []

                    for item in batch:
                        if not isinstance(item, dict):
                            continue

                        key = self._candidate_key(item, store)
                        if key in seen:
                            # Same store + same product identity + same size.
                            continue

                        seen.add(key)
                        candidate = dict(item)

                        # Guarantee store provenance even when an adapter forgot
                        # to put it in its returned object.
                        if not candidate.get("store") and not candidate.get("shop"):
                            candidate["store"] = store

                        candidates.append(candidate)

                except Exception as exc:
                    print(
                        f"STORE_SEARCH_ATTEMPT_ERROR: store={store} "
                        f"query={discovery_query!r} "
                        f"error={type(exc).__name__}: {exc}",
                        flush=True,
                    )

            # Retry only a true zero-result store.
            for retry in range(STORE_RETRIES):
                if candidates:
                    break

                time.sleep(RETRY_DELAYS[min(retry, len(RETRY_DELAYS) - 1)])

                for discovery_query in self._discovery_queries(query):
                    try:
                        raw = runner(store, discovery_query)
                        batch = raw if isinstance(raw, list) else list(raw or [])

                        for item in batch:
                            if not isinstance(item, dict):
                                continue

                            key = self._candidate_key(item, store)
                            if key in seen:
                                continue

                            seen.add(key)
                            candidate = dict(item)
                            if not candidate.get("store") and not candidate.get("shop"):
                                candidate["store"] = store
                            candidates.append(candidate)

                    except Exception as exc:
                        print(
                            f"STORE_RETRY_ERROR: store={store} "
                            f"retry={retry + 1} "
                            f"error={type(exc).__name__}: {exc}",
                            flush=True,
                        )

            candidates = self._filter_requested_format(candidates, query)

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
        started = time.monotonic()

        results = {
            store: StoreRun(store=store)
            for store in self.stores
        }

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(2, max(1, len(self.stores))),
            thread_name_prefix="scenthunter-store",
        )

        futures = {
            executor.submit(self._run_one_store, store, query): store
            for store in self.stores
        }

        try:
            pending = set(futures)
            deadline = started + self.global_timeout
            submitted = {f: time.monotonic() for f in futures}

            while pending:
                now = time.monotonic()
                if now >= deadline:
                    break

                done = {f for f in pending if f.done()}

                for future in done:
                    pending.remove(future)
                    store = futures[future]
                    try:
                        results[store] = future.result()
                    except Exception as exc:
                        results[store] = StoreRun(
                            store=store,
                            status="error",
                            error=f"{type(exc).__name__}: {exc}",
                        )

                now = time.monotonic()
                for future in list(pending):
                    if now - submitted[future] >= self.store_timeout:
                        pending.remove(future)
                        store = futures[future]
                        results[store] = StoreRun(
                            store=store,
                            status="timeout",
                            error=f"store timeout ({self.store_timeout:.0f}s)",
                            elapsed=now - submitted[future],
                        )

                if pending:
                    time.sleep(0.05)

            now = time.monotonic()
            for future in pending:
                store = futures[future]
                results[store] = StoreRun(
                    store=store,
                    status="timeout",
                    error="global search window expired",
                    elapsed=now - submitted[future],
                )

        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return {
            "stores": results,
            "elapsed": time.monotonic() - started,
        }

    # ---------------------------------------------------------------
    # Validation
    # ---------------------------------------------------------------

    def _validate_batch(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Central validation wrapper.

        IMPORTANT:
        this method is called ONLY for candidates that have not previously
        been accepted. Existing accepted candidates are never passed back
        through a destructive later validation.
        """
        if not candidates:
            return []

        batch = list(candidates)

        pre_rank = getattr(self.legacy, "_pre_rank_candidates", None)
        if callable(pre_rank):
            try:
                batch = pre_rank(batch, query)
            except TypeError:
                try:
                    batch = pre_rank(batch)
                except Exception:
                    pass
            except Exception:
                pass

        validator = getattr(self.legacy, "_validate_candidates_parallel", None)
        if callable(validator):
            try:
                validated = validator(batch, query)
            except TypeError:
                validated = validator(batch)
            except Exception:
                validated = []

            if validated is None:
                return []

            try:
                return [
                    dict(x) for x in validated
                    if isinstance(x, dict)
                ]
            except Exception:
                return []

        return [dict(x) for x in batch if isinstance(x, dict)]

    def _prepare_final(self, query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Final preparation is allowed to group offers, but it is NOT allowed to
        perform a new candidate validation pass.

        If the legacy prepare function itself returns fewer candidates, the
        lossless fallback below restores missing store candidates whenever they
        are not represented in the prepared output.
        """
        prepare = getattr(self.legacy, "_prepare_final_results", None)

        if not callable(prepare):
            return self._stable_results(candidates)

        try:
            prepared = prepare(candidates, query)
        except TypeError:
            try:
                prepared = prepare(candidates)
            except Exception:
                prepared = candidates
        except Exception:
            prepared = candidates

        if prepared is None:
            prepared = []

        if not isinstance(prepared, list):
            try:
                prepared = list(prepared)
            except Exception:
                prepared = []

        prepared = [
            dict(x) for x in prepared
            if isinstance(x, dict)
        ]

        # Lossless store reconciliation.
        #
        # The old failure mode was:
        #   candidate A exists
        #   later finalization produces B
        #   A disappears
        #
        # Here we explicitly compare stores. If a validated store candidate is
        # not represented in the prepared result, we retain the original.
        represented_stores = set()

        for item in prepared:
            store = self._store_name(item)
            if store:
                represented_stores.add(store)

            offers = item.get("offers")
            if isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict):
                        offer_store = self._store_name(offer)
                        if offer_store:
                            represented_stores.add(offer_store)

        restored = list(prepared)

        for candidate in candidates:
            store = self._store_name(candidate)
            if not store:
                continue

            if store in represented_stores:
                continue

            restored.append(dict(candidate))
            represented_stores.add(store)

        return self._stable_results(restored)

    # ---------------------------------------------------------------
    # Synchronous search
    # ---------------------------------------------------------------

    def search(self, query: str) -> Dict[str, Any]:
        text = str(query or "").strip()

        if not text:
            return {
                "query": "",
                "count": 0,
                "results": [],
                "comparisons": [],
                "errors": {},
            }

        run = self._run_stores(text)

        raw_pool: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}

        for store in self.stores:
            result: StoreRun = run["stores"][store]
            self._merge_unique(raw_pool, result.candidates, store)

            if result.error:
                errors[store] = result.error

        # One validation pass for the complete raw set.
        validated = self._validate_batch(text, raw_pool)
        final = self._prepare_final(text, validated)

        return {
            "query": text,
            "count": len(final),
            "results": final,
            "comparisons": [],
            "errors": errors,
        }

    # ---------------------------------------------------------------
    # Background job API
    # ---------------------------------------------------------------

    def run_job(self, job_id: str, query: str) -> None:
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

        def exists() -> bool:
            if lock is not None:
                with lock:
                    return job_id in jobs
            return job_id in jobs

        started = time.monotonic()

        # These two structures are the heart of the fix.
        raw_pool: List[Dict[str, Any]] = []
        accepted_pool: List[Dict[str, Any]] = []

        # A candidate is validated once. It is never invalidated by a later
        # wave. The key includes store, preventing cross-store destruction.
        validated_keys: set = set()
        accepted_keys: set = set()

        store_status = {
            store: {"status": "pending", "count": 0}
            for store in self.stores
        }
        errors: Dict[str, str] = {}

        update({
            "completed": False,
            "phase": "discovery",
            "status": "searching",
            "results": [],
            "candidates": [],
            "errors": {},
            "store_status": store_status,
        })

        try:
            # Exactly two stores per wave, matching the current architecture.
            for wave_start in range(0, len(self.stores), 2):
                wave = self.stores[wave_start:wave_start + 2]

                update({
                    "phase": f"stores_{wave_start + 1}_{wave_start + len(wave)}",
                    "status": "searching",
                    "store_status": {
                        **store_status,
                        **{
                            store: {"status": "searching", "count": 0}
                            for store in wave
                        },
                    },
                })

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=2,
                    thread_name_prefix="scenthunter-store",
                ) as executor:

                    future_map = {
                        executor.submit(
                            self._run_one_store,
                            store,
                            query,
                        ): store
                        for store in wave
                    }

                    for future in concurrent.futures.as_completed(future_map):
                        store = future_map[future]

                        try:
                            result: StoreRun = future.result()
                        except Exception as exc:
                            result = StoreRun(
                                store=store,
                                status="error",
                                error=f"{type(exc).__name__}: {exc}",
                            )

                        store_status[store] = {
                            "status": result.status,
                            "count": len(result.candidates),
                            "elapsed": round(result.elapsed, 3),
                            "error": result.error,
                        }

                        if result.error:
                            errors[store] = result.error

                        # ---------------------------------------------------
                        # LOSSLESS MERGE
                        # ---------------------------------------------------
                        # First add the new raw candidates. Existing stores are
                        # never overwritten by a later wave.
                        new_candidates: List[Dict[str, Any]] = []

                        for item in result.candidates:
                            if not isinstance(item, dict):
                                continue

                            candidate = dict(item)
                            if not candidate.get("store") and not candidate.get("shop"):
                                candidate["store"] = store

                            key = self._candidate_key(candidate, store)

                            if key in {
                                self._candidate_key(x, store)
                                for x in raw_pool
                                if isinstance(x, dict)
                            }:
                                continue

                            raw_pool.append(candidate)
                            new_candidates.append(candidate)

                        # ---------------------------------------------------
                        # VALIDATE ONLY NEW CANDIDATES
                        # ---------------------------------------------------
                        # This is the fundamental correction.
                        #
                        # OLD:
                        #     validate(raw_pool)
                        #
                        # NEW:
                        #     validate(new_candidates)
                        #
                        # Therefore an already accepted Deloox candidate can
                        # never be removed when ParfumCity/Sabina/etc. arrive.
                        to_validate = []

                        for candidate in new_candidates:
                            key = self._candidate_key(candidate, store)
                            if key not in validated_keys:
                                validated_keys.add(key)
                                to_validate.append(candidate)

                        newly_accepted = self._validate_batch(
                            query,
                            to_validate,
                        )

                        for candidate in newly_accepted:
                            key = self._candidate_key(candidate, store)

                            if key in accepted_keys:
                                continue

                            accepted_keys.add(key)
                            accepted_pool.append(dict(candidate))

                        # ---------------------------------------------------
                        # PROGRESS RESULT
                        # ---------------------------------------------------
                        # Progress is prepared from the MONOTONIC accepted_pool.
                        # We do not validate it again.
                        progress_results = self._prepare_final(
                            query,
                            list(accepted_pool),
                        )

                        update({
                            "results": progress_results,
                            "candidates": list(raw_pool),
                            "errors": dict(errors),
                            "store_status": dict(store_status),
                            "phase": (
                                f"stores_{wave_start + 1}_"
                                f"{wave_start + len(wave)}"
                            ),
                            "status": "searching",
                            "completed": False,
                            "elapsed": round(time.monotonic() - started, 3),
                        })

                        if not exists():
                            return

                if not exists():
                    return

            # ---------------------------------------------------------------
            # FINAL PUBLICATION
            # ---------------------------------------------------------------
            #
            # accepted_pool is monotonic and contains every candidate that was
            # accepted during any wave. No second validation is performed.
            final_results = self._prepare_final(
                query,
                list(accepted_pool),
            )

            update({
                "results": final_results,
                "candidates": list(raw_pool),
                "errors": dict(errors),
                "store_status": dict(store_status),
                "phase": "completed",
                "status": "completed",
                "completed": True,
                "elapsed": round(time.monotonic() - started, 3),
                "raw_candidate_count": len(raw_pool),
                "validated_candidate_count": len(accepted_pool),
            })

        except Exception as exc:
            update({
                "results": [],
                "errors": {
                    **errors,
                    "_search": f"{type(exc).__name__}: {exc}",
                },
                "status": "error",
                "completed": True,
                "phase": "error",
                "elapsed": round(time.monotonic() - started, 3),
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
            })
