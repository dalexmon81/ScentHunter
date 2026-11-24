"""Retailer connector interfaces and implementations.

Exports are lazy so importing a pure connector utility (for example, URL
validation used by read-only search) does not eagerly import retailer scrapers.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "ConnectorValidation": (".base", "ConnectorValidation"),
    "DiscoveredProduct": (".base", "DiscoveredProduct"),
    "StoreConnector": (".base", "StoreConnector"),
    "NotinoAffiliateFeedConnector": (".notino_feed", "NotinoAffiliateFeedConnector"),
    "LegacyScraperConnector": (".legacy_scrapers", "LegacyScraperConnector"),
    "build_legacy_connector": (".legacy_scrapers", "build_legacy_connector"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
