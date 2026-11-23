"""Regression tests for the bounded PostgreSQL queue cutover."""

from datetime import datetime, timezone

import pytest

from app.workers.postgres_queue import queue_min_created_at


def test_queue_cutover_is_disabled_when_unconfigured():
    assert queue_min_created_at({}) is None


def test_queue_cutover_parses_utc_z_timestamp():
    assert queue_min_created_at({
        "SCENTHUNTER_QUEUE_MIN_CREATED_AT": "2026-11-23T07:00:00Z",
    }) == datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)


def test_queue_cutover_normalizes_explicit_timezone():
    assert queue_min_created_at({
        "SCENTHUNTER_QUEUE_MIN_CREATED_AT": "2026-11-23T08:00:00+01:00",
    }) == datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)


def test_queue_cutover_rejects_timezone_naive_timestamp():
    with pytest.raises(RuntimeError, match="must include a timezone"):
        queue_min_created_at({
            "SCENTHUNTER_QUEUE_MIN_CREATED_AT": "2026-11-23T07:00:00",
        })


def test_queue_cutover_rejects_invalid_timestamp():
    with pytest.raises(RuntimeError, match="ISO-8601 timestamp"):
        queue_min_created_at({
            "SCENTHUNTER_QUEUE_MIN_CREATED_AT": "not-a-date",
        })
