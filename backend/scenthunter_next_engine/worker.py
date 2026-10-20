"""Single-task worker entry point for the durable discovery/hydration queue."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Iterable

from .adapter import OfferPipeline
from .errors import AdapterFailure, ErrorKind
from .identity import DeterministicIdentityResolver
from .ingestion import IngestionService
from .queue import DurableTaskQueue, QueueTask
from .registry import AdapterRegistry
from .repository import SQLiteOfferRepository
from .telemetry import metrics


@dataclass(frozen=True)
class WorkerOutcome:
    status: str
    task_id: str | None
    store: str | None = None
    processed_urls: int = 0
    error_kind: str | None = None
    error: str | None = None


class QueueWorker:
    """Process one leased task; orchestration is injected, never hidden in search.

    `discovery_source` receives `(store, seed_url, limit)` and must return product
    URLs. No default discovery strategy is silently selected.
    """
    def __init__(self, *, queue: DurableTaskQueue, repository: SQLiteOfferRepository,
                 registry: AdapterRegistry, resolver=None,
                 discovery_source: Callable[[str, str, int], Iterable[str]] | None = None,
                 discovery_limit: int = 100):
        if discovery_limit < 1:
            raise ValueError("discovery_limit must be positive")
        self.queue = queue
        self.repository = repository
        self.registry = registry
        self.resolver = resolver or DeterministicIdentityResolver()
        self.discovery_source = discovery_source
        self.discovery_limit = discovery_limit

    def process_one(self, *, worker_id: str, lease_seconds: float = 90.0, now: float | None = None) -> WorkerOutcome:
        task = self.queue.claim(worker_id=worker_id, lease_seconds=lease_seconds, now=now)
        if task is None:
            return WorkerOutcome("idle", None)
        metrics.increment("worker_task_claimed")
        try:
            if task.task_type == "discovery":
                count = self._process_discovery(task, now=now)
                if not self.queue.complete(task.task_id, worker_id=worker_id, now=now):
                    return WorkerOutcome("lease_lost", task.task_id, task.store, count)
                metrics.increment("worker_discovery_done")
                return WorkerOutcome("done", task.task_id, task.store, count)
            outcome = self._process_hydration(task, now=now)
            if outcome.status in {"saved", "replay"}:
                if not self.queue.complete(task.task_id, worker_id=worker_id, now=now):
                    return WorkerOutcome("lease_lost", task.task_id, task.store, 1)
                metrics.increment("worker_hydration_done")
                return WorkerOutcome("done", task.task_id, task.store, 1)
            error_kind = outcome.error_kind or ErrorKind.UNKNOWN.value
            try:
                parsed_kind = ErrorKind(error_kind)
            except ValueError:
                parsed_kind = ErrorKind.UNKNOWN
            status = self.queue.fail(task.task_id, worker_id=worker_id, error_kind=parsed_kind,
                                     message=outcome.error or "ingestion failed", now=now)
            metrics.increment("worker_hydration_failed")
            return WorkerOutcome(status, task.task_id, task.store, 0, parsed_kind.value, outcome.error)
        except AdapterFailure as exc:
            status = self.queue.fail(task.task_id, worker_id=worker_id, error_kind=exc.kind,
                                     message=str(exc), retry_after_seconds=exc.retry_after_seconds, now=now)
            metrics.increment("worker_task_failed")
            return WorkerOutcome(status, task.task_id, task.store, 0, exc.kind.value, str(exc))
        except Exception as exc:
            kind = ErrorKind.UNKNOWN
            status = self.queue.fail(task.task_id, worker_id=worker_id, error_kind=kind,
                                     message=f"{type(exc).__name__}: {exc}", now=now)
            metrics.increment("worker_task_failed")
            return WorkerOutcome(status, task.task_id, task.store, 0, kind.value, str(exc))

    def _process_discovery(self, task: QueueTask, *, now: float | None) -> int:
        if self.discovery_source is None:
            raise AdapterFailure(ErrorKind.INVALID_PRODUCT, "no discovery source configured for discovery task")
        urls = self.discovery_source(task.store, task.url, self.discovery_limit)
        count = 0
        for url in urls:
            _, created = self.queue.enqueue(task_type="hydration", store=task.store, url=url,
                                             now=now, reopen_done=True)
            count += int(created)
        return count

    def _process_hydration(self, task: QueueTask, *, now: float | None):
        adapter = self.registry.get(task.store)
        service = IngestionService(OfferPipeline(adapter), self.resolver, self.repository)
        return service.ingest(task.url)
