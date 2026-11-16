"""Perfumes-MEN remains fail-closed until written commercial crawling permission."""
import asyncio

import pytest

from app.connectors.base import ConnectorError
from app.connectors.perfumesmem import PerfumesMemConnector
from app.connectors.runtime_registry import build_connectors


def test_perfumesmem_is_registered_but_permission_blocked():
    connector = build_connectors()["perfumesmem"]
    assert isinstance(connector, PerfumesMemConnector)
    assert connector.source_kind == "permission_blocked"


def test_perfumesmem_live_operations_fail_closed_without_network_access():
    connector = PerfumesMemConnector()
    operations = (
        lambda: asyncio.run(connector.discover_products()),
        lambda: asyncio.run(connector.fetch_product("sku-1")),
        lambda: asyncio.run(connector.fetch_offers("sku-1")),
        lambda: asyncio.run(connector.fetch_price_and_stock("offer-1")),
        lambda: connector.parse_raw({"name": "Dior Sauvage"}),
        lambda: connector.validate_offer(None),
    )
    for operation in operations:
        with pytest.raises(ConnectorError, match="written_permission_required"):
            operation()
