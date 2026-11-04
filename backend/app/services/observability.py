"""Process-local latency samples for operational diagnostics.

Samples are bounded and are not presented as durable fleet-wide telemetry.
"""
from __future__ import annotations
from collections import deque
from math import ceil
from threading import Lock
from time import perf_counter

_SEARCH_LATENCIES_MS = deque(maxlen=500)
_LOCK = Lock()

def record_search_latency(started_at: float) -> None:
    elapsed_ms = max(0.0, (perf_counter() - started_at) * 1000.0)
    with _LOCK:
        _SEARCH_LATENCIES_MS.append(elapsed_ms)

def search_latency_snapshot() -> dict:
    with _LOCK:
        values = sorted(_SEARCH_LATENCIES_MS)
    if not values:
        return {"available": False, "sample_count": 0, "p50_ms": None, "p95_ms": None,
                "scope": "single_application_process_last_500_searches"}
    def percentile(p: float) -> float:
        return round(values[max(0, ceil(p * len(values)) - 1)], 2)
    return {"available": True, "sample_count": len(values), "p50_ms": percentile(0.50),
            "p95_ms": percentile(0.95), "scope": "single_application_process_last_500_searches"}
