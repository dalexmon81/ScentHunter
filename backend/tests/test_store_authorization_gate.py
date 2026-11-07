from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.workers.ingestion_tasks import _require_store_authorization


def test_store_authorization_fails_closed_without_approved_record():
    session = Mock()
    session.scalar.return_value = None
    store = SimpleNamespace(id="store-id", slug="deloox")

    with pytest.raises(PermissionError, match="store_collection_not_authorized"):
        _require_store_authorization(session, store, "offer_data")


def test_store_authorization_requires_explicit_scope_and_reference():
    grant = SimpleNamespace(
        scopes=["product_discovery"],
        authorization_reference="ticket-123",
    )
    session = Mock()
    session.scalar.return_value = grant
    store = SimpleNamespace(id="store-id", slug="deloox")

    with pytest.raises(PermissionError, match="scope_missing"):
        _require_store_authorization(session, store, "price_stock")

    with pytest.raises(PermissionError, match="reference_mismatch"):
        _require_store_authorization(
            session, store, "product_discovery", "different-reference"
        )


def test_store_authorization_accepts_explicitly_granted_scope():
    grant = SimpleNamespace(
        scopes=["product_discovery", "offer_data"],
        authorization_reference="written-consent-2026-01",
    )
    session = Mock()
    session.scalar.return_value = grant
    store = SimpleNamespace(id="store-id", slug="deloox")

    result = _require_store_authorization(
        session, store, "offer_data", "written-consent-2026-01"
    )

    assert result is grant
