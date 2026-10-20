"""Small in-process metrics with bounded cardinality and no URL/secret labels."""
from __future__ import annotations
from collections import Counter
from threading import Lock
from time import monotonic


class PipelineMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._started = monotonic()
        self._counters: Counter[str] = Counter()
        self._durations_ms: dict[str, list[float]] = {}

    def increment(self, name: str, amount: int = 1) -> None:
        if not name or not name.replace("_", "").isalnum():
            raise ValueError("metric name must be a simple identifier")
        with self._lock:
            self._counters[name] += amount

    def observe_ms(self, stage: str, elapsed_ms: float) -> None:
        if not stage or not stage.replace("_", "").isalnum():
            raise ValueError("stage must be a simple identifier")
        value = max(0.0, float(elapsed_ms))
        with self._lock:
            values = self._durations_ms.setdefault(stage, [])
            values.append(value)
            if len(values) > 2048:
                del values[:len(values) - 2048]

    def snapshot(self) -> dict:
        with self._lock:
            durations = {}
            for stage, values in self._durations_ms.items():
                ordered = sorted(values)
                def percentile(p: float) -> float | None:
                    if not ordered:
                        return None
                    idx = min(len(ordered) - 1, int(round((len(ordered) - 1) * p)))
                    return round(ordered[idx], 2)
                durations[stage] = {
                    "count": len(ordered),
                    "p50_ms": percentile(0.50),
                    "p95_ms": percentile(0.95),
                }
            return {
                "uptime_seconds": round(monotonic() - self._started, 1),
                "counters": dict(self._counters),
                "durations": durations,
            }


metrics = PipelineMetrics()
