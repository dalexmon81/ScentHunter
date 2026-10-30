from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend import main


class OfferEngineMainSearchTests(unittest.TestCase):
    def test_search_uses_offer_engine_only_when_explicitly_enabled(self):
        expected = {"query": "Liquid Brun", "results": [{"catalog_id": "SH-0031"}]}
        with (
            patch.dict(os.environ, {"SCENTHUNTER_OFFER_ENGINE_SEARCH_ENABLED": "1"}),
            patch.object(main, "_search_with_offer_engine", return_value=expected) as new_search,
            patch.object(main, "collect_store_reports_isolated", side_effect=AssertionError("legacy path called")),
        ):
            result = main.search_perfume("Liquid Brun")
        self.assertEqual(result, expected)
        new_search.assert_called_once_with("Liquid Brun")

    def test_offer_engine_rows_keep_sold_out_variant_in_legacy_ui_contract(self):
        from backend.offer_engine.runner import ConnectorRunResult, EngineRunResult
        row = {
            "product_id": "SH-0031",
            "brand": "French Avenue",
            "canonical_name": "Liquid Brun Limited Edition",
            "concentration": "Extrait de Parfum",
            "variant_id": "VAR-f5aff76b4bb5de8a",
            "size_ml": 150,
            "retailer_id": "deloox",
            "retailer_name": "Deloox",
            "market": "BE",
            "product_url": "https://www.deloox.be/produit/1385920/liquid-brun.html",
            "price": None,
            "currency": "EUR",
            "availability": "out_of_stock",
        }
        connection = type("FakeConnection", (), {"close": lambda self: None})()
        run_result = EngineRunResult([ConnectorRunResult("deloox", "success", listings_seen=1)])
        try:
            from offer_engine import runtime as runtime_module
            from offer_engine import read_repository as read_module
        except ModuleNotFoundError:
            from backend.offer_engine import runtime as runtime_module
            from backend.offer_engine import read_repository as read_module

        with (
            patch.object(runtime_module, "run_offer_engine", return_value=run_result),
            patch.object(runtime_module, "connect_offer_engine_db", return_value=connection),
            patch.object(read_module.OfferReadRepository, "search", return_value=[row]),
        ):
            result = main._search_with_offer_engine("Liquid Brun")

        self.assertEqual(result["count"], 1)
        offer = result["results"][0]["offers"][0]
        self.assertEqual(offer["variant_id"], "VAR-f5aff76b4bb5de8a")
        self.assertEqual(offer["availability"], "out_of_stock")
        self.assertIsNone(offer["price"])
        self.assertIsNone(offer["price_num"])
        self.assertTrue(offer["url"].startswith("https://www.deloox.be/"))

    def test_search_flag_defaults_off(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(main._offer_engine_search_enabled())


if __name__ == "__main__":
    unittest.main()
