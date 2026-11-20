from __future__ import annotations

import unittest
from typing import Any, Mapping, Sequence

from app.connectors import ConnectorValidation, DiscoveredProduct, StoreConnector


class FakeConnector(StoreConnector):
    store_key = "fixture-store"

    async def discover_products(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> Sequence[DiscoveredProduct]:
        return [DiscoveredProduct("sku-1", "https://shop.example/p/sku-1")]

    async def fetch_product(self, external_product_id: str) -> Mapping[str, Any] | None:
        return {"id": external_product_id, "title": "Fixture fragrance"}

    async def fetch_offers(self, product_key: str) -> Sequence[Mapping[str, Any]]:
        return [{"offer_id": product_key}]

    async def fetch_price_and_stock(self, offer_id: str) -> Mapping[str, Any]:
        return {
            "offer_id": offer_id,
            "product_url": "https://shop.example/p/sku-1",
            "price": "49.90",
            "currency": "EUR",
            "availability": "in_stock",
        }

    def parse_raw(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(raw)


class StoreConnectorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector = FakeConnector()

    def test_subclass_must_implement_all_io_methods(self) -> None:
        class IncompleteConnector(StoreConnector):
            store_key = "incomplete"

        # The abstract class cannot be instantiated without all six methods.
        with self.assertRaises(TypeError):
            IncompleteConnector()
        self.assertEqual(self.connector.store_key, "fixture-store")

    def test_discovered_product_requires_stable_id_and_http_url(self) -> None:
        product = DiscoveredProduct("sku-1", "https://shop.example/p/sku-1")
        self.assertEqual(product.external_product_id, "sku-1")
        with self.assertRaises(ValueError):
            DiscoveredProduct("", "https://shop.example/p/sku-1")
        with self.assertRaises(ValueError):
            DiscoveredProduct("sku-1", "/relative/path")

    def test_valid_offer_passes_common_publication_gate(self) -> None:
        result = self.connector.validate_offer({
            "product_url": "https://shop.example/p/sku-1",
            "price": "49.90",
            "currency": "EUR",
            "availability": "in_stock",
        })
        self.assertEqual(result, ConnectorValidation(valid=True))

    def test_missing_or_bad_fields_are_rejected_with_reasons(self) -> None:
        result = self.connector.validate_offer({
            "product_url": "javascript:alert(1)",
            "price": "0",
            "currency": "euro",
            "availability": None,
        })
        self.assertFalse(result.valid)
        self.assertEqual(
            set(result.errors),
            {
                "invalid_product_url",
                "price_must_be_positive",
                "invalid_currency",
                "availability_not_explicit",
            },
        )

    def test_invalid_price_strings_are_rejected(self) -> None:
        for value in (None, "unknown", "NaN", "-1"):
            with self.subTest(value=value):
                result = self.connector.validate_offer({
                    "product_url": "https://shop.example/p/sku-1",
                    "price": value,
                    "currency": "EUR",
                    "availability": "in_stock",
                })
                self.assertFalse(result.valid)


if __name__ == "__main__":
    unittest.main()
