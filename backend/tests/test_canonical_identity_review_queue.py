from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Base, Brand, CanonicalIdentityReview
from app.services.canonical_identity_review_queue import (
    enqueue_identity_review,
    resolve_identity_review,
)
from app.services.product_normalization import normalize_product


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_review_queue_is_durable_idempotent_and_does_not_touch_catalog():
    engine, session = _session()
    try:
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        first = enqueue_identity_review(
            session, product, reason="gtin_conflict",
            gtin="4006381333931", source_reference="retailer:item-42",
        )
        second = enqueue_identity_review(
            session, product, reason="gtin_conflict",
            gtin="4006381333931", source_reference="retailer:item-42",
        )
        assert first.id == second.id
        assert first.status == "pending"
        assert first.normalized_payload["brand"] == "christian dior"
        assert session.scalar(select(func.count()).select_from(CanonicalIdentityReview)) == 1
        assert session.scalar(select(func.count()).select_from(Brand)) == 0
    finally:
        session.close()
        engine.dispose()


def test_review_queue_resolution_is_audited_and_terminal():
    engine, session = _session()
    try:
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        item = enqueue_identity_review(session, product, reason="ambiguous_match")
        resolved = resolve_identity_review(
            session, item.id, outcome="rejected",
            reviewed_by="catalog-reviewer", notes="Conflicting product evidence",
        )
        assert resolved.status == "rejected"
        assert resolved.reviewed_by == "catalog-reviewer"
        assert resolved.reviewed_at is not None
        assert resolved.resolution_notes == "Conflicting product evidence"
        with pytest.raises(ValueError, match="already_resolved"):
            resolve_identity_review(
                session, item.id, outcome="approved", reviewed_by="another-reviewer"
            )
    finally:
        session.close()
        engine.dispose()


def test_review_queue_rejects_invalid_resolution_values():
    engine, session = _session()
    try:
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        item = enqueue_identity_review(session, product, reason="needs_review")
        with pytest.raises(ValueError, match="unsupported_review_outcome"):
            resolve_identity_review(
                session, item.id, outcome="merge", reviewed_by="reviewer"
            )
    finally:
        session.close()
        engine.dispose()
