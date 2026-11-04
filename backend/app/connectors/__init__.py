"""Universal retailer connector contracts and adapters."""
from .base import (
    ConnectorError,
    ConnectorQuarantined,
    OfferRecord,
    RateLimiter,
    RetryPolicy,
    StoreConnector,
    validate_offer,
)
from .deloox import DelooxConnector
from .notino import NotinoAffiliateFeedConnector

__all__ = [
    "ConnectorError",
    "ConnectorQuarantined",
    "DelooxConnector",
    "NotinoAffiliateFeedConnector",
    "OfferRecord",
    "RateLimiter",
    "RetryPolicy",
    "StoreConnector",
    "validate_offer",
]
