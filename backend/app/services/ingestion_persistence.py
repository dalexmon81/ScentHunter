"""Backward-compatible imports for offer lifecycle persistence.

New code should import from app.offers.persistence.
"""
from app.offers.persistence import (
    PromotionRejected,
    ResolvedLegacyIds,
    promote_offer,
    record_legacy_match,
    record_match,
    resolve_legacy_ids,
    stage_raw_offer,
)

__all__ = [
    "PromotionRejected", "ResolvedLegacyIds", "promote_offer",
    "record_legacy_match", "record_match", "resolve_legacy_ids", "stage_raw_offer",
]
