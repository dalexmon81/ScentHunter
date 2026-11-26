from __future__ import annotations

import unittest
from unittest.mock import patch

from scrapers.orioudh import scraper


class FakeResponse:
    ok = True

    def __init__(self, text: str):
        self.text = text
        self.closed = False

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, html: str):
        self.html = html
        self.requested_urls = []

    def get(self, url, **kwargs):
        self.requested_urls.append(url)
        return FakeResponse(self.html)


class OrioudhCurrencyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.product = {
            "id": 900,
            "title": "Liquid Brun by French Avenue",
            "vendor": "French Avenue",
            "variants": [
                {"id": 101, "title": "100 ml", "sku": "ORI-101", "price": 3185, "available": True},
                {"id": 202, "title": "150 ml", "sku": "ORI-202", "price": 4490, "available": True},
            ],
        }

    def test_currency_is_evidenced_only_when_displayed_variant_price_matches(self):
        session = FakeSession(
            '<div class="price"><span class="price-item--regular">31,85 €</span></div>'
        )
        with patch.object(scraper, "_product_json", return_value=self.product):
            rows = scraper._extract_product(
                session,
                "https://orioudh.com/products/liquid-brun?variant=101",
                "Liquid Brun",
            )

        self.assertEqual(len(rows), 2)
        by_variant = {row["identity"]["store_variant_id"]["value"]: row for row in rows}
        self.assertEqual(
            by_variant[101]["raw_data"]["currency_evidence"],
            {
                "currency": "EUR",
                "source": "product_price_display",
                "displayed_price": "31,85 €",
                "matched_price": "31.85",
            },
        )
        self.assertIsNone(by_variant[202]["raw_data"]["currency_evidence"])
        self.assertIn("?variant=101", session.requested_urls[0])

    def test_currency_is_not_inferred_from_symbol_when_amount_does_not_match(self):
        session = FakeSession(
            '<div class="price"><span class="price-item--regular">44,90 €</span></div>'
        )
        with patch.object(scraper, "_product_json", return_value=self.product):
            rows = scraper._extract_product(
                session,
                "https://orioudh.com/products/liquid-brun?variant=101",
                "Liquid Brun",
            )

        self.assertTrue(all(row["raw_data"]["currency_evidence"] is None for row in rows))

    def test_non_default_selected_variant_gets_its_own_price_evidence(self):
        session = FakeSession(
            '<div class="price"><span class="price-item--regular">44,90 €</span></div>'
        )
        with patch.object(scraper, "_product_json", return_value=self.product):
            rows = scraper._extract_product(
                session,
                "https://orioudh.com/products/liquid-brun?variant=202",
                "Liquid Brun",
            )

        by_variant = {row["identity"]["store_variant_id"]["value"]: row for row in rows}
        self.assertEqual(
            by_variant[202]["raw_data"]["currency_evidence"]["matched_price"],
            "44.9",
        )
        self.assertIsNone(by_variant[101]["raw_data"]["currency_evidence"])

    def test_jsonld_currency_requires_matching_offer_price(self):
        payload = {
            "@type": "Product",
            "offers": {"price": "31.85", "priceCurrency": "EUR"},
        }
        self.assertEqual(
            scraper._jsonld_currency_evidence(payload, 31.85)["currency"],
            "EUR",
        )
        self.assertIsNone(scraper._jsonld_currency_evidence(payload, 44.90))


if __name__ == "__main__":
    unittest.main()
