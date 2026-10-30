"""Orchestrate independent retailer connectors without cross-retailer failure coupling.

Each retailer runs in its own worker with its own repository/DB connection.
The runner deliberately owns no connection lifecycle; callers create and close
those connections after all workers have completed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Iterable

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
    unresolved_samples: list[dict[str, str]] = field(default_factory=list)


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
    """Run retailers concurrently while retaining isolated failure boundaries."""

    def __init__(self, matcher: Any, repository_factory: Any, *, max_workers: int = 4):
        self.matcher = matcher
        self.repository_factory = repository_factory
        self.max_workers = max(1, int(max_workers))

    def _run_connector(self, connector: RetailerConnector, query: str) -> ConnectorRunResult:
        result = ConnectorRunResult(retailer=str(connector.retailer), status="running")
        try:
            repository = self.repository_factory(connector)
            listings = list(connector.discover(query) or [])
        except Exception as exc:
            result.status = "failed"
            result.errors.append(f"discovery: {type(exc).__name__}: {exc}")
            return result

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

    def run(self, connectors: Iterable[RetailerConnector], query: str) -> EngineRunResult:
        configured = list(connectors)
        if not configured:
            return EngineRunResult([])
        workers = min(self.max_workers, len(configured))
        # Futures are collected in registry order so API output remains stable,
        # while network-bound retailer work overlaps instead of serializing.
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="offer-retailer") as pool:
            futures = [pool.submit(self._run_connector, connector, query) for connector in configured]
            results = [future.result() for future in futures]
        return EngineRunResult(results)
