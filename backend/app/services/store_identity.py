"""Canonical retailer-key normalization shared by legacy and catalog-first adapters.

Keep aliases here rather than duplicating retailer-name cleanup in API handlers,
workers or matching code. This function normalizes identity only; it does not
authorize or activate a retailer.
"""
from __future__ import annotations

_STORE_ALIASES = {
    "bplatz.de": "bplatz",
    "parfum city": "parfumcity",
    "parfum zentrum": "parfumzentrum",
    "parfum-zentrum": "parfumzentrum",
    "perfume market": "perfumemarket",
    "orioudh.com": "orioudh",
}


def normalize_store_key(value: object, fallback: object = "") -> str:
    """Return a stable store key from a retailer name, URL host or alias."""
    normalized = str(value or fallback or "").strip().lower()
    return _STORE_ALIASES.get(normalized, normalized)
