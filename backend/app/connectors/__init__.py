"""Retailer connector interfaces and implementations."""

from .base import ConnectorValidation, DiscoveredProduct, StoreConnector
from .notino_feed import NotinoAffiliateFeedConnector
from .legacy_scrapers import LegacyScraperConnector, build_legacy_connector
from .bplatz import BplatzConnector, build_bplatz_connector
from .perfumemarket import PerfumeMarketConnector, build_perfumemarket_connector

__all__ = [
    "ConnectorValidation",
    "DiscoveredProduct",
    "StoreConnector",
    "NotinoAffiliateFeedConnector",
    "LegacyScraperConnector",
    "build_legacy_connector",
    "BplatzConnector",
    "build_bplatz_connector",
    "PerfumeMarketConnector",
    "build_perfumemarket_connector",
]
