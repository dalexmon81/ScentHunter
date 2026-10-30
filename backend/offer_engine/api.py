"""Read-only FastAPI surface for the isolated Offer Engine.

Mounting is controlled by SCENTHUNTER_OFFER_ENGINE_API_ENABLED. The route
opens only the dedicated Offer Engine database (SQLite on Fly by default, optional PostgreSQL) and never touches the legacy catalog DB.
"""
from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Query

from .read_repository import OfferReadRepository
from .runtime import connect_offer_engine_db, run_offer_engine


router = APIRouter()



@router.post("/offer-engine/search")
def refresh_and_search_offer_engine(
    query: str = Query(..., min_length=1, max_length=200),
    market: str | None = Query(default=None, min_length=2, max_length=3),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Refresh the requested retailer query, then return the verified current state."""
    if not query.strip():
        raise HTTPException(status_code=422, detail="query_must_not_be_empty")
    try:
        run_result = run_offer_engine(query)
        connection = connect_offer_engine_db()
        try:
            offers = OfferReadRepository(connection).search(
                query,
                market=market,
                limit=limit,
            )
        finally:
            connection.close()
        statuses = [item.status for item in run_result.connectors]
        overall = "failed" if statuses and all(status == "failed" for status in statuses) else (
            "partial" if any(status != "success" for status in statuses) else "success"
        )
        return {
            "status": overall,
            "refresh": asdict(run_result),
            "count": len(offers),
            "offers": offers,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="offer_engine_refresh_unavailable",
        ) from exc

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
