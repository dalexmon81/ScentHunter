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
    # BASIC HELPERS
    # ---------------------------------------------------------------

    def _norm(self, value: Any) -> str:
        fn = getattr(self.legacy, "norm", None)
        if callable(fn):
            try:
                return str(fn(str(value or ""))).strip().casefold()
            except Exception:
                pass

        return re.sub(
            r"\s+",
            " ",
            str(value or "").strip(),
        ).casefold()

    def _store_name(
        self,
        item: Dict[str, Any],
        fallback: str = "",
    ) -> str:
        return str(
            item.get("store")
            or item.get("shop")
            or item.get("source")
            or fallback
            or ""
        ).strip().casefold()

    def _size_ml(
        self,
        item: Dict[str, Any],
    ) -> Optional[float]:
        fn = getattr(
            self.legacy,
            "product_size_ml",
            None,
        )

        if callable(fn):
            try:
                value = fn(item)

                if value is not None:
                    return float(value)

            except Exception:
                pass

        values: List[str] = []

        for key in (
            "size_ml",
            "volume_ml",
            "format_ml",
            "size",
            "format",
            "volume",
            "name",
            "title",
            "product_name",
            "canonical_name",
            "catalog_variant",
            "url",
        ):
            if item.get(key) not in (
                None,
                "",
            ):
                values.append(
                    str(item.get(key))
                )

        attrs = item.get("attributes")

        if isinstance(attrs, dict):
            value = attrs.get("size_ml")

            if isinstance(value, dict):
                value = value.get("value")

            if value not in (
                None,
                "",
            ):
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
            number = float(
                match.group(1).replace(",", ".")
            )

            if match.group(2).lower() == "cl":
                number *= 10

            return number

        except Exception:
            return None

    def _candidate_key(
        self,
        item: Dict[str, Any],
        fallback_store: str = "",
    ) -> Tuple[str, ...]:
        """
        Store is deliberately the FIRST component.

        Different stores can therefore never collapse into one candidate.
        """

        store = self._store_name(
            item,
            fallback_store,
        )

        size = self._size_ml(item)
        size_key = (
            f"{size:.4f}"
            if size is not None
            else ""
        )

        product_id = str(
            item.get("product_id")
            or item.get("catalog_id")
            or item.get("gtin")
            or item.get("mpn")
            or ""
        ).strip().casefold()

        url = str(
            item.get("url")
            or ""
        ).strip().casefold()

        name = self._norm(
            item.get("canonical_name")
            or item.get("product_name")
            or item.get("title")
            or item.get("name")
            or ""
        )

        identity = (
            product_id
            or url
            or name
        )

        return (
            store,
            identity,
            size_key,
        )

    def _merge_unique(
        self,
        destination: List[Dict[str, Any]],
        incoming: List[Dict[str, Any]],
        fallback_store: str = "",
    ) -> int:
        existing: Dict[
            Tuple[str, ...],
            int,
        ] = {}

        for index, item in enumerate(destination):
            if isinstance(item, dict):
                existing[
                    self._candidate_key(
                        item,
                        fallback_store,
                    )
                ] = index

        added = 0

        for item in incoming:
            if not isinstance(item, dict):
                continue

            key = self._candidate_key(
                item,
                fallback_store,
            )

            old_index = existing.get(key)

            if old_index is None:
                destination.append(
                    dict(item)
                )

                existing[key] = (
                    len(destination) - 1
                )

                added += 1
                continue

            current = destination[old_index]

            for field, value in item.items():
                if value in (
                    None,
                    "",
                    [],
                    {},
                ):
                    continue

                if current.get(field) in (
                    None,
                    "",
                    [],
                    {},
                ):
                    current[field] = value

        return added

    # ---------------------------------------------------------------
    # AVAILABILITY / PRICE
    # ---------------------------------------------------------------

    def _availability_rank(
        self,
        item: Dict[str, Any],
    ) -> int:
        value = str(
            item.get("availability")
            or item.get("stock_status")
            or item.get("stock")
            or ""
        ).strip().casefold()

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
            "unknown",
            "pending",
            "unconfirmed",
            "",
        }:
            return 1

        if value in {
            "out_of_stock",
            "oos",
            "unavailable",
            "sold_out",
            "sold out",
            "false",
            "0",
            "out of stock",
        }:
            return 2

        return 1

    def _price_value(
        self,
        item: Dict[str, Any],
    ) -> float:
        value = item.get("price_num")

        if value is None:
            value = item.get("price_value")

        if value is None:
            value = item.get("price")

        if isinstance(value, str):
            value = re.sub(
                r"[^\d,.]",
                "",
                value,
            ).replace(",", ".")

        try:
            return float(value)
        except Exception:
            return float("inf")

    def _stable_results(
        self,
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Sorting only.

        This function NEVER validates, filters or deduplicates.
        """

        output = [
            dict(x)
            for x in results
            if isinstance(x, dict)
        ]

        for item in output:
            offers = item.get("offers")

            if isinstance(offers, list):
                cleaned = [
                    dict(x)
                    for x in offers
                    if isinstance(x, dict)
                ]

                cleaned.sort(
                    key=lambda x: (
                        self._availability_rank(x),
                        self._price_value(x),
                        self._store_name(x),
                        str(
                            x.get("url")
                            or ""
                        ),
                    )
                )

                item["offers"] = cleaned
                item["offer_count"] = len(
                    cleaned
                )

        output.sort(
            key=lambda x: (
                self._availability_rank(x),
                self._price_value(x),
                self._store_name(x),
                str(
                    x.get("url")
                    or ""
                ),
                str(
                    x.get("title")
                    or x.get("name")
                    or ""
                ),
            )
        )

        return output

    # ---------------------------------------------------------------
    # QUERY
    # ---------------------------------------------------------------

    def analyze_query(
        self,
        query: str,
    ) -> Dict[str, Any]:
        raw = str(
            query or ""
        ).strip()

        return {
            "raw": raw,
            "normalized": self._norm(raw),
            "size_ml": None,
        }

    def _query_flags(
        self,
        query: str,
    ) -> Dict[str, Any]:
        raw = str(
            query or ""
        ).strip()

        normalized = self._norm(raw)

        size_ml = None

        match = re.search(
            r"(?<!\d)(\d+(?:[.,]\d+)?)\s*[-_/]?\s*(ml|cl)\b",
            normalized,
            re.I,
        )

        if match:
            try:
                size_ml = float(
                    match.group(1).replace(
                        ",",
                        ".",
                    )
                )

                if match.group(2).lower() == "cl":
                    size_ml *= 10

            except Exception:
                size_ml = None

        sample_tokens = {
            "sample",
            "samples",
            "campione",
            "campioncino",
            "echantillon",
            "muestra",
        }

        requests_sample = bool(
            set(normalized.split())
            & sample_tokens
        )

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

        base = re.sub(
            r"\s+",
            " ",
            base,
        ).strip()

        return {
            "raw": raw,
            "normalized": normalized,
            "size_ml": size_ml,
            "requests_sample": requests_sample,
            "requests_small": (
                requests_sample
                or (
                    size_ml is not None
                    and size_ml <= 10
                )
            ),
            "base_query": base,
        }

    def _discovery_queries(
        self,
        query: str,
    ) -> List[str]:
        flags = self._query_flags(query)

        raw = flags["raw"]
        base = flags["base_query"]

        queries: List[str] = []
        seen = set()

        def add(value: Any) -> None:
            value = str(
                value or ""
            ).strip()

            key = self._norm(value)

            if (
                value
                and key
                and key not in seen
            ):
                seen.add(key)
                queries.append(value)

        family = None

        try:
            fn = getattr(
                self.legacy,
                "_catalog_family_for_query",
                None,
            )

            if callable(fn):
                family = fn(raw)

        except Exception:
            family = None

        if isinstance(family, dict):
            brand = str(
                family.get("brand")
                or ""
            ).strip()

            variant = ""

            try:
                fn = getattr(
                    self.legacy,
                    "_catalog_requested_variant",
                    None,
                )

                if callable(fn):
                    requested = fn(
                        raw,
                        family,
                    )

                    if isinstance(
                        requested,
                        dict,
                    ):
                        variant = str(
                            requested.get(
                                "canonical_name"
                            )
                            or ""
                        ).strip()

            except Exception:
                pass

            if brand and variant:
                add(
                    f"{brand} {variant}"
                )

            elif brand and base:
                add(
                    f"{brand} {base}"
                )

        add(raw)

        if flags["requests_small"] and base:
            add(base)

            if flags["requests_sample"]:
                add(
                    f"{base} sample"
                )

                add(
                    f"{base} 10 ml"
                )

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

            if flags["requests_sample"]:
                if (
                    requested is None
                    and (
                        size is None
                        or size > 10
                    )
                ):
                    continue

            if requested is not None:
                if (
                    size is None
                    or abs(size - requested) > 0.01
                ):
                    continue

            result.append(item)

        return result

    # ---------------------------------------------------------------
    # STORE EXECUTION
    # ---------------------------------------------------------------

    def _run_one_store(
        self,
        store: str,
        query: str,
    ) -> StoreRun:
        started = time.monotonic()

        try:
            runner = getattr(
                self.legacy,
                "run_store",
                None,
            )

            if not callable(runner):
                raise RuntimeError(
                    "main.run_store is not available"
                )

            candidates: List[
                Dict[str, Any]
            ] = []

            seen = set()

            for discovery_query in self._discovery_queries(
                query
            ):
                try:
                    raw = runner(
                        store,
                        discovery_query,
                    )

                    if raw is None:
                        batch = []

                    elif isinstance(
                        raw,
                        list,
                    ):
                        batch = raw

                    else:
                        try:
                            batch = list(raw)
                        except Exception:
                            batch = []

                    for item in batch:
                        if not isinstance(
                            item,
                            dict,
                        ):
                            continue

                        candidate = dict(item)

                        if not candidate.get(
                            "store"
                        ) and not candidate.get(
                            "shop"
                        ):
                            candidate["store"] = store

                        key = self._candidate_key(
                            candidate,
                            store,
                        )

                        if key in seen:
                            continue

                        seen.add(key)
                        candidates.append(
                            candidate
                        )

                except Exception as exc:
                    print(
                        "STORE_SEARCH_ATTEMPT_ERROR: "
                        f"store={store} "
                        f"query={discovery_query!r} "
                        f"error={type(exc).__name__}: {exc}",
                        flush=True,
                    )

            # Retry only a true zero-result store.
            for retry in range(
                STORE_RETRIES
            ):
                if candidates:
                    break

                time.sleep(
                    RETRY_DELAYS[
                        min(
                            retry,
                            len(RETRY_DELAYS) - 1,
                        )
                    ]
                )

                for discovery_query in self._discovery_queries(
                    query
                ):
                    try:
                        raw = runner(
                            store,
                            discovery_query,
                        )

                        if raw is None:
                            batch = []

                        elif isinstance(
                            raw,
                            list,
                        ):
                            batch = raw

                        else:
                            try:
                                batch = list(raw)
                            except Exception:
                                batch = []

                        for item in batch:
                            if not isinstance(
                                item,
                                dict,
                            ):
                                continue

                            candidate = dict(item)

                            if not candidate.get(
                                "store"
                            ) and not candidate.get(
                                "shop"
                            ):
                                candidate["store"] = store

                            key = self._candidate_key(
                                candidate,
                                store,
                            )

                            if key in seen:
                                continue

                            seen.add(key)
                            candidates.append(
                                candidate
                            )

                    except Exception as exc:
                        print(
                            "STORE_RETRY_ERROR: "
                            f"store={store} "
                            f"retry={retry + 1} "
                            f"error={type(exc).__name__}: {exc}",
                            flush=True,
                        )

            candidates = self._filter_requested_format(
                candidates,
                query,
            )

            return StoreRun(
                store=store,
                status=(
                    "ok"
                    if candidates
                    else "empty"
                ),
                candidates=candidates,
                elapsed=(
                    time.monotonic()
                    - started
                ),
            )

        except Exception as exc:
            return StoreRun(
                store=store,
                status="error",
                candidates=[],
                elapsed=(
                    time.monotonic()
                    - started
                ),
                error=(
                    f"{type(exc).__name__}: {exc}"
                ),
            )

    def _run_stores(
        self,
        query: str,
    ) -> Dict[str, Any]:
        """
        Execute all stores.

        IMPORTANT FIX:
        timeout starts when a worker actually starts the store, not when the
        future is queued. Queued stores must not be killed merely because
        another store is still running.
        """

        started = time.monotonic()

        results = {
            store: StoreRun(
                store=store
            )
            for store in self.stores
        }

        max_workers = min(
            2,
            max(
                1,
                len(self.stores),
            ),
        )

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="scenthunter-store",
        )

        futures = {
            executor.submit(
                self._run_one_store,
                store,
                query,
            ): store
            for store in self.stores
        }

        try:
            pending = set(futures)

            while pending:
                elapsed = (
                    time.monotonic()
                    - started
                )

                if elapsed >= self.global_timeout:
                    break

                done = {
                    future
                    for future in pending
                    if future.done()
                }

                for future in done:
                    pending.remove(future)

                    store = futures[future]

                    try:
                        results[store] = (
                            future.result()
                        )

                    except Exception as exc:
                        results[store] = StoreRun(
                            store=store,
                            status="error",
                            candidates=[],
                            error=(
                                f"{type(exc).__name__}: {exc}"
                            ),
                        )

                if pending:
                    time.sleep(0.05)

            # IMPORTANT:
            # Do NOT mark queued futures as individual store timeouts based on
            # submission time. Only the global deadline can terminate them.
            if pending:
                for future in pending:
                    store = futures[future]

                    results[store] = StoreRun(
                        store=store,
                        status="timeout",
                        candidates=[],
                        error=(
                            "global search window expired"
                        ),
                        elapsed=(
                            time.monotonic()
                            - started
                        ),
                    )

        finally:
            executor.shutdown(
                wait=False,
                cancel_futures=True,
            )

        return {
            "stores": results,
            "elapsed": (
                time.monotonic()
                - started
            ),
        }

    # ---------------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------------

    def _validate_batch(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Central validation wrapper.

        Only candidates passed to this method are validated.
        Already accepted candidates are never revalidated by later stores.
        """

        if not candidates:
            return []

        batch = [
            dict(item)
            for item in candidates
            if isinstance(item, dict)
        ]

        pre_rank = getattr(
            self.legacy,
            "_pre_rank_candidates",
            None,
        )

        if callable(pre_rank):
            try:
                batch = pre_rank(
                    batch,
                    query,
                )

            except TypeError:
                try:
                    batch = pre_rank(batch)
                except Exception:
                    pass

            except Exception:
                pass

        validator = getattr(
            self.legacy,
            "_validate_candidates_parallel",
            None,
        )

        if callable(validator):
            try:
                validated = validator(
                    batch,
                    query,
                )

            except TypeError:
                try:
                    validated = validator(
                        batch
                    )
                except Exception:
                    validated = []

            except Exception:
                validated = []

            if validated is None:
                return []

            try:
                return [
                    dict(x)
                    for x in validated
                    if isinstance(x, dict)
                ]
            except Exception:
                return []

        return [
            dict(x)
            for x in batch
            if isinstance(x, dict)
        ]

    # ---------------------------------------------------------------
    # FINAL RECONCILIATION
    # ---------------------------------------------------------------

    def _legacy_group_key(
        self,
        item: Dict[str, Any],
    ) -> Any:
        fn = getattr(
            self.legacy,
            "_result_group_key",
            None,
        )

        if callable(fn):
            try:
                return fn(item)
            except Exception:
                pass

        brand = self._norm(
            item.get("canonical_brand")
            or item.get("brand")
            or item.get("source_brand")
            or ""
        )

        variant = self._norm(
            item.get("catalog_variant")
            or item.get("canonical_name")
            or item.get("product_name")
            or item.get("title")
            or item.get("name")
            or ""
        )

        return (
            "fallback",
            brand,
            variant,
        )

    def _offer_identity(
        self,
        item: Dict[str, Any],
    ) -> Tuple[str, str, str]:
        store = self._store_name(item)

        size = self._size_ml(item)

        size_key = (
            f"{size:.4f}"
            if size is not None
            else ""
        )

        product_id = str(
            item.get("store_variant_id")
            or item.get("variant_id")
            or item.get("store_product_id")
            or item.get("product_id")
            or item.get("catalog_id")
            or item.get("gtin")
            or item.get("ean")
            or item.get("ean13")
            or item.get("sku")
            or ""
        ).strip().casefold()

        url = str(
            item.get("url")
            or ""
        ).strip().casefold()

        return (
            store,
            product_id or url,
            size_key,
        )

    def _reconcile_prepared(
        self,
        prepared: List[Dict[str, Any]],
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Lossless reconciliation.

        Every accepted candidate must remain represented in the final offers.
        """

        output = [
            dict(item)
            for item in prepared
            if isinstance(item, dict)
        ]

        family_index: Dict[
            Any,
            Dict[str, Any],
        ] = {}

        offer_keys = set()

        for product in output:
            offers = product.get(
                "offers"
            )

            if isinstance(
                offers,
                list,
            ):
                cleaned_offers = [
                    dict(offer)
                    for offer in offers
                    if isinstance(
                        offer,
                        dict,
                    )
                ]

                product["offers"] = (
                    cleaned_offers
                )

                product["offer_count"] = (
                    len(cleaned_offers)
                )

                for offer in cleaned_offers:
                    offer_keys.add(
                        self._offer_identity(
                            offer
                        )
                    )

            family_key = (
                self._legacy_group_key(
                    product
                )
            )

            if family_key not in family_index:
                family_index[
                    family_key
                ] = product

        for candidate in candidates:
            if not isinstance(
                candidate,
                dict,
            ):
                continue

            candidate = dict(candidate)

            key = self._offer_identity(
                candidate
            )

            if key in offer_keys:
                continue

            family_key = (
                self._legacy_group_key(
                    candidate
                )
            )

            target = family_index.get(
                family_key
            )

            if target is None:
                candidate_variant = self._norm(
                    candidate.get(
                        "catalog_variant"
                    )
                    or candidate.get(
                        "canonical_name"
                    )
                    or ""
                )

                candidate_brand = self._norm(
                    candidate.get(
                        "canonical_brand"
                    )
                    or candidate.get(
                        "brand"
                    )
                    or ""
                )

                if candidate_variant:
                    for existing in output:
                        existing_variant = self._norm(
                            existing.get(
                                "catalog_variant"
                            )
                            or existing.get(
                                "canonical_name"
                            )
                            or ""
                        )

                        existing_brand = self._norm(
                            existing.get(
                                "canonical_brand"
                            )
                            or existing.get(
                                "brand"
                            )
                            or ""
                        )

                        if (
                            candidate_variant
                            == existing_variant
                            and (
                                not candidate_brand
                                or not existing_brand
                                or candidate_brand
                                == existing_brand
                            )
                        ):
                            target = existing
                            break

            if target is not None:
                offers = target.get(
                    "offers"
                )

                if not isinstance(
                    offers,
                    list,
                ):
                    representative = dict(
                        target
                    )

                    representative.pop(
                        "offers",
                        None,
                    )

                    representative.pop(
                        "offer_count",
                        None,
                    )

                    offers = [
                        representative
                    ]

                    target["offers"] = (
                        offers
                    )

                offers.append(
                    candidate
                )

                target["offer_count"] = (
                    len(offers)
                )

                target["stores"] = list(
                    dict.fromkeys(
                        str(
                            offer.get(
                                "store"
                            )
                            or ""
                        ).strip()
                        for offer in offers
                        if str(
                            offer.get(
                                "store"
                            )
                            or ""
                        ).strip()
                    )
                )

                offer_keys.add(key)

                continue

            output.append(
                candidate
            )

            family_index[
                family_key
            ] = candidate

            offer_keys.add(key)

        return output

    def _prepare_final(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Prepare accepted candidates for public output.

        No validation is performed here.
        """

        if not candidates:
            return []

        prepare = getattr(
            self.legacy,
            "_prepare_final_results",
            None,
        )

        if not callable(prepare):
            return self._stable_results(
                candidates
            )

        try:
            prepared = prepare(
                candidates,
                query,
            )

        except TypeError:
            try:
                prepared = prepare(
                    candidates
                )
            except Exception:
                prepared = candidates

        except Exception:
            prepared = candidates

        if prepared is None:
            prepared = []

        if not isinstance(
            prepared,
            list,
        ):
            try:
                prepared = list(
                    prepared
                )
            except Exception:
                prepared = []

        prepared = [
            dict(x)
            for x in prepared
            if isinstance(x, dict)
        ]

        reconciled = (
            self._reconcile_prepared(
                prepared,
                candidates,
            )
        )

        for item in reconciled:
            offers = item.get(
                "offers"
            )

            if not isinstance(
                offers,
                list,
            ):
                continue

            offers = [
                dict(offer)
                for offer in offers
                if isinstance(
                    offer,
                    dict,
                )
            ]

            offers.sort(
                key=lambda offer: (
                    self._availability_rank(
                        offer
                    ),
                    self._price_value(
                        offer
                    ),
                    self._store_name(
                        offer
                    ),
                    str(
                        offer.get("url")
                        or ""
                    ),
                )
            )

            item["offers"] = offers
            item["offer_count"] = len(
                offers
            )

            item["stores"] = list(
                dict.fromkeys(
                    str(
                        offer.get(
                            "store"
                        )
                        or ""
                    ).strip()
                    for offer in offers
                    if str(
                        offer.get(
                            "store"
                        )
                        or ""
                    ).strip()
                )
            )

            if offers:
                representative = offers[0]

                for field in (
                    "store",
                    "shop",
                    "source",
                    "price",
                    "price_num",
                    "price_value",
                    "availability",
                    "stock_status",
                    "in_stock",
                    "url",
                    "image",
                    "size_ml",
                    "canonical_name",
                    "catalog_variant",
                    "canonical_brand",
                    "brand",
                    "name",
                    "title",
                ):
                    value = representative.get(
                        field
                    )

                    if value not in (
                        None,
                        "",
                        [],
                        {},
                    ):
                        item[field] = value

        return self._stable_results(
            reconciled
        )

    # ---------------------------------------------------------------
    # SYNCHRONOUS SEARCH
    # ---------------------------------------------------------------

    def search(
        self,
        query: str,
    ) -> Dict[str, Any]:
        text = str(
            query or ""
        ).strip()

        if not text:
            return {
                "query": "",
                "count": 0,
                "results": [],
                "comparisons": [],
                "errors": {},
            }

        run = self._run_stores(
            text
        )

        raw_pool: List[
            Dict[str, Any]
        ] = []

        accepted_pool: List[
            Dict[str, Any]
        ] = []

        errors: Dict[
            str,
            str,
        ] = {}

        accepted_keys = set()

        for store in self.stores:
            result: StoreRun = (
                run["stores"][store]
            )

            self._merge_unique(
                raw_pool,
                result.candidates,
                store,
            )

            if result.error:
                errors[store] = (
                    result.error
                )

            batch = []

            for candidate in result.candidates:
                if not isinstance(
                    candidate,
                    dict,
                ):
                    continue

                item = dict(candidate)

                if not item.get(
                    "store"
                ) and not item.get(
                    "shop"
                ):
                    item["store"] = store

                key = self._candidate_key(
                    item,
                    store,
                )

                if key in accepted_keys:
                    continue

                batch.append(item)

            validated = self._validate_batch(
                text,
                batch,
            )

            for candidate in validated:
                if not isinstance(
                    candidate,
                    dict,
                ):
                    continue

                item = dict(candidate)

                if not item.get(
                    "store"
                ) and not item.get(
                    "shop"
                ):
                    item["store"] = store

                key = self._candidate_key(
                    item,
                    store,
                )

                if key in accepted_keys:
                    continue

                accepted_keys.add(key)
                accepted_pool.append(
                    item
                )

        final = self._prepare_final(
            text,
            accepted_pool,
        )

        return {
            "query": text,
            "count": len(final),
            "results": final,
            "comparisons": [],
            "errors": errors,
        }

    # ---------------------------------------------------------------
    # BACKGROUND JOB
    # ---------------------------------------------------------------

    def run_job(
        self,
        job_id: str,
        query: str,
    ) -> None:
        jobs = getattr(
            self.legacy,
            "SEARCH_JOBS",
            None,
        )

        lock = getattr(
            self.legacy,
            "SEARCH_JOBS_LOCK",
            None,
        )

        if jobs is None:
            legacy_runner = getattr(
                self.legacy,
                "_run_search_job_legacy",
                None,
            )

            if callable(
                legacy_runner
            ):
                return legacy_runner(
                    job_id,
                    query,
                )

            raise RuntimeError(
                "SEARCH_JOBS is not available"
            )

        def update(
            payload: Dict[str, Any],
        ) -> None:
            if lock is not None:
                with lock:
                    job = jobs.get(
                        job_id
                    )

                    if job is not None:
                        job.update(
                            payload
                        )
            else:
                job = jobs.get(
                    job_id
                )

                if job is not None:
                    job.update(
                        payload
                    )

        def exists() -> bool:
            if lock is not None:
                with lock:
                    return (
                        job_id in jobs
                    )

            return job_id in jobs

        started = time.monotonic()

        raw_pool: List[
            Dict[str, Any]
        ] = []

        accepted_pool: List[
            Dict[str, Any]
        ] = []

        validated_keys = set()
        accepted_keys = set()

        store_status = {
            store: {
                "status": "pending",
                "count": 0,
            }
            for store in self.stores
        }

        errors: Dict[
            str,
            str,
        ] = {}

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
            # Two stores at a time.
            for wave_start in range(
                0,
                len(self.stores),
                2,
            ):
                wave = self.stores[
                    wave_start:
                    wave_start + 2
                ]

                update({
                    "phase": (
                        f"stores_{wave_start + 1}_"
                        f"{wave_start + len(wave)}"
                    ),
                    "status": "searching",
                    "store_status": {
                        **store_status,
                        **{
                            store: {
                                "status": "searching",
                                "count": 0,
                            }
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

                    for future in concurrent.futures.as_completed(
                        future_map
                    ):
                        store = future_map[
                            future
                        ]

                        try:
                            result: StoreRun = (
                                future.result()
                            )

                        except Exception as exc:
                            result = StoreRun(
                                store=store,
                                status="error",
                                candidates=[],
                                error=(
                                    f"{type(exc).__name__}: "
                                    f"{exc}"
                                ),
                            )

                        store_status[store] = {
                            "status": result.status,
                            "count": len(
                                result.candidates
                            ),
                            "elapsed": round(
                                result.elapsed,
                                3,
                            ),
                            "error": result.error,
                        }

                        if result.error:
                            errors[store] = (
                                result.error
                            )

                        new_candidates = []

                        existing_keys = {
                            self._candidate_key(
                                x,
                                store,
                            )
                            for x in raw_pool
                            if isinstance(
                                x,
                                dict,
                            )
                        }

                        for item in result.candidates:
                            if not isinstance(
                                item,
                                dict,
                            ):
                                continue

                            candidate = dict(
                                item
                            )

                            if not candidate.get(
                                "store"
                            ) and not candidate.get(
                                "shop"
                            ):
                                candidate[
                                    "store"
                                ] = store

                            key = (
                                self._candidate_key(
                                    candidate,
                                    store,
                                )
                            )

                            if key in existing_keys:
                                continue

                            existing_keys.add(key)
                            raw_pool.append(
                                candidate
                            )
                            new_candidates.append(
                                candidate
                            )

                        # Validate ONLY new candidates.
                        to_validate = []

                        for candidate in new_candidates:
                            key = (
                                self._candidate_key(
                                    candidate,
                                    store,
                                )
                            )

                            if key in validated_keys:
                                continue

                            validated_keys.add(
                                key
                            )

                            to_validate.append(
                                candidate
                            )

                        newly_accepted = (
                            self._validate_batch(
                                query,
                                to_validate,
                            )
                        )

                        for candidate in newly_accepted:
                            if not isinstance(
                                candidate,
                                dict,
                            ):
                                continue

                            item = dict(
                                candidate
                            )

                            if not item.get(
                                "store"
                            ) and not item.get(
                                "shop"
                            ):
                                item["store"] = store

                            key = (
                                self._candidate_key(
                                    item,
                                    store,
                                )
                            )

                            if key in accepted_keys:
                                continue

                            accepted_keys.add(
                                key
                            )

                            accepted_pool.append(
                                item
                            )

                        progress_results = (
                            self._prepare_final(
                                query,
                                list(
                                    accepted_pool
                                ),
                            )
                        )

                        update({
                            "results": progress_results,
                            "candidates": list(
                                raw_pool
                            ),
                            "errors": dict(
                                errors
                            ),
                            "store_status": dict(
                                store_status
                            ),
                            "phase": (
                                f"stores_{wave_start + 1}_"
                                f"{wave_start + len(wave)}"
                            ),
                            "status": "searching",
                            "completed": False,
                            "elapsed": round(
                                time.monotonic()
                                - started,
                                3,
                            ),
                        })

                        if not exists():
                            return

                if not exists():
                    return

            final_results = (
                self._prepare_final(
                    query,
                    list(
                        accepted_pool
                    ),
                )
            )

            update({
                "results": final_results,
                "candidates": list(
                    raw_pool
                ),
                "errors": dict(
                    errors
                ),
                "store_status": dict(
                    store_status
                ),
                "phase": "completed",
                "status": "completed",
                "completed": True,
                "elapsed": round(
                    time.monotonic()
                    - started,
                    3,
                ),
                "raw_candidate_count": len(
                    raw_pool
                ),
                "validated_candidate_count": len(
                    accepted_pool
                ),
            })

        except Exception as exc:
            update({
                "results": [],
                "errors": {
                    **errors,
                    "_search": (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                },
                "status": "error",
                "completed": True,
                "phase": "error",
                "elapsed": round(
                    time.monotonic()
                    - started,
                    3,
                ),
                "error": (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                "traceback": traceback.format_exc(
                    limit=8
                ),
            })
