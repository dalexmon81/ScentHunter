"""Regression tests for retailer-offer deduplication across canonical catalog records."""

import os
import unittest
from unittest.mock import patch

import main
from main import _public_offer, dedupe_results, result_key


class ResultDeduplicationTests(unittest.TestCase):
    def test_public_offer_preserves_currency_and_cj_feed_source(self):
        offer = _public_offer({
            "catalog_id": "SH-0030",
            "name": "Liquid Brun",
            "brand": "French Avenue",
            "store": "notino",
            "price": 36.70,
            "price_num": 36.70,
            "currency": "EUR",
            "availability": "in_stock",
            "url": "https://www.anrdoezrs.net/click?url=https%3A%2F%2Fnotino.fr%2Fp",
            "source": "cj_notino_fr_feed",
        })

        self.assertEqual(offer["currency"], "EUR")
        self.assertEqual(offer["source"], "cj_notino_fr_feed")

    def test_same_retailer_url_is_deduplicated_across_catalog_ids(self):
        first = {
            "store": "sabina",
            "url": "https://www.sabina.com/es/product/example",
            "product_url": "https://www.sabina.com/es/product/example",
            "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum 100 ml",
            "size_ml": 100,
            "price_num": 38.90,
        }
        duplicate = {
            **first,
            "catalog_id": "canonical-b",
        }

        self.assertEqual(result_key(first), result_key(duplicate))
        self.assertEqual(dedupe_results([first, duplicate]), [first])

    def test_notino_same_gtin_collapses_legacy_and_cj_urls(self):
        legacy = {
            "store": "notino",
            "url": "https://www.notino.fr/french-avenue/liquid-brun/",
            "product_url": "https://www.notino.fr/french-avenue/liquid-brun/",
            "catalog_id": "SH-0030",
            "name": "Liquid Brun",
            "gtin": "6290360375694",
            "size_ml": 100,
            "price_num": 36.70,
        }
        cj = {
            **legacy,
            "url": "https://www.anrdoezrs.net/click?url=https%3A%2F%2Fwww.notino.fr%2Fp-16289640%2F",
            "product_url": "https://www.notino.fr/french-avenue/liquid-brun-eau-de-parfum-mixte/p-16289640/",
            "source": "cj_notino_fr_feed",
        }
        self.assertEqual(result_key(legacy), result_key(cj))
        self.assertEqual(dedupe_results([cj, legacy]), [cj])
        diagnostics = []
        self.assertEqual(dedupe_results([legacy, cj], diagnostics), [cj])
        self.assertEqual(diagnostics[0]["kept"]["url"], cj["url"])
        self.assertEqual(diagnostics[0]["dropped"]["url"], legacy["url"])

    def test_notino_distinct_gtins_remain_separate(self):
        first = {
            "store": "notino", "url": "https://www.notino.fr/p-100/",
            "gtin": "6290360375694", "size_ml": 100, "price_num": 36.70,
        }
        second = {
            **first, "url": "https://www.notino.fr/p-150/",
            "gtin": "6298042001831", "size_ml": 150, "price_num": 49.90,
        }
        self.assertNotEqual(result_key(first), result_key(second))
        self.assertEqual(len(dedupe_results([first, second])), 2)

    def test_distinct_sizes_of_same_retailer_url_are_preserved(self):
        first = {
            "store": "sabina",
            "url": "https://www.sabina.com/es/product/example",
            "product_url": "https://www.sabina.com/es/product/example",
            "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum",
            "size_ml": 50,
            "price_num": 29.90,
        }
        second = {
            **first,
            "catalog_id": "canonical-b",
            "size_ml": 100,
            "price_num": 38.90,
        }

        self.assertNotEqual(result_key(first), result_key(second))
        self.assertEqual(len(dedupe_results([first, second])), 2)

    def test_distinct_explicit_variant_selectors_are_preserved(self):
        first = {
            "store": "sabina",
            "url": "https://www.sabina.com/es/product/example#size-100-ml",
            "product_url": "https://www.sabina.com/es/product/example",
            "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum 100 ml",
            "size_ml": 100,
        }
        second = {
            **first,
            "url": "https://www.sabina.com/es/product/example#size-200-ml",
            "catalog_id": "canonical-b",
        }

        self.assertNotEqual(result_key(first), result_key(second))
        self.assertEqual(len(dedupe_results([first, second])), 2)

    def test_tracking_parameters_do_not_create_duplicate_easycosmetic_offers(self):
        first = {
            "store": "easycosmetic",
            "url": "https://www.easycosmetic.de/p/example?utm_source=google",
            "product_url": "https://www.easycosmetic.de/p/example?utm_source=google",
            "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum 100 ml",
            "size_ml": 100,
            "price_num": 25.99,
        }
        duplicate = {
            **first,
            "url": "https://easycosmetic.de/p/example?gclid=tracking",
            "product_url": "https://easycosmetic.de/p/example?gclid=tracking",
            "catalog_id": "canonical-b",
        }

        self.assertEqual(result_key(first), result_key(duplicate))
        self.assertEqual(len(dedupe_results([first, duplicate])), 1)

    def test_distinct_variant_query_parameters_are_not_collapsed(self):
        first = {
            "store": "easycosmetic",
            "url": "https://www.easycosmetic.de/p/example?variant=100",
            "product_url": "https://www.easycosmetic.de/p/example?variant=100",
            "name": "Example Eau de Parfum",
            "size_ml": 100,
        }
        second = {
            **first,
            "url": "https://www.easycosmetic.de/p/example?variant=200",
            "product_url": "https://www.easycosmetic.de/p/example?variant=200",
        }

        self.assertNotEqual(result_key(first), result_key(second))
        self.assertEqual(len(dedupe_results([first, second])), 2)


    def test_same_easycosmetic_name_size_price_different_urls_is_deduplicated(self):
        first = {
            "store": "easycosmetic", "url": "https://www.easycosmetic.de/p/example-a",
            "product_url": "https://www.easycosmetic.de/p/example-a", "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum 100 ml", "size_ml": 100, "price_num": 25.99,
        }
        duplicate = {**first, "url": "https://www.easycosmetic.de/p/example-b",
                     "product_url": "https://www.easycosmetic.de/p/example-b", "catalog_id": "canonical-b"}
        self.assertEqual(len(dedupe_results([first, duplicate])), 1)

    def test_same_sabina_name_size_price_different_urls_is_deduplicated(self):
        first = {
            "store": "sabina", "url": "https://www.sabina.com/es/product/example-a",
            "product_url": "https://www.sabina.com/es/product/example-a", "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum 100 ml", "size_ml": 100, "price_num": 38.90,
        }
        duplicate = {**first, "url": "https://www.sabina.com/es/product/example-b",
                     "product_url": "https://www.sabina.com/es/product/example-b", "catalog_id": "canonical-b"}
        self.assertEqual(len(dedupe_results([first, duplicate])), 1)

    def test_same_store_name_size_different_price_is_preserved(self):
        first = {"store": "sabina", "url": "https://www.sabina.com/es/product/example-a",
                 "name": "Example Eau de Parfum", "size_ml": 100, "price_num": 38.90}
        second = {**first, "url": "https://www.sabina.com/es/product/example-b", "price_num": 39.90}
        self.assertEqual(len(dedupe_results([first, second])), 2)


    def test_easycosmetic_same_price_deduplicates_when_size_metadata_missing(self):
        first = {"store": "easycosmetic", "url": "https://www.easycosmetic.de/p/a",
                 "name": "Example Eau de Parfum", "price_num": 25.99}
        duplicate = {"store": "easycosmetic", "url": "https://www.easycosmetic.de/p/b",
                     "name": "Example Eau de Parfum 100 ml", "price_num": 25.99}
        self.assertEqual(len(dedupe_results([first, duplicate])), 1)


    def test_notino_live_fallback_is_disabled_by_default(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(main, "CATALOG_ENGINE_AVAILABLE", True),
            patch.object(main, "catalog_search_local", lambda *args, **kwargs: []),
            patch(
                "app.services.notino_phase2_search.search_notino_phase2",
                return_value=[],
            ),
            patch(
                "main._collect_catalog_reports_isolated",
                return_value=[],
            ) as collect,
        ):
            main.collect_store_reports_isolated("Hawas", ["notino"])

        self.assertFalse(collect.call_args.kwargs["allow_live_fallback"])



if __name__ == "__main__":
    unittest.main()
