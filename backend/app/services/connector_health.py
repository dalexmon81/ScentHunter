"""Backward-compatible imports for connector health tracking.

New code should import from app.monitoring.connector_health.
"""
from app.monitoring.connector_health import (
    record_connector_failure,
    record_connector_success,
    reinstate_connector,
)

__all__ = [
    "record_connector_failure", "record_connector_success", "reinstate_connector",
]
