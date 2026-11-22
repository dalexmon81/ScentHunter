from __future__ import annotations

import unittest

from scripts.seed_postgres_fetch_queue_from_legacy_catalog import is_allowed_product_url


class LegacyCatalogQueueSeedUrlTests(unittest.TestCase):
    def test_accepts_expected_retailer_host_and_subdomains(self):
        self.assertTrue(is_allowed_product_url(
            "https://www.deloox.be/en/product/123", "www.deloox.be"
        ))
        self.assertTrue(is_allowed_product_url(
            "https://shop.www.deloox.be/product/123", "www.deloox.be"
        ))

    def test_rejects_lookalike_hosts_and_unexpected_domains(self):
        self.assertFalse(is_allowed_product_url(
            "https://evildeloox.be/product/123", "www.deloox.be"
        ))
        self.assertFalse(is_allowed_product_url(
            "https://www.deloox.be.evil.example/product/123", "www.deloox.be"
        ))
        self.assertFalse(is_allowed_product_url(
            "https://www.notino.fr/product/123", "www.deloox.be"
        ))

    def test_rejects_non_http_schemes_missing_hosts_and_credentials(self):
        for url in (
            "javascript:alert(1)",
            "file:///etc/passwd",
            "/relative/product",
            "https://user:pass@www.deloox.be/product/123",
            "https:///product/123",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_allowed_product_url(url, "www.deloox.be"))


if __name__ == "__main__":
    unittest.main()
