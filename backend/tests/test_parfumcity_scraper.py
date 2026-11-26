from __future__ import annotations

import json
import unittest

from scrapers.parfumcity import scraper


class FakeResponse:
    def __init__(self, *, payload=None, text=""):
        self._payload = payload
        self.text = text
        self.status_code = 200

    def json(self):
        return self._payload

    def close(self):
        pass


class FakeSession:
    def __init__(self, product, html):
        self.product = product
        self.html = html
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        if url.endswith(".js"):
            return FakeResponse(payload=self.product)
        return FakeResponse(text=self.html)


class ParfumCityScraperTests(unittest.TestCase):
    def setUp(self):
        self.product = {
            "id": 987654,
            "title": "Liquid Brun French Avenue 100ML",
            "vendor": "French Avenue",
            "handle": "liquid-brun-french-avenue-100ml",
            "variants": [
                {
                    "id": 301,
                    "sku": "PC-301",
                    "title": "100 ml",
                    "price": "2999",
                    "available": False,
                },
                {
                    "id": 302,
                    "sku": "PC-302",
                    "title": "150 ml",
                    "price": "3999",
                    "available": True,
                },
            ],
        }
        self.html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps({
                "@type": "Product",
                "offers": [
                    {"@type": "Offer", "price": "29.99", "priceCurrency": "EUR"}
                ],
            })
            + "</script></head><body>Liquid Brun</body></html>"
        )

    def test_normalization_and_query_matching_handle_compact_sizes(self):
        self.assertEqual(scraper.norm("100ML"), "100 ml")
        self.assertTrue(
            scraper.matches("Liquid Brun French Avenue 100ML", "Liquid Brun")
        )

    def test_extract_product_page_keeps_each_variant_and_currency_evidence(self):
        session = FakeSession(self.product, self.html)
        records = scraper.extract_product_page(
            session,
            "https://www.parfumcity.nl/en/products/liquid-brun-french-avenue-100ml",
            query="",
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(
            [row["identity"]["store_variant_id"]["value"] for row in records],
            [301, 302],
        )
        self.assertEqual(records[0]["price_num"], 29.99)
        self.assertEqual(records[0]["availability"], "out_of_stock")
        self.assertEqual(records[1]["availability"], "in_stock")
        self.assertEqual(
            records[0]["raw_data"]["currency_evidence"]["currency"], "EUR"
        )
        self.assertEqual(
            records[0]["raw_data"]["currency_evidence"]["matched_price"], "29.99"
        )
        self.assertIn(
            "https://www.parfumcity.nl/products/liquid-brun-french-avenue-100ml.js",
            session.requested,
        )

    def test_currency_evidence_is_not_assigned_when_price_does_not_match(self):
        html = (
            '<script type="application/ld+json">'
            + json.dumps({
                "@type": "Product",
                "offers": {"price": "35.00", "priceCurrency": "EUR"},
            })
            + "</script>"
        )
        session = FakeSession(self.product, html)
        records = scraper.extract_product_page(
            session,
            "https://www.parfumcity.nl/products/liquid-brun-french-avenue-100ml",
        )
        self.assertEqual(len(records), 2)
        self.assertNotIn("currency_evidence", records[0]["raw_data"])

    def test_non_retailer_product_urls_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "canonical HTTPS retailer host"):
            scraper.extract_product_page(
                FakeSession(self.product, self.html),
                "https://example.com/products/liquid-brun",
            )


if __name__ == "__main__":
    unittest.main()
