"""Isolated foundation for the ScentHunter offer platform.

This package is not wired into the public search route. Integrations are added
one retailer at a time behind shadow-mode validation.
"""

from .contracts import (
    AdapterRunResult,
    AdapterStatus,
    ProductCandidate,
    RawProductObservation,
    RetailerMarket,
)

__all__ = [
    "AdapterRunResult",
    "AdapterStatus",
    "ProductCandidate",
    "RawProductObservation",
    "RetailerMarket",
]
