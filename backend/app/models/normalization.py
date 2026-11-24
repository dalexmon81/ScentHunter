"""Backward-compatible imports for canonical catalog normalization.

New code should import from :mod:`app.catalog.normalization`.
"""
from app.catalog.normalization import (
    CanonicalIdentity,
    build_identity,
    extract_concentration,
    extract_format_flags,
    extract_size_from_text,
    extract_size_ml,
    normalize_brand,
    normalize_fragrance_name,
    normalize_text,
)

__all__ = [
    "CanonicalIdentity", "build_identity", "extract_concentration",
    "extract_format_flags", "extract_size_from_text", "extract_size_ml",
    "normalize_brand", "normalize_fragrance_name", "normalize_text",
]
