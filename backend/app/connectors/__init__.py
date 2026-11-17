"""Provider-neutral retailer connector contracts."""

from .base import (
    ConnectorError,
    ConnectorQuarantined,
    OfferRecord,
    RateLimiter,
    RetryPolicy,
    StoreConnector,
    capture_raw_page_artifact,
    is_currency_code,
    validate_offer,
    validate_offer_payload,
)

__all__ = [
    "ConnectorError",
    "ConnectorQuarantined",
    "OfferRecord",
    "RateLimiter",
    "RetryPolicy",
    "StoreConnector",
    "capture_raw_page_artifact",
    "is_currency_code",
    "validate_offer",
    "validate_offer_payload",
]
