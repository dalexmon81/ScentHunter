from time import perf_counter

from app.services.observability import record_search_latency, search_latency_snapshot


def test_search_latency_collector_reports_bounded_samples():
    before = search_latency_snapshot()["sample_count"]
    started = perf_counter() - 0.01
    record_search_latency(started)
    result = search_latency_snapshot()
    assert result["available"] is True
    assert result["sample_count"] == before + 1
    assert result["p50_ms"] >= 0
    assert result["p95_ms"] >= result["p50_ms"]
