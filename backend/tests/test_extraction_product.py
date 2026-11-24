from __future__ import annotations

import unittest

from app.extraction.product import extract_price_stock_observation, extract_product_record, extract_price_stock_observation


class FakeConnector:
    async def fetch_product(self, external_product_id):
        if external_product_id == "missing":
            return None
        return {"title": "Sauvage", "source": "fixture"}

    async def fetch_price_and_stock(self, external_product_id):
        return {"external_product_id": external_product_id, "price": "89.90", "currency": "EUR"}


class ExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_raw_evidence_and_adds_missing_external_id(self):
        result = await extract_product_record(FakeConnector(), "SKU-1")
        self.assertEqual(result.external_product_id, "SKU-1")
        self.assertEqual(result.raw_payload["external_product_id"], "SKU-1")
        self.assertEqual(result.raw_payload["title"], "Sauvage")
        self.assertEqual(result.raw_payload["source"], "fixture")

    async def test_missing_product_remains_none(self):
        result = await extract_product_record(FakeConnector(), "missing")
        self.assertIsNone(result)

    async def test_extracts_price_stock_evidence_without_rewriting_it(self):
        result = await extract_price_stock_observation(FakeConnector(), "SKU-1")
        self.assertEqual(result, {
            "external_product_id": "SKU-1", "price": "89.90", "currency": "EUR",
        })

    async def test_rejects_malformed_price_stock_observation(self):
        class BrokenConnector:
            async def fetch_price_and_stock(self, external_product_id):
                return ["not", "a", "mapping"]
        with self.assertRaisesRegex(TypeError, "must return a mapping"):
            await extract_price_stock_observation(BrokenConnector(), "SKU-1")

    async def test_rejects_empty_identifier_before_network_call(self):
        with self.assertRaisesRegex(ValueError, "external_product_id"):
            await extract_product_record(FakeConnector(), "  ")

    async def test_extracts_price_stock_observation_without_mutating_source(self):
        class PriceConnector:
            async def fetch_price_and_stock(self, external_product_id):
                return {"external_product_id": external_product_id, "price": "12.50"}
        result = await extract_price_stock_observation(PriceConnector(), "SKU-2")
        self.assertEqual(result, {"external_product_id": "SKU-2", "price": "12.50"})

    async def test_rejects_malformed_price_stock_observation(self):
        class BrokenConnector:
            async def fetch_price_and_stock(self, external_product_id):
                return None
        with self.assertRaisesRegex(TypeError, "must return a mapping"):
            await extract_price_stock_observation(BrokenConnector(), "SKU-2")

    async def test_rejects_malformed_connector_result(self):
        class BrokenConnector:
            async def fetch_product(self, external_product_id):
                return ["not", "a", "mapping"]
        with self.assertRaisesRegex(TypeError, "mapping or None"):
            await extract_product_record(BrokenConnector(), "SKU-1")


if __name__ == "__main__":
    unittest.main()
