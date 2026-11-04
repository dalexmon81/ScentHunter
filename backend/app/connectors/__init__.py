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
from .bplatz import BplatzConnector\nfrom .deloox import DelooxConnector
from .easycosmetic import EasycosmeticConnector
from .notino import NotinoAffiliateFeedConnector
from .orioudh import OrioudhConnector\nfrom .parfumcity import ParfumCityConnector\nfrom .parfumemarket import PerfumeMarketConnector\nfrom .parfumzentrum import ParfumzentrumConnector
from .sabina import SabinaConnector

__all__ = [
    "BplatzConnector",\n    "ConnectorError",
    "ConnectorQuarantined",
    "DelooxConnector",
    "EasycosmeticConnector",
    "NotinoAffiliateFeedConnector",\n    "OrioudhConnector",\n    "ParfumCityConnector",\n    "PerfumeMarketConnector",
    "OfferRecord",
    "RateLimiter",
    "RetryPolicy",
    "ParfumzentrumConnector",
    "SabinaConnector",
    "StoreConnector",
    "validate_offer",
]
