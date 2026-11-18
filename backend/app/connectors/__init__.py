"""Retailer connector interfaces and implementations."""

from .base import ConnectorValidation, DiscoveredProduct, StoreConnector
from .notino_feed import NotinoAffiliateFeedConnector

__all__ = [
    "ConnectorValidation",
    "DiscoveredProduct",
    "StoreConnector",
    "NotinoAffiliateFeedConnector",
]
