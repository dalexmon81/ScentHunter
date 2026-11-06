"""Token-protected, read-only catalog operational overview."""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Header, HTTPException

from app.db import make_session_factory
from app.services.catalog_metrics import catalog_metrics_snapshot

router = APIRouter(prefix="/catalog/admin", tags=["catalog-admin"])


def _authorize_admin(token: str | None) -> None:
    expected = os.environ.get("SCENTHUNTER_CATALOG_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="catalog_admin_token_not_configured",
        )
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/overview")
def get_catalog_admin_overview(
    x_scenthunter_admin_token: str | None = Header(
        default=None, alias="X-ScentHunter-Admin-Token"
    ),
):
    """Return aggregate health metrics; never exposes raw offers or credentials."""
    _authorize_admin(x_scenthunter_admin_token)
    factory = make_session_factory()
    try:
        with factory() as session:
            return catalog_metrics_snapshot(session)
    finally:
        factory.kw["bind"].dispose()
