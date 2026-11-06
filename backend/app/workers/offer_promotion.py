""""Controlled publication worker for already matched, validated offer evidence."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.models import IngestionRaw
from app.services.ingestion_persistence import PromotionRejected, promote_offer


def _source_capture_time(payload: dict) -> datetime | None:
    """Parse a retailer capture timestamp without silently accepting local time."""
    value = payload.get("capturedAt")
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("capturedAt must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("capturedAt must include a timezone offset")
    return parsed


def promote_matched_offers(session_factory, *, limit: int = 100) -> dict:
    """Publish eligible matched rows without allowing blocked rows to starve a batch.

    A blocked row remains matched for audit/review, with a promotion_blocked
    rejection_reason. After its raw evidence is corrected, an operator may
    clear that reason to make the row eligible for another promotion attempt.
    The caller owns the database target and this function never selects one.
    """
    if limit < 1 or limit > 5000:
        raise ValueError("limit_must_be_between_1_and_5000")
    session = session_factory()
    try:
        rows = session.scalars(
            select(IngestionRaw.id)
            .where(
                IngestionRaw.status == "matched",
                IngestionRaw.rejection_reason.is_(None),
            )
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
                    captured_at=_source_capture_time(payload),
                )
            except (PromotionRejected, InvalidOperation, TypeError, ValueError) as exc:
                raw.rejection_reason = f"promotion_blocked:{str(exc)[:450]}"
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
