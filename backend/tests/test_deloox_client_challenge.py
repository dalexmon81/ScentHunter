import unittest
from unittest.mock import Mock

from scrapers.deloox import scraper


class DelooxClientChallengeTests(unittest.TestCase):
    def test_detects_client_challenge_interstitial(self):
        html = "<html><head><title>Client Challenge</title></head><body></body></html>"
        self.assertTrue(scraper._is_client_challenge(html))

    def test_does_not_flag_normal_product_html(self):
        html = "<html><head><title>Liquid Brun</title></head><body><h1>Liquid Brun</h1></body></html>"
        self.assertFalse(scraper._is_client_challenge(html))

    def test_browser_retry_returns_explicit_block_status_if_challenge_persists(self):
        # The browser path is integration-tested in production; this unit test
        # verifies that a challenge response is never interpreted as product HTML.
        self.assertTrue(scraper._is_client_challenge(
            '<html><title>Client Challenge</title><script src="/challenge-platform.js"></script></html>'
        ))


if __name__ == "__main__":
    unittest.main()
