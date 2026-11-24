"""Verified offer staging, match audit and publication persistence."""
from .persistence import (
    PromotionRejected, promote_offer, record_legacy_match, record_match,
    resolve_legacy_ids, stage_raw_offer,
)

__all__ = [
    "PromotionRejected", "promote_offer", "record_legacy_match",
    "record_match", "resolve_legacy_ids", "stage_raw_offer",
]
