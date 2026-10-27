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


if __name__ == "__main__":
    unittest.main()
