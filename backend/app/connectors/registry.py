"""Static capability inventory for the nine supported ScentHunter retailers.

This registry describes code readiness only. It does not seed stores, register
worker handlers, enable schedules, or assert live retailer health.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetailerCapability:
    key: str
    display_name: str
    adapter_module: str | None
    store_slug: str | None
    worker_stages: tuple[str, ...]
    readiness: str
    notes: str


# Keep this inventory explicit. Unknown store slugs stay None until the
# canonical store seed is reviewed; do not infer them from a domain or key.
RETAILER_CAPABILITIES: tuple[RetailerCapability, ...] = (
    RetailerCapability(
        key="bplatz",
        display_name="Bplatz",
        adapter_module="app.connectors.bplatz",
        store_slug="bplatz",
        worker_stages=("discover", "fetch", "refresh"),
        readiness="worker_registered",
        notes="Isolated Offer-First worker handlers are registered; scheduling remains disabled and requires explicit operator action.",
    ),
    RetailerCapability(
        key="deloox",
        display_name="Deloox",
        adapter_module="app.connectors.legacy_scrapers",
        store_slug="deloox-be",
        worker_stages=("discover", "fetch", "refresh"),
        readiness="worker_registered",
        notes="Thin wrapper around the preserved legacy scraper; discovery needs operator query seeds.",
    ),
    RetailerCapability(
        key="easycosmetic",
        display_name="Easycosmetic",
        adapter_module="app.connectors.legacy_scrapers",
        store_slug="easycosmetic-de",
        worker_stages=("discover", "fetch", "refresh"),
        readiness="worker_registered",
        notes="Thin wrapper around the preserved legacy scraper; discovery needs operator query seeds.",
    ),
    RetailerCapability(
        key="notino",
        display_name="Notino",
        adapter_module="app.connectors.notino_feed",
        store_slug="notino-fr",
        worker_stages=("discover", "fetch", "refresh"),
        readiness="worker_registered",
        notes="Authorized CJ/VIV feed adapter; discovery and refresh schedules require explicit opt-in.",
    ),
    RetailerCapability(
        key="orioudh",
        display_name="Orioudh",
        adapter_module="app.connectors.orioudh",
        store_slug=None,
        worker_stages=(),
        readiness="adapter_only",
        notes="Variant-aware Shopify adapter; worker dispatch and canonical store slug are not registered.",
    ),
    RetailerCapability(
        key="parfumcity",
        display_name="Parfumcity",
        adapter_module="app.connectors.parfumcity",
        store_slug=None,
        worker_stages=(),
        readiness="adapter_only",
        notes="Variant-aware Shopify adapter; worker dispatch and canonical store slug are not registered.",
    ),
    RetailerCapability(
        key="parfumzentrum",
        display_name="Parfum-Zentrum",
        adapter_module="app.connectors.legacy_scrapers",
        store_slug="parfumzentrum-de",
        worker_stages=("discover", "fetch", "refresh"),
        readiness="worker_registered",
        notes="Thin wrapper around the preserved legacy scraper; discovery needs operator query seeds.",
    ),
    RetailerCapability(
        key="perfumemarket",
        display_name="PerfumeMarket",
        adapter_module="app.connectors.perfumemarket",
        store_slug=None,
        worker_stages=(),
        readiness="adapter_only",
        notes="Fixture-tested adapter; not registered in worker dispatch.",
    ),
    RetailerCapability(
        key="sabina",
        display_name="Sabina",
        adapter_module="app.connectors.legacy_scrapers",
        store_slug="sabina-es",
        worker_stages=("discover", "fetch", "refresh"),
        readiness="worker_registered",
        notes="Thin wrapper around the preserved legacy scraper; discovery needs operator query seeds.",
    ),
)

EXPECTED_RETAILER_KEYS = frozenset({
    "bplatz",
    "deloox",
    "easycosmetic",
    "notino",
    "orioudh",
    "parfumcity",
    "parfumzentrum",
    "perfumemarket",
    "sabina",
})

_CAPABILITIES_BY_KEY = {item.key: item for item in RETAILER_CAPABILITIES}
if len(_CAPABILITIES_BY_KEY) != len(RETAILER_CAPABILITIES):
    raise RuntimeError("duplicate retailer capability key")
if frozenset(_CAPABILITIES_BY_KEY) != EXPECTED_RETAILER_KEYS:
    raise RuntimeError("retailer capability inventory does not match the required nine retailers")


def get_retailer_capability(key: str) -> RetailerCapability:
    """Return a known retailer's static capability record."""
    try:
        return _CAPABILITIES_BY_KEY[key.strip().lower()]
    except (AttributeError, KeyError):
        raise KeyError(f"unknown retailer capability: {key!r}") from None


def list_retailer_capabilities() -> tuple[RetailerCapability, ...]:
    """Return the stable, display-independent retailer inventory."""
    return RETAILER_CAPABILITIES
