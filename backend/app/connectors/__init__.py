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
from .bplatz import BplatzConnector
from .deloox import DelooxConnector
from .easycosmetic import EasycosmeticConnector
from .notino import NotinoAffiliateFeedConnector
from .orioudh import OrioudhConnector
from .parfumcity import ParfumCityConnector
from .perfumemarket import PerfumeMarketConnector
from .parfumzentrum import ParfumzentrumConnector
from .sabina import SabinaConnector

__all__ = [
    "BplatzConnector",
    "ConnectorError",
    "ConnectorQuarantined",
    "DelooxConnector",
    "EasycosmeticConnector",
    "NotinoAffiliateFeedConnector",
    "OrioudhConnector",
    "ParfumCityConnector",
    "PerfumeMarketConnector",
    "OfferRecord",
    "RateLimiter",
    "RetryPolicy",
    "ParfumzentrumConnector",
    "SabinaConnector",
    "StoreConnector",
    "validate_offer",
]
