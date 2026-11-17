"""Opt-in catalog-first search endpoint."""
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db import database_url, make_engine
from app.search.catalog import catalog_status as read_catalog_status, search_catalog

router = APIRouter()


@lru_cache(maxsize=1)
def _engine():
    url = make_url(database_url())
    if url.get_backend_name() == "sqlite" and (
        not url.database or url.database == ":memory:" or not Path(url.database).is_file()
    ):
        raise HTTPException(status_code=503, detail="Canonical catalog is not provisioned")
    return make_engine()


@router.get("/api/catalog/search")
def catalog_search(q: str = Query(min_length=1, max_length=120)):
    with Session(_engine()) as session:
        return search_catalog(session, q.strip())


@router.get("/api/catalog/status")
def catalog_status():
    with Session(_engine()) as session:
        return read_catalog_status(session)
