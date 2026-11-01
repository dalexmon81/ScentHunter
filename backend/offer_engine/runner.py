"""Orchestrate independent retailer connectors without cross-retailer failure coupling.

Each retailer runs in its own worker with its own repository/DB connection.
The runner closes each connection when that connector finishes. Search waits
for a bounded interval; slower connector tasks may finish in the background
without holding back verified results from faster retailers.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Any, Iterable
import time

from .adapters import RetailerConnector
from .resolver import resolve_observation


@dataclass
class ConnectorRunResult:
    retailer: str
    status: str
    listings_seen: int = 0
    observations_written: int = 0
    offers_published: int = 0
    unresolved: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    unresolved_samples: list[dict[str, str]] = field(default_factory=list)
    discovery_details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineRunResult:
    connectors: list[ConnectorRunResult]

    @property
    def listings_seen(self) -> int:
        return sum(item.listings_seen for item in self.connectors)

    @property
    def observations_written(self) -> int:
        return sum(item.observations_written for item in self.connectors)

    @property
    def offers_published(self) -> int:
        return sum(item.offers_published for item in self.connectors)


class OfferEngineRunner:
    """Run retailers concurrently with bounded wait and isolated DB lifetimes."""

    def __init__(
        self,
        matcher: Any,
        repository_factory: Any,
        *,
        max_workers: int = 4,
        connector_timeout_seconds: float = 60.0,
    ):
        self.matcher = matcher
        self.repository_factory = repository_factory
        self.max_workers = max(1, int(max_workers))
        self.connector_timeout_seconds = max(0.01, float(connector_timeout_seconds))

    @staticmethod
    def _close_repository(repository: Any) -> None:
        close = getattr(repository, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _run_connector(self, connector: RetailerConnector, query: str) -> ConnectorRunResult:
        started = time.monotonic()
        result = ConnectorRunResult(retailer=str(connector.retailer), status="running")
        repository = None
        try:
            listings = list(connector.discover(query) or [])
            details = getattr(connector, "discovery_details", None)
            if isinstance(details, dict):
                result.discovery_details = dict(details)
            repository = self.repository_factory(connector)
        except Exception as exc:
            # Preserve source diagnostics even when discovery raises after
            # recording partial evidence (blocked endpoint, timeout, parser
            # failure). Without this, the public search can only say failed.
            details = getattr(connector, "discovery_details", None)
            if isinstance(details, dict):
                result.discovery_details = dict(details)
            result.status = "failed"
            result.errors.append(f"discovery/setup: {type(exc).__name__}: {exc}")
            result.elapsed = round(time.monotonic() - started, 3)
            self._close_repository(repository)
            return result

        try:
            for listing in listings:
                result.listings_seen += 1
                try:
                    if listing.retailer != connector.retailer:
                        raise ValueError("discovered listing belongs to another retailer")
                    observation = connector.observe(listing)
                    resolution = resolve_observation(listing, observation, self.matcher)
                    if resolution.status != "matched":
                        result.unresolved += 1
                        if len(result.unresolved_samples) < 12:
                            payload = observation.raw_payload if isinstance(observation.raw_payload, dict) else {}
                            page = payload.get("parsed_page") or payload.get("feed_record") or {}
                            if not isinstance(page, dict):
                                page = {}
                            attributes = page.get("attributes") or {}
                            identity = page.get("identity") or {}
                            if not isinstance(attributes, dict):
                                attributes = {}
                            if not isinstance(identity, dict):
                                identity = {}
                            size_fact = attributes.get("size_ml") or page.get("size_ml")
                            gtin_fact = identity.get("gtin") or page.get("gtin") or page.get("ean")
                            result.unresolved_samples.append({
                                "title": listing.raw_title,
                                "brand": listing.raw_brand,
                                "size_ml": listing.raw_size_ml,
                                "gtin": listing.raw_gtin,
                                "evidence_title": page.get("name") or page.get("title"),
                                "evidence_brand": page.get("brand"),
                                "evidence_size_ml": size_fact.get("value") if isinstance(size_fact, dict) else size_fact,
                                "evidence_gtin": gtin_fact.get("value") if isinstance(gtin_fact, dict) else gtin_fact,
                                "evidence_concentration": attributes.get("concentration") or page.get("concentration"),
                                "url": listing.product_url,
                                "status": resolution.status,
                                "reason": resolution.reason,
                            })
                    persisted = repository.record(listing, resolution.observation, match_status=resolution.status)
                    result.observations_written += 1
                    if persisted.get("published"):
                        result.offers_published += 1
                except Exception as exc:
                    result.errors.append(
                        f"{getattr(listing, 'product_url', '<unknown>')}: "
                        f"{type(exc).__name__}: {exc}"
                    )

            if result.errors and result.observations_written:
                result.status = "partial"
            elif result.errors:
                result.status = "failed"
            else:
                result.status = "success"
            return result
        finally:
            result.elapsed = round(time.monotonic() - started, 3)
            self._close_repository(repository)

    def run(self, connectors: Iterable[RetailerConnector], query: str) -> EngineRunResult:
        configured = list(connectors)
        if not configured:
            return EngineRunResult([])
        workers = min(self.max_workers, len(configured))
        started = time.monotonic()
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="offer-retailer")
        future_indexes = {
            pool.submit(self._run_connector, connector, query): index
            for index, connector in enumerate(configured)
        }
        completed: dict[int, ConnectorRunResult] = {}
        try:
            try:
                for future in as_completed(
                    future_indexes, timeout=self.connector_timeout_seconds
                ):
                    index = future_indexes[future]
                    try:
                        completed[index] = future.result()
                    except Exception as exc:
                        completed[index] = ConnectorRunResult(
                            retailer=str(configured[index].retailer),
                            status="failed",
                            errors=[f"connector: {type(exc).__name__}: {exc}"],
                            elapsed=round(time.monotonic() - started, 3),
                        )
            except FuturesTimeoutError:
                # A slow retailer must not hold back results already verified
                # by other stores. Its task keeps its own DB connection and
                # may publish a verified offer after this search has returned.
                pass
        finally:
            pool.shutdown(wait=False, cancel_futures=False)

        elapsed = round(time.monotonic() - started, 3)
        results = []
        for index, connector in enumerate(configured):
            if index not in completed:
                future = next(
                    future for future, future_index in future_indexes.items()
                    if future_index == index
                )
                if future.done():
                    try:
                        completed[index] = future.result()
                    except Exception as exc:
                        completed[index] = ConnectorRunResult(
                            retailer=str(connector.retailer),
                            status="failed",
                            errors=[f"connector: {type(exc).__name__}: {exc}"],
                            elapsed=elapsed,
                        )
                else:
                    status = "timeout" if future.running() else "deferred"
                    label = "timeout" if status == "timeout" else "deferred"
                    completed[index] = ConnectorRunResult(
                        retailer=str(connector.retailer),
                        status=status,
                        errors=[f"connector_{label}_after_{self.connector_timeout_seconds:g}s"],
                        elapsed=elapsed,
                    )
            results.append(completed[index])
        return EngineRunResult(results)
