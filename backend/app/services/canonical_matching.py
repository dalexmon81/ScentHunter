"""Backward-compatible imports for the canonical matching implementation.

New code should import from app.matching.canonical_matching.
"""
from app.matching.canonical_matching import (
    CanonicalMatch,
    CanonicalMatchResult,
    _gtin,
    _gtin_metadata_conflicts,
    resolve_canonical_variant,
)

__all__ = [
    "CanonicalMatch", "CanonicalMatchResult", "resolve_canonical_variant",
]
