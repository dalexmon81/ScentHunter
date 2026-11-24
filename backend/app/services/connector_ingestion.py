"""Backward-compatible import for the shared offer ingestion workflow.

New code should import from app.offers.ingestion.
"""
from app.offers.ingestion import ConnectorIngestionResult, persist_connector_record

__all__ = ["ConnectorIngestionResult", "persist_connector_record"]
