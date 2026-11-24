"""Backward-compatible Bplatz Phase 2 adapter imports.

New code should import from app.offers.bplatz_adapter.
"""
from app.offers.bplatz_adapter import BplatzPhase2Result, persist_bplatz_record

__all__ = ["BplatzPhase2Result", "persist_bplatz_record"]
