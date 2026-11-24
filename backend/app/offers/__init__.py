"""Offer ingestion, persistence and publication boundaries."""
from .ingestion import ConnectorIngestionResult, persist_connector_record
from .persistence import (
    PromotionRejected, promote_offer, record_legacy_match, record_match,
    resolve_legacy_ids, stage_raw_offer,
)

__all__ = [
    "ConnectorIngestionResult", "persist_connector_record", "PromotionRejected",
    "promote_offer", "record_legacy_match", "record_match",
    "resolve_legacy_ids", "stage_raw_offer",
]
