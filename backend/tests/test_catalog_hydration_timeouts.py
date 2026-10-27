"""Regression tests for retailer-specific catalog hydration timeouts."""
import unittest
from unittest.mock import Mock, patch

import catalog_engine


class CatalogHydrationTimeoutTests(unittest.TestCase):
    def test_deloox_has_bounded_but_less_aggressive_read_timeout(self):
        self.assertEqual(
            catalog_engine._refresh_timeout_for_store("deloox"),
            (3.0, 8.0),
        )

    def test_easycosmetic_keeps_its_existing_long_timeout(self):
        self.assertEqual(
            catalog_engine._refresh_timeout_for_store("easycosmetic"),
            max(25, catalog_engine.REFRESH_TIMEOUT),
        )

    def test_deloox_lu_uses_browser_headers(self):
        response = Mock()
        response.status_code = 200
        response.url = "https://www.deloox.lu/"
        response.content = b"<html></html>"
        response.headers = {"Content-Type": "text/html"}
        session = Mock()
        session.get.return_value = response

        with patch.object(catalog_engine, "_session", return_value=session):
            result = catalog_engine._http_fetch("https://www.deloox.lu/", timeout=(3.0, 8.0))

        self.assertEqual(result["status"], 200)
        self.assertEqual(session.get.call_args.kwargs["headers"], catalog_engine.DELOOX_HEADERS)

    def test_other_stores_keep_the_default_refresh_timeout(self):
        self.assertEqual(
            catalog_engine._refresh_timeout_for_store("parfumzentrum"),
            catalog_engine.REFRESH_TIMEOUT,
        )


if __name__ == "__main__":
    unittest.main()
