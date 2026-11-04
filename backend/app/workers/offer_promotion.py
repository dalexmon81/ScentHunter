"""Controlled publication worker for already matched, validated offer evidence."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.models import IngestionRaw
from app.services.ingestion_persistence import PromotionRejected, promote_offer


def promote_matched_offers(session_factory, *, limit: int = 100) -> dict:
    """Publish only rows with an existing canonical match and complete evidence.

    The caller supplies the session factory. This worker never opens the
    application's production database itself; transaction ownership is local
    to this invocation and failures roll back the batch.
    """
    if limit < 1 or limit > 5000:
        raise ValueError("limit_must_be_between_1_and_5000")
    session = session_factory()
    try:
        rows = session.scalars(
            select(IngestionRaw.id)
            .where(IngestionRaw.status == "matched")
            .order_by(IngestionRaw.created_at.asc())
            .limit(limit)
        ).all()
        counts = {"processed": 0, "published": 0, "blocked": 0}
        for raw_id in rows:
            raw = session.get(IngestionRaw, raw_id)
            payload = raw.raw_payload or {}
            counts["processed"] += 1
            try:
                price = Decimal(str(payload.get("price")))
                promote_offer(
                    session,
                    ingestion_raw_id=raw.id,
                    price=price,
                    currency=str(payload.get("currency") or ""),
                    url=str(payload.get("url") or ""),
                    availability=str(payload.get("availability") or ""),
                    source=str(payload.get("source") or ""),
                    confidence=raw.match_confidence,
                )
            except (PromotionRejected, InvalidOperation, TypeError, ValueError):
                # Keep the row matched so corrected evidence can be retried;
                # never weaken the publication contract to force a publish.
                counts["blocked"] += 1
                continue
            counts["published"] += 1
        session.commit()
        return counts
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
