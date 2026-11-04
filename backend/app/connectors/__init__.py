"""Universal retailer connector contracts and shared runtime helpers."""
from .deloox import DelooxConnector\nfrom .base import (
    ConnectorError, ConnectorQuarantined, OfferRecord, RateLimiter,
    RetryPolicy, StoreConnector, validate_offer,
)

__all__ = [
    "DelooxConnector", "ConnectorError", "ConnectorQuarantined", "OfferRecord", "RateLimiter",
    "RetryPolicy", "StoreConnector", "validate_offer",
]
