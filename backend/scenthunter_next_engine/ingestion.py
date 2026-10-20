from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
import uuid
from time import perf_counter

from .telemetry import metrics

from .adapter import OfferPipeline
from .errors import AdapterFailure, ErrorKind, is_retryable
from .models import RetailerOfferRecord, SourceObservation
from .repository import SQLiteOfferRepository


class IdentityResolver(Protocol):
    """Resolve retailer facts to canonical Product and Variant entities."""

    def resolve(self, record: RetailerOfferRecord) -> SourceObservation:
        ...


@dataclass(frozen=True)
class IngestionOutcome:
    status: str  # saved | replay | failed
    source_url: str
    trace_id: str
    error_kind: str | None = None
    error: str | None = None


class IngestionService:
    """Orchestrate adapter -> identity resolution -> transactional persistence."""

    def __init__(self, pipeline: OfferPipeline, resolver: IdentityResolver,
                 repository: SQLiteOfferRepository):
        self.pipeline = pipeline
        self.resolver = resolver
        self.repository = repository

    def ingest(self, url: str) -> IngestionOutcome:
        trace_id = uuid.uuid4().hex
        started = perf_counter()
        metrics.increment("ingestion_started")
        try:
            record = self.pipeline.observe(url)
            trace_id = record.trace_id
            observation = self.resolver.resolve(record)
            if not isinstance(observation, SourceObservation):
                raise AdapterFailure(ErrorKind.INVALID_PRODUCT,
                                     "identity resolver did not return SourceObservation")
            if observation.store != record.store:
                raise AdapterFailure(ErrorKind.INVALID_PRODUCT,
                                     "resolved observation store differs from retailer record")
            if observation.source_url != record.source_url:
                raise AdapterFailure(ErrorKind.INVALID_URL,
                                     "resolved observation source URL differs from retailer record")
            if observation.offer.product_url != record.product_url:
                raise AdapterFailure(ErrorKind.INVALID_URL,
                                     "resolved offer URL differs from retailer record")
        except AdapterFailure as exc:
            self.repository.record_failure(
                store=self.pipeline.adapter.store_key,
                source_url=url,
                kind=exc.kind.value,
                message=str(exc),
                retryable=is_retryable(exc.kind),
                occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                trace_id=trace_id,
            )
            metrics.increment("ingestion_failed")
            metrics.increment(f"failure_{exc.kind.value}")
            metrics.observe_ms("ingestion", (perf_counter() - started) * 1000)
            return IngestionOutcome("failed", url, trace_id, exc.kind.value, str(exc))
        except Exception as exc:
            # Unexpected resolver errors are recorded and surfaced as a failed
            # observation; database exceptions below are intentionally outside
            # this catch so infrastructure failures cannot masquerade as scrape failures.
            failure = AdapterFailure(ErrorKind.UNKNOWN,
                                     f"identity resolver raised {type(exc).__name__}: {exc}")
            self.repository.record_failure(
                store=self.pipeline.adapter.store_key,
                source_url=url,
                kind=failure.kind.value,
                message=str(failure),
                retryable=is_retryable(failure.kind),
                occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                trace_id=trace_id,
            )
            metrics.increment("ingestion_failed")
            metrics.increment("failure_unknown")
            metrics.observe_ms("ingestion", (perf_counter() - started) * 1000)
            return IngestionOutcome("failed", url, trace_id, failure.kind.value, str(failure))

        saved = self.repository.save_observation(observation)
        metrics.increment("ingestion_saved" if saved else "ingestion_replay")
        metrics.observe_ms("ingestion", (perf_counter() - started) * 1000)
        return IngestionOutcome("saved" if saved else "replay", url, trace_id)
