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
from .easycosmetic import EasycosmeticConnector
from .notino import NotinoAffiliateFeedConnector

__all__ = [
    "ConnectorError",
    "ConnectorQuarantined",
    "DelooxConnector",
    "EasycosmeticConnector",
    "NotinoAffiliateFeedConnector",
    "OfferRecord",
    "RateLimiter",
    "RetryPolicy",
    "StoreConnector",
    "validate_offer",
]
