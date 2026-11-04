"""Universal retailer connector contracts and shared runtime helpers."""
from .base import (
    ConnectorError, ConnectorQuarantined, OfferRecord, RateLimiter,
    RetryPolicy, StoreConnector, validate_offer,
)

__all__ = [
    "ConnectorError", "ConnectorQuarantined", "OfferRecord", "RateLimiter",
    "RetryPolicy", "StoreConnector", "validate_offer",
]
