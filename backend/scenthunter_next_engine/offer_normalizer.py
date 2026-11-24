"""Backward-compatible re-export for the canonical offer normalizer.

New code should import from app.offers.normalization.
"""
from app.offers.normalization import normalize_offer, normalize_offers

__all__ = ["normalize_offer", "normalize_offers"]
