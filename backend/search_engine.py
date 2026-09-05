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
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


DEFAULT_STORE_TIMEOUT = 65.0
DEFAULT_GLOBAL_TIMEOUT = 145.0
STORE_RETRIES = 2
RETRY_DELAYS = (1.25, 3.0)


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
    # Temporary Deloox / Liquid Brun forensic trace
    # ------------------------------------------------------------------

    _DELOOX_TRACE_MARKER = "SCENTHUNTER_DELOOX_TRACE_V2"
    _DELOOX_TRACE_QUERY = "liquid brun"
    _DELOOX_TRACE_STORE = "deloox"

    @classmethod
    def _deloox_trace_enabled(cls, query: Any, store: Any = "deloox") -> bool:
        try:
            normalized = str(query or "").strip().lower()
            normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
            normalized = re.sub(r"\s+", " ", normalized).strip()
            return normalized == cls._DELOOX_TRACE_QUERY and str(store or "").strip().lower() == cls._DELOOX_TRACE_STORE
        except Exception:
            return False

    @staticmethod
    def _deloox_trace_value(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): SearchEngine._deloox_trace_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [SearchEngine._deloox_trace_value(v) for v in value]
        return str(value)

    def _deloox_trace_offer(self, item: Any) -> Dict[str, Any]:
        if not isinstance(item, dict):
            return {"type": type(item).__name__, "value": self._deloox_trace_value(item)}
        keys = (
            "store", "shop", "name", "title", "product_name", "brand",
            "source_brand", "canonical_brand", "canonical_name", "catalog_variant",
            "catalog_id", "product_id", "product_identity", "family_id", "family_name",
            "size_ml", "volume_ml", "format_ml", "size", "format", "volume",
            "price", "price_num", "price_value", "in_stock", "available",
            "availability", "stock", "stock_status", "url", "gtin", "mpn",
            "match_method", "identity", "source",
        )
        payload = {k: self._deloox_trace_value(item.get(k)) for k in keys if k in item}
        payload["all_keys"] = sorted(str(k) for k in item.keys())
        try:
            payload["derived_size_ml"] = self._extract_candidate_size_ml(item)
        except Exception:
            payload["derived_size_ml"] = None
        return payload

    def _deloox_trace_candidates(self, candidates: Any) -> Dict[str, Any]:
        if not isinstance(candidates, list):
            try:
                candidates = list(candidates or [])
            except Exception:
                candidates = []
        deloox = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            store = str(item.get("store") or item.get("shop") or "").strip().lower()
            url = str(item.get("url") or "").strip().lower()
            if store == "deloox" or "deloox" in url:
                deloox.append(self._deloox_trace_offer(item))
        return {"total": len(candidates), "deloox_count": len(deloox), "deloox": deloox}

    @staticmethod
    def _deloox_trace_identity(item: Any) -> str:
        if not isinstance(item, dict):
            return "non_dict:" + repr(item)
        for key in ("url", "product_id", "catalog_id", "gtin", "mpn"):
            value = item.get(key)
            if value not in (None, ""):
                return f"{key}:{value}"
        return f"name:{item.get('store') or item.get('shop') or ''}|{item.get('name') or item.get('title') or item.get('product_name') or item.get('canonical_name') or ''}|{item.get('size_ml')}"

    def _deloox_trace_diff(self, before: Any, after: Any) -> Dict[str, Any]:
        def only_deloox(value: Any) -> List[Dict[str, Any]]:
            if not isinstance(value, list):
                try:
                    value = list(value or [])
                except Exception:
                    value = []
            return [
                x for x in value if isinstance(x, dict) and (
                    str(x.get("store") or x.get("shop") or "").strip().lower() == "deloox"
                    or "deloox" in str(x.get("url") or "").strip().lower()
                )
            ]
        b, a = only_deloox(before), only_deloox(after)
        bm = {self._deloox_trace_identity(x): x for x in b}
        am = {self._deloox_trace_identity(x): x for x in a}
        return {
            "before_deloox_count": len(b),
            "after_deloox_count": len(a),
            "removed_count": len(set(bm) - set(am)),
            "added_count": len(set(am) - set(bm)),
            "removed": [self._deloox_trace_offer(bm[k]) for k in bm.keys() - am.keys()],
            "added": [self._deloox_trace_offer(am[k]) for k in am.keys() - bm.keys()],
        }

    def _deloox_trace_log(self, stage: str, query: str, *, job_id: Optional[str] = None, store: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> None:
        if not self._deloox_trace_enabled(query, store or "deloox"):
            return
        import json
        record = {
            "marker": self._DELOOX_TRACE_MARKER,
            "stage": stage,
            "job_id": job_id,
            "query": str(query or ""),
            "store": store or "deloox",
        }
        if payload:
            record.update(payload)
        print(self._DELOOX_TRACE_MARKER + " " + json.dumps(record, ensure_ascii=False, default=str, sort_keys=True), flush=True)

    def _deloox_prepare_with_trace(self, prepare: Callable[..., Any], candidates: List[Dict[str, Any]], query: str, *, job_id: Optional[str] = None) -> Any:
        # No shGroupData() exists in the current repository. The actual final
        # grouping boundary is _prepare_final_results(), so we trace that exact function.
        if not self._deloox_trace_enabled(query):
            try:
                return prepare(candidates, query)
            except TypeError:
                return prepare(candidates)

        self._deloox_trace_log(
            "3_grouping_input_prepare_final_results",
            query,
            job_id=job_id,
            payload={
                "function": getattr(prepare, "__name__", str(prepare)),
                "input": self._deloox_trace_candidates(candidates),
            },
        )
        try:
            final = prepare(candidates, query)
        except TypeError:
            final = prepare(candidates)

        final_list = final if isinstance(final, list) else list(final or [])
        nested = []
        for result in final_list:
            if isinstance(result, dict) and isinstance(result.get("offers"), list):
                nested.extend(x for x in result["offers"] if isinstance(x, dict))

        self._deloox_trace_log(
            "4_grouping_output_prepare_final_results",
            query,
            job_id=job_id,
            payload={
                "output_top_level": self._deloox_trace_candidates(final_list),
                "output_nested_offers": self._deloox_trace_candidates(nested),
                "diff_top_level": self._deloox_trace_diff(candidates, final_list),
                "diff_nested_offers": self._deloox_trace_diff(candidates, nested),
            },
        )
        return final


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

    def _query_flags(self, query: str) -> Dict[str, Any]:
        raw = str(query or "").strip()
        normalized = self.legacy.norm(raw) if hasattr(self.legacy, "norm") else raw.lower()

        size_ml = None
        try:
            m = self.legacy.re.search(
                r"(?<!\d)(\d+(?:[.,]\d+)?)\s*[-_/]?\s*(ml|cl)\b",
                normalized,
                self.legacy.re.I,
            )
            if m:
                size_ml = float(m.group(1).replace(",", "."))
                if m.group(2).lower() == "cl":
                    size_ml *= 10.0
        except Exception:
            size_ml = None

        sample_tokens = {
            "sample", "samples", "campione", "campioncino", "echantillon", "muestra"
        }
        requests_sample = bool(set(normalized.split()) & sample_tokens)

        base = self.legacy.re.sub(
            r"\b(?:sample|samples|campione|campioncino|echantillon|muestra)\b",
            " ", normalized, flags=self.legacy.re.I,
        )
        base = self.legacy.re.sub(
            r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
            " ", base, flags=self.legacy.re.I,
        )
        base = self.legacy.re.sub(r"\s+", " ", base).strip()

        return {
            "raw": raw,
            "normalized": normalized,
            "size_ml": size_ml,
            "requests_sample": requests_sample,
            "requests_small": requests_sample or (size_ml is not None and size_ml <= 10.0),
            "base_query": base,
        }

    def _discovery_queries(self, query: str) -> List[str]:
        """
        Build a small, deterministic discovery set.

        For products/families already known by the Family Registry, the
        retailer is queried with its real brand as well as the user's text.
        This is important: a query such as ``Hawas`` is ambiguous to several
        merchant search engines, while ``Rasasi Hawas`` is not. The central
        validator remains authoritative, so broader discovery cannot publish
        false positives.
        """
        flags = self._query_flags(query)
        raw = flags["raw"]
        base = flags["base_query"]
        queries: List[str] = []
        seen = set()

        def add(value: str) -> None:
            value = str(value or "").strip()
            key = self.legacy.norm(value) if hasattr(self.legacy, "norm") else value.lower()
            if value and key and key not in seen:
                seen.add(key)
                queries.append(value)

        # Prefer a catalog-qualified query whenever the Family Registry knows
        # the family. It dramatically improves recall on merchant search
        # engines that rank by their own fuzzy interpretation of the query.
        catalog_family = None
        try:
            catalog_family = self.legacy._catalog_family_for_query(raw)
        except Exception:
            catalog_family = None

        if isinstance(catalog_family, dict):
            brand = str(catalog_family.get("brand") or "").strip()
            variant_name = ""
            try:
                requested = self.legacy._catalog_requested_variant(raw, catalog_family)
            except Exception:
                requested = None
            if isinstance(requested, dict):
                variant_name = str(requested.get("canonical_name") or "").strip()

            if brand and variant_name:
                add(f"{brand} {variant_name}")
            elif brand and base:
                add(f"{brand} {base}")

            # Keep the user's exact query as a second discovery channel. For
            # broad family searches this is what finds alternate variants.
            add(raw)
        else:
            add(raw)

        if flags["requests_small"] and base:
            add(base)
            if flags["requests_sample"]:
                add(f"{base} sample")
                add(f"{base} 10 ml")

        return queries

    def _extract_candidate_size_ml(self, item: Dict[str, Any]) -> Optional[float]:
        try:
            value = self.legacy.product_size_ml(item)
            if value is not None:
                return float(value)
        except Exception:
            pass

        values: List[Any] = []
        for key in (
            "name", "title", "product_name", "source_name", "canonical_name",
            "catalog_variant", "size", "format", "volume", "url", "handle",
        ):
            values.append(item.get(key))

        attributes = item.get("attributes")
        if isinstance(attributes, dict):
            size_attr = attributes.get("size_ml")
            if isinstance(size_attr, dict):
                values.append(size_attr.get("value"))
            else:
                values.append(size_attr)

        source = item.get("source")
        if isinstance(source, dict):
            values.extend(source.get(key) for key in ("source_name", "name", "title", "url"))

        raw_data = item.get("raw_data")
        if isinstance(raw_data, dict):
            values.extend(raw_data.get(key) for key in ("name", "title", "product_title", "handle", "url"))

        text = " ".join(str(value or "") for value in values)
        try:
            match = self.legacy.re.search(
                r"(?<!\d)(\d+(?:[.,]\d+)?)\s*[-_/]?\s*(ml|cl)\b",
                text, self.legacy.re.I,
            )
        except Exception:
            match = None
        if not match:
            return None
        try:
            value = float(match.group(1).replace(",", "."))
            return value * 10.0 if match.group(2).lower() == "cl" else value
        except (TypeError, ValueError):
            return None

    def _filter_requested_format(self, candidates: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """Enforce exact explicit size/sample semantics after broad discovery."""
        flags = self._query_flags(query)
        if not flags["requests_small"]:
            return candidates

        requested = flags["size_ml"]
        filtered: List[Dict[str, Any]] = []
        for item in candidates:
            size = self._extract_candidate_size_ml(item)

            if flags["requests_sample"] and requested is None:
                if size is None or size > 10.0:
                    continue

            if requested is not None:
                if size is None or abs(size - requested) > 0.01:
                    continue

            filtered.append(item)
        return filtered

    def _run_one_store(self, store: str, query: str) -> StoreRun:
        started = time.monotonic()

        try:
            # run_store is the existing store adapter boundary in main.py.
            runner = getattr(self.legacy, "run_store", None)
            if runner is None:
                raise RuntimeError("main.run_store is not available")

            candidates: List[Dict[str, Any]] = []
            seen_urls = set()

            discovery_queries = self._discovery_queries(query)

            def collect_from_result(raw_result: Any) -> int:
                if raw_result is None:
                    batch: List[Dict[str, Any]] = []
                elif isinstance(raw_result, list):
                    batch = raw_result
                else:
                    try:
                        batch = list(raw_result)
                    except Exception:
                        batch = []

                added = 0
                for item in batch:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    if url:
                        # A single product URL can legitimately expose several
                        # bottle sizes (e.g. 30/50/100 ml). Keep each explicit
                        # size, while still removing a true duplicate of the
                        # same URL + size.
                        size = self._extract_candidate_size_ml(item)
                        url_key = (
                            url.casefold(),
                            round(float(size), 4) if size is not None else None,
                        )
                        if url_key in seen_urls:
                            continue
                        seen_urls.add(url_key)
                    candidates.append(item)
                    added += 1
                return added

            # First pass: every store gets its full discovery strategy.
            for discovery_query in discovery_queries:
                try:
                    raw_result = runner(store, discovery_query)
                    if self._deloox_trace_enabled(query, store):
                        raw_batch = raw_result if isinstance(raw_result, list) else list(raw_result or [])
                        self._deloox_trace_log(
                            "1_test_store_equivalent_raw_response",
                            query,
                            store=store,
                            payload={
                                "discovery_query": discovery_query,
                                "response_type": type(raw_result).__name__,
                                "raw_response": self._deloox_trace_candidates(raw_batch),
                            },
                        )
                    collect_from_result(raw_result)
                except Exception as exc:
                    print(
                        f"STORE_SEARCH_ATTEMPT_ERROR: store={store} "
                        f"query={discovery_query!r} error={type(exc).__name__}: {exc}",
                        flush=True,
                    )

            # A zero-result store is not treated as a definitive miss. The
            # underlying merchant may have returned 429/5xx, transient HTML,
            # or an empty search response. Retry the complete store strategy
            # with backoff. Do not retry stores that already returned data: that
            # would create unnecessary load and increase rate-limit risk.
            retry_number = 0
            while not candidates and retry_number < STORE_RETRIES:
                delay = RETRY_DELAYS[min(retry_number, len(RETRY_DELAYS) - 1)]
                time.sleep(delay)
                retry_number += 1

                for discovery_query in discovery_queries:
                    try:
                        raw_result = runner(store, discovery_query)
                        if self._deloox_trace_enabled(query, store):
                            raw_batch = raw_result if isinstance(raw_result, list) else list(raw_result or [])
                            self._deloox_trace_log(
                                "1_test_store_equivalent_raw_response",
                                query,
                                store=store,
                                payload={
                                    "discovery_query": discovery_query,
                                    "response_type": type(raw_result).__name__,
                                    "raw_response": self._deloox_trace_candidates(raw_batch),
                                },
                            )
                        collect_from_result(raw_result)
                    except Exception as exc:
                        print(
                            f"STORE_RETRY_ERROR: store={store} retry={retry_number} "
                            f"query={discovery_query!r} error={type(exc).__name__}: {exc}",
                            flush=True,
                        )

            # No identity/availability/ranking is done here.
            clean_candidates = [
                item for item in candidates if isinstance(item, dict)
            ]

            if self._deloox_trace_enabled(query, store):
                self._deloox_trace_log(
                    "1b_deloox_store_run_complete",
                    query,
                    store=store,
                    payload={
                        "discovery_queries": discovery_queries,
                        "retry_count": retry_number,
                        "candidates_after_collection": self._deloox_trace_candidates(clean_candidates),
                    },
                )

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

        # HARD LIMIT: never run more than two store scrapers at once.
        # This protects retailers from burst/rate-limit pressure and keeps the
        # search behavior aligned with the format-comparison endpoint.
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(2, max(1, len(self.stores))),
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
                remaining_store = min(
                    max(0.0, self.store_timeout - (time.monotonic() - submitted_at[future]))
                    for future in pending
                )
                time.sleep(min(0.05, max(0.0, remaining_global), remaining_store))

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

    @staticmethod
    def _clean_display_price(value: Any) -> Any:
        """Repair common UTF-8/CP1252 mojibake in merchant display prices."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if any(marker in text for marker in ("â‚¬", "Â€", "Ã¢", "â€")):
            try:
                text = text.encode("cp1252").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                text = text.replace("â‚¬", "€").replace("Â€", "€").replace("Ã¢â‚¬", "€")
        text = text.replace("â‚¬", "€").replace("Â€", "€")
        text = re.sub(r"\s+€", " €", text)
        return text

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
                for offer in offers:
                    if "price" in offer:
                        offer["price"] = self._clean_display_price(offer.get("price"))
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

            if "price" in item:
                item["price"] = self._clean_display_price(item.get("price"))
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

        candidates = self._filter_requested_format(list(raw_candidates), query)
        if self._deloox_trace_enabled(query):
            self._deloox_trace_log(
                "2a_validation_input_after_format_filter",
                query,
                payload={
                    "input": self._deloox_trace_candidates(raw_candidates),
                    "output": self._deloox_trace_candidates(candidates),
                    "diff": self._deloox_trace_diff(raw_candidates, candidates),
                },
            )
        if pre_rank is not None:
            before_pre_rank = list(candidates)
            try:
                candidates = pre_rank(candidates, query)
            except TypeError:
                candidates = pre_rank(candidates)
            if self._deloox_trace_enabled(query):
                self._deloox_trace_log(
                    "2b_after_pre_rank",
                    query,
                    payload={
                        "output": self._deloox_trace_candidates(candidates),
                        "diff": self._deloox_trace_diff(before_pre_rank, candidates),
                    },
                )

        if validate is not None:
            before_validate = list(candidates)
            try:
                candidates = validate(candidates, query)
            except TypeError:
                candidates = validate(candidates)
            if self._deloox_trace_enabled(query):
                self._deloox_trace_log(
                    "2c_after_central_validate",
                    query,
                    payload={
                        "output": self._deloox_trace_candidates(candidates),
                        "diff": self._deloox_trace_diff(before_validate, candidates),
                    },
                )

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

        candidates = self._filter_requested_format(list(raw_candidates), query)

        if self._deloox_trace_enabled(query):
            self._deloox_trace_log(
                "3a_final_path_after_format_filter",
                query,
                payload={
                    "input": self._deloox_trace_candidates(raw_candidates),
                    "output": self._deloox_trace_candidates(candidates),
                    "diff": self._deloox_trace_diff(raw_candidates, candidates),
                },
            )

        if pre_rank is not None:
            before_pre_rank = list(candidates)
            try:
                candidates = pre_rank(candidates, query)
            except TypeError:
                candidates = pre_rank(candidates)
            if self._deloox_trace_enabled(query):
                self._deloox_trace_log(
                    "3b_final_path_after_pre_rank",
                    query,
                    payload={
                        "output": self._deloox_trace_candidates(candidates),
                        "diff": self._deloox_trace_diff(before_pre_rank, candidates),
                    },
                )

        if validate is not None:
            before_validate = list(candidates)
            try:
                candidates = validate(candidates, query)
            except TypeError:
                candidates = validate(candidates)
            if self._deloox_trace_enabled(query):
                self._deloox_trace_log(
                    "3c_final_path_after_central_validate",
                    query,
                    payload={
                        "output": self._deloox_trace_candidates(candidates),
                        "diff": self._deloox_trace_diff(before_validate, candidates),
                    },
                )

        if prepare is not None:
            final = self._deloox_prepare_with_trace(
                prepare,
                candidates,
                query,
            )
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
        """Run the background search in waves of two stores and publish progress.

        The frontend uses /search-start + /search-status for live progress.
        Each wave starts at most two store scrapers. As soon as a store finishes,
        its candidates are merged into the central job pool and the validated
        candidate list is published. The legacy snapshot then performs the final
        grouping for the response.
        """
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

        def read_job() -> Optional[Dict[str, Any]]:
            if lock is not None:
                with lock:
                    job = jobs.get(job_id)
                    return dict(job) if job is not None else None
            job = jobs.get(job_id)
            return dict(job) if job is not None else None

        started = time.monotonic()
        raw_pool: List[Dict[str, Any]] = []
        store_status: Dict[str, Any] = {
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
            # Explicit waves: never more than two scrapers are active.
            for wave_start in range(0, len(self.stores), 2):
                wave = self.stores[wave_start:wave_start + 2]
                wave_started = time.monotonic()

                update({
                    "phase": f"stores_{wave_start + 1}_{wave_start + len(wave)}",
                    "status": "searching",
                    "store_status": {
                        **store_status,
                        **{store: {"status": "searching", "count": 0} for store in wave},
                    },
                })

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=2,
                    thread_name_prefix="scenthunter-store",
                ) as executor:
                    future_map = {
                        executor.submit(self._run_one_store, store, query): store
                        for store in wave
                    }

                    for future in concurrent.futures.as_completed(future_map):
                        store = future_map[future]
                        try:
                            result = future.result()
                        except Exception as exc:
                            result = StoreRun(
                                store=store,
                                status="error",
                                candidates=[],
                                elapsed=time.monotonic() - wave_started,
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

                        raw_pool.extend(result.candidates)

                        if self._deloox_trace_enabled(query):
                            self._deloox_trace_log(
                                "2_merged_after_store_batch",
                                query,
                                job_id=job_id,
                                store=store,
                                payload={
                                    "completed_store": store,
                                    "store_result": self._deloox_trace_candidates(result.candidates),
                                    "raw_pool": self._deloox_trace_candidates(raw_pool),
                                },
                            )

                        # Publish after every completed store. This is the
                        # important difference from the old implementation:
                        # users no longer wait for all eight stores.
                        validated = self._validate_candidates_only(query, raw_pool)
                        if self._deloox_trace_enabled(query):
                            self._deloox_trace_log(
                                "2b_merged_batch_published_results",
                                query,
                                job_id=job_id,
                                store=store,
                                payload={
                                    "results": self._deloox_trace_candidates(validated),
                                    "comparisons": [],
                                    "raw_pool": self._deloox_trace_candidates(raw_pool),
                                    "diff_raw_to_results": self._deloox_trace_diff(raw_pool, validated),
                                },
                            )
                        update({
                            "results": validated,
                            "candidates": list(raw_pool),
                            "errors": dict(errors),
                            "store_status": dict(store_status),
                            "phase": f"stores_{wave_start + 1}_{wave_start + len(wave)}",
                            "status": "searching",
                            "completed": False,
                            "elapsed": round(time.monotonic() - started, 3),
                        })

                if read_job() is None:
                    return

            # Final publication. Keep raw validated candidates in the job; the
            # legacy /search-status snapshot performs _prepare_final_results().
            validated = self._validate_candidates_only(query, raw_pool)
            if self._deloox_trace_enabled(query):
                self._deloox_trace_log(
                    "2c_final_merged_before_snapshot",
                    query,
                    job_id=job_id,
                    payload={
                        "raw_pool": self._deloox_trace_candidates(raw_pool),
                        "results": self._deloox_trace_candidates(validated),
                        "comparisons": [],
                        "diff_raw_to_results": self._deloox_trace_diff(raw_pool, validated),
                    },
                )
            update({
                "results": validated,
                "candidates": list(raw_pool),
                "errors": dict(errors),
                "store_status": dict(store_status),
                "phase": "completed",
                "status": "completed",
                "completed": True,
                "elapsed": round(time.monotonic() - started, 3),
                "raw_candidate_count": len(raw_pool),
            })

        except Exception as exc:
            update({
                "results": [],
                "errors": {**errors, "_search": f"{type(exc).__name__}: {exc}"},
                "status": "error",
                "completed": True,
                "phase": "error",
                "elapsed": round(time.monotonic() - started, 3),
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
            })
