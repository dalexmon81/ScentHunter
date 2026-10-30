from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.offer_engine import api


class FakeConnection:
    def __init__(self):
        self.closed = False
    def close(self):
        self.closed = True


class OfferEngineApiTests(unittest.TestCase):
    def test_blank_query_is_rejected_as_client_error(self):
        with self.assertRaises(HTTPException) as caught:
            api.search_offer_engine("   ")
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail, "query_must_not_be_empty")

    def test_missing_database_schema_returns_service_unavailable(self):
        with patch.object(api, "connect_offer_engine_db", side_effect=RuntimeError("not migrated")):
            with self.assertRaises(HTTPException) as caught:
                api.search_offer_engine("Liquid Brun")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.detail, "offer_engine_database_unavailable")

    def test_search_returns_read_model_and_closes_connection(self):
        connection = FakeConnection()
        with (
            patch.object(api, "connect_offer_engine_db", return_value=connection),
            patch.object(api.OfferReadRepository, "search", return_value=[{"availability": "out_of_stock", "price": None}]) as search,
        ):
            result = api.search_offer_engine("Liquid Brun", market="BE", limit=20)
        search.assert_called_once_with("Liquid Brun", market="BE", limit=20)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["offers"][0]["availability"], "out_of_stock")
        self.assertIsNone(result["offers"][0]["price"])
        self.assertTrue(connection.closed)

    def test_database_failure_is_not_exposed_to_client(self):
        with (
            patch.object(api, "connect_offer_engine_db", side_effect=RuntimeError("secret host/password")),
        ):
            with self.assertRaises(HTTPException) as caught:
                api.search_offer_engine("Liquid Brun")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.detail, "offer_engine_database_unavailable")


if __name__ == "__main__":
    unittest.main()
