"""Regression tests for retailer-offer deduplication across canonical catalog records."""

import unittest

from main import dedupe_results, result_key


class ResultDeduplicationTests(unittest.TestCase):
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

    def test_sabina_duplicate_without_price_is_deduplicated(self):
        first = {
            "store": "sabina", "url": "https://www.sabina.com/es/product/example-a",
            "name": "French Avenue Liquid Brun 100 ml", "size_ml": 100,
            "price": None, "price_num": None,
        }
        duplicate = {
            **first,
            "url": "https://www.sabina.com/es/product/example-b",
            "product_url": "https://www.sabina.com/es/product/example-b",
            "catalog_id": "canonical-b",
        }
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


if __name__ == "__main__":
    unittest.main()
