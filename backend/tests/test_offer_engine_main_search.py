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

    def test_search_flag_defaults_off(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(main._offer_engine_search_enabled())


if __name__ == "__main__":
    unittest.main()
