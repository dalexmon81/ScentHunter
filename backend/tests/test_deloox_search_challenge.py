from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.scrapers.deloox import scraper


class FakeResponse:
    status_code = 200
    url = "https://www.deloox.be/chercher.html?q=Liquid+Brun"
    text = "<html><head><title>Client Challenge</title></head><body>challenge</body></html>"
    content = text.encode()


class FakeSession:
    def get(self, *_args, **_kwargs):
        return FakeResponse()


class DelooxChallengeDiscoveryTests(unittest.TestCase):
    def test_client_challenge_is_not_counted_as_verified_search(self):
        with (
            patch.object(
                scraper,
                "_search_endpoints",
                return_value=["https://www.deloox.be/chercher.html?q=Liquid+Brun"],
            ),
            patch.dict("sys.modules", {"playwright.sync_api": None}),
        ):
            candidates = scraper._discover_from_search(FakeSession(), "Liquid Brun")

        self.assertEqual(candidates, [])
        state = scraper._LAST_DISCOVERY_STATE
        self.assertFalse(state["search_verified"])
        self.assertEqual(state["search_pages_ok"], 0)
        self.assertEqual(state["search_pages_failed"], 1)
        self.assertEqual(state["search_failure_reasons"], {"client_challenge": 1})


if __name__ == "__main__":
    unittest.main()
