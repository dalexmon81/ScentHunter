"""Batch worker for matching staged offers; publication is intentionally separate."""
from __future__ import annotations

from sqlalchemy import select

from app.models import IngestionRaw
from app.matching.offer_matcher import match_staged_offer


def match_pending_offers(session_factory, *, limit: int = 100) -> dict:
    if limit < 1 or limit > 5000:
        raise ValueError("limit_must_be_between_1_and_5000")
    session = session_factory()
    try:
        rows = session.scalars(
            select(IngestionRaw.id)
            .where(IngestionRaw.status.in_(( "pending", "unmatched" )))
            .order_by(IngestionRaw.created_at.asc())
            .limit(limit)
        ).all()
        counts = {"processed": 0, "matched": 0, "unmatched": 0}
        for raw_id in rows:
            decision = match_staged_offer(session, raw_id)
            counts["processed"] += 1
            counts[decision.status] += 1
        session.commit()
        return counts
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
