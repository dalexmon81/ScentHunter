"""Read-only FastAPI surface for the isolated Offer Engine.

Mounting is controlled by SCENTHUNTER_OFFER_ENGINE_API_ENABLED. The route
opens only the dedicated PostgreSQL DSN and never touches the legacy SQLite DB.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query

from .read_repository import OfferReadRepository
from .runtime import connect_offer_engine_db


router = APIRouter()


@router.get("/offer-engine/search")
def search_offer_engine(
    query: str = Query(..., min_length=1, max_length=200),
    market: str | None = Query(default=None, min_length=2, max_length=3),
    limit: int = Query(default=50, ge=1, le=200),
):
    if not query.strip():
        raise HTTPException(status_code=422, detail="query_must_not_be_empty")

    connection = None
    try:
        connection = connect_offer_engine_db()
        offers = OfferReadRepository(connection).search(
            query,
            market=market,
            limit=limit,
        )
        return {"status": "ok", "count": len(offers), "offers": offers}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="offer_engine_database_unavailable",
        ) from exc
    finally:
        if connection is not None:
            connection.close()
