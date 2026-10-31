from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.scrapers.deloox import scraper
from backend.offer_engine.connectors.deloox import DelooxConnector


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

    def test_offer_engine_verified_empty_search_skips_full_category_and_sitemap_fallbacks(self):
        def verified_empty(_session, _query, deadline=None):
            scraper._LAST_DISCOVERY_STATE = {
                "search_pages_ok": 1,
                "search_pages_failed": 0,
                "search_failure_reasons": {},
                "search_verified": True,
                "category_verified": False,
                "sitemap_verified": False,
                "technical_failure": False,
            }
            return []

        with (
            patch.object(scraper, "_discover_from_search", side_effect=verified_empty),
            patch.object(scraper, "_discover_from_categories", side_effect=AssertionError("category crawl must be skipped")),
            patch.object(scraper, "_sitemap_product_urls", side_effect=AssertionError("sitemap crawl must be skipped")),
        ):
            candidates = scraper._discover(
                FakeSession(),
                "Liquid Brun",
                deadline=None,
                max_candidates=8,
                include_fallback=False,
            )

        self.assertEqual(candidates, [])
        self.assertTrue(scraper._LAST_DISCOVERY_STATE["search_verified"])
        self.assertFalse(scraper._LAST_DISCOVERY_STATE["technical_failure"])

    def test_healthcheck_does_not_report_http_200_challenge_as_healthy(self):
        with patch(
            "backend.offer_engine.connectors.deloox.requests.get",
            return_value=FakeResponse(),
        ):
            health = DelooxConnector().healthcheck()
        self.assertFalse(health.ok)
        self.assertEqual(health.message, "client_challenge")


if __name__ == "__main__":
    unittest.main()
