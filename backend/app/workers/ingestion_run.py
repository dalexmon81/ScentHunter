"""Backward-compatible imports for ingestion-run persistence helpers.

New code should import from app.repositories.ingestion_runs.
"""
from app.repositories.ingestion_runs import (
    finish_ingestion_run,
    record_ingestion_progress,
    start_ingestion_run,
)

__all__ = [
    "finish_ingestion_run", "record_ingestion_progress", "start_ingestion_run",
]
