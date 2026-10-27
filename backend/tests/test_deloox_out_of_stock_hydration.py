"""Regression tests for verified out-of-stock catalog observations."""
import unittest
from unittest.mock import patch

import catalog_engine


class DelooxOutOfStockHydrationTests(unittest.TestCase):
    def test_verified_out_of_stock_without_price_completes_hydration(self):
        task = {"store": "deloox", "url": "https://www.deloox.be/produit/1385920/example.html"}
        item = {
            "name": "French Avenue Liquid Brun Extrait de Parfum Limited Edition",
            "size_ml": 150,
            "price_num": None,
            "availability": "out_of_stock",
            "available": False,
        }

        with (
            patch.object(catalog_engine, "_foreground_search_running", return_value=False),
            patch.object(catalog_engine, "refresh_url", return_value=item),
            patch.object(catalog_engine, "_queue_mark_done") as mark_done,
            patch.object(catalog_engine, "_queue_mark_error") as mark_error,
        ):
            self.assertTrue(catalog_engine._hydrate_one_task(task))

        mark_done.assert_called_once_with(task)
        mark_error.assert_not_called()

    def test_unknown_availability_without_price_stays_retryable(self):
        task = {"store": "deloox", "url": "https://www.deloox.be/produit/1385920/example.html"}
        item = {
            "name": "French Avenue Liquid Brun Extrait de Parfum Limited Edition",
            "size_ml": 150,
            "price_num": None,
            "availability": "unknown",
            "available": None,
        }

        with (
            patch.object(catalog_engine, "_foreground_search_running", return_value=False),
            patch.object(catalog_engine, "refresh_url", return_value=item),
            patch.object(catalog_engine, "_queue_mark_done") as mark_done,
            patch.object(catalog_engine, "_queue_mark_error") as mark_error,
        ):
            self.assertFalse(catalog_engine._hydrate_one_task(task))

        mark_done.assert_not_called()
        mark_error.assert_called_once_with(task, "refresh_missing_explicit_price")


if __name__ == "__main__":
    unittest.main()
