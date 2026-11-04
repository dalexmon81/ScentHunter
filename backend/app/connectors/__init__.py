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
from .sabina import SabinaConnector

__all__ = [
    "ConnectorError",
    "ConnectorQuarantined",
    "DelooxConnector",
    "EasycosmeticConnector",
    "NotinoAffiliateFeedConnector",
    "OfferRecord",
    "RateLimiter",
    "RetryPolicy",
    "SabinaConnector",
    "StoreConnector",
    "validate_offer",
]
