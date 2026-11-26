from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.offers.contracts import RetailerOffer
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository
from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from backend.scenthunter_next_engine.models import MatchStatus

from scrapers.parfumcity import scraper


class FakeResponse:
    def __init__(self, *, payload=None, text="", status_code=200):
        self._payload = payload
        self.text = text
        self.status_code = status_code

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

    def test_manufacturer_brand_and_canonical_name_ignore_retailer_vendor(self):
        product = dict(
            self.product,
            vendor="Parfum City",
            title="Liquid Brun Limited Edition Extrait French Avenue 150ML",
            variants=[dict(self.product["variants"][1], price="4099")],
        )
        html = (
            '<script type="application/ld+json">'
            + json.dumps({
                "@type": "Product",
                "offers": [{"price": "40.99", "priceCurrency": "EUR"}],
            })
            + "</script><p>Liquid Brun Limited Edition van French Avenue is een parfum.</p>"
        )
        records = scraper.extract_product_page(
            FakeSession(product, html),
            "https://www.parfumcity.nl/products/liquid-brun-limited-edition-french-avenue-100-ml",
        )
        self.assertEqual(records[0]["brand"], "French Avenue")
        self.assertEqual(records[0]["source"]["source_brand"], "French Avenue")
        self.assertEqual(records[0]["brand_source"], "product_description")
        self.assertEqual(records[0]["name"], "Liquid Brun Limited Edition Extrait de Parfum")
        self.assertEqual(records[0]["size_ml"], 150)
        self.assertEqual(records[0]["concentration"], "Extrait de Parfum")
        self.assertEqual(records[0]["price_num"], 40.99)

    def test_extracted_identity_matches_exact_canonical_150ml_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "product_catalog.json"
            catalog_path.write_text(
                json.dumps({
                    "products": [{
                        "product_id": "SH-LB-LE",
                        "brand_name": "French Avenue",
                        "canonical_name": "Liquid Brun Limited Edition",
                        "concentration": "Extrait de Parfum",
                    }],
                    "variants": [{
                        "product_id": "SH-LB-LE",
                        "variant_id": "VAR-LB-LE-150",
                        "size_ml": 150,
                    }],
                }),
                encoding="utf-8",
            )
            matcher = CanonicalMatcher(CatalogRepository.from_file(catalog_path))
            offer = RetailerOffer(
                retailer="parfumcity",
                raw_name="Liquid Brun Limited Edition Extrait de Parfum",
                brand_raw="French Avenue",
                size_ml=150,
            )
            result = matcher.match(offer)
            self.assertIs(result.status, MatchStatus.MATCHED, result.reason)
            self.assertEqual(result.canonical_product_id, "SH-LB-LE")
            self.assertEqual(result.canonical_variant_id, "VAR-LB-LE-150")

    def test_product_json_429_falls_back_to_exact_handle_search_json(self):
        class RateLimitedSession(FakeSession):
            def get(self, url, **kwargs):
                self.requested.append(url)
                if url.endswith(".js"):
                    return FakeResponse(text="rate limited", status_code=429)
                if url.endswith("/search.json"):
                    return FakeResponse(payload={"products": [self.product]})
                return FakeResponse(text=self.html)

        session = RateLimitedSession(self.product, self.html)
        records = scraper.extract_product_page(
            session,
            "https://www.parfumcity.nl/products/liquid-brun-french-avenue-100ml",
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["identity"]["store_variant_id"]["value"], 301)
        self.assertIn("https://www.parfumcity.nl/search.json", session.requested)

    def test_invalid_search_json_after_product_429_preserves_blocked_error(self):
        class InvalidSearchJsonResponse(FakeResponse):
            def json(self):
                raise json.JSONDecodeError("not JSON", "<html>challenge</html>", 0)

        class InvalidFallbackSession(FakeSession):
            def get(self, url, **kwargs):
                self.requested.append(url)
                if url.endswith(".js"):
                    return FakeResponse(text="rate limited", status_code=429)
                if url.endswith("/search.json"):
                    return InvalidSearchJsonResponse(text="<html>challenge</html>")
                return FakeResponse(text=self.html)

        session = InvalidFallbackSession(self.product, self.html)
        with self.assertRaises(scraper.StoreRequestError) as raised:
            scraper.extract_product_page(
                session,
                "https://www.parfumcity.nl/products/liquid-brun-french-avenue-100ml",
            )

        self.assertEqual(raised.exception.status, "blocked")
        self.assertIn("HTTP 429", str(raised.exception))
        self.assertIn("https://www.parfumcity.nl/search.json", session.requested)

    def test_empty_predictive_variants_do_not_short_circuit_full_search_json(self):
        class DiscoverySession:
            def __init__(self):
                self.requested = []

            def get(self, url, **kwargs):
                self.requested.append(url)
                if url.endswith("/search/suggest.json"):
                    return FakeResponse(payload={
                        "resources": {
                            "results": {
                                "products": [{
                                    "title": "Liquid Brun French Avenue 100ML",
                                    "vendor": "Parfum City",
                                    "url": "/products/liquid-brun-french-avenue-100ml",
                                    "variants": [],
                                }]
                            }
                        }
                    })
                if url.endswith("/search.json"):
                    return FakeResponse(payload={"products": [self_product]})
                raise AssertionError(f"Unexpected request: {url}")

        self_product = dict(
            self.product,
            title="Liquid Brun French Avenue 100ML",
            handle="liquid-brun-french-avenue-100ml",
            variants=[dict(self.product["variants"][0])],
        )
        session = DiscoverySession()
        urls, errors, verified, product_cache = scraper.discover(session, "Liquid Brun")
        self.assertTrue(verified)
        self.assertEqual(errors, [])
        self.assertEqual(len(urls), 1)
        self.assertEqual(
            product_cache[urls[0]]["variants"][0]["id"],
            self_product["variants"][0]["id"],
        )
        self.assertTrue(any(url.endswith("/search.json") for url in session.requested))

    def test_invalid_predictive_search_json_falls_back_to_full_search_json(self):
        class InvalidPredictiveResponse(FakeResponse):
            def json(self):
                raise json.JSONDecodeError("not JSON", "<html>blocked</html>", 0)

        self_product = dict(
            self.product,
            title="Liquid Brun French Avenue 100ML",
            handle="liquid-brun-french-avenue-100ml",
            variants=[dict(self.product["variants"][0])],
        )

        class DiscoverySession:
            def __init__(self):
                self.requested = []
                self.suggest_calls = 0

            def get(self, url, **kwargs):
                self.requested.append(url)
                if url.endswith("/search/suggest.json"):
                    self.suggest_calls += 1
                    return InvalidPredictiveResponse(text="<html>challenge</html>")
                if url.endswith("/search.json"):
                    return FakeResponse(payload={"products": [self_product]})
                raise AssertionError(f"Unexpected request: {url}")

        session = DiscoverySession()
        urls, errors, verified, product_cache = scraper.discover(session, "Liquid Brun")
        self.assertTrue(verified)
        self.assertEqual(len(urls), 1)
        self.assertEqual(product_cache[urls[0]]["variants"][0]["id"], 301)
        self.assertEqual(session.suggest_calls, 2)
        self.assertTrue(any(e["source"] == "shopify_predictive_search" for e in errors))
        self.assertTrue(any(url.endswith("/search.json") for url in session.requested))

    def test_non_retailer_product_urls_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "canonical HTTPS retailer host"):
            scraper.extract_product_page(
                FakeSession(self.product, self.html),
                "https://example.com/products/liquid-brun",
            )


if __name__ == "__main__":
    unittest.main()
