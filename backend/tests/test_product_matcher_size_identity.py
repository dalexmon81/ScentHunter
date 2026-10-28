"""Regression tests for explicit bottle-size conflicts in retailer offers."""
import unittest

from product_matcher import ProductMatcher


class ProductMatcherSizeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ProductMatcher(catalog=[], family_registry=[])

    def test_rejects_stale_100ml_title_for_150ml_url(self):
        offer = {
            "store": "deloox",
            "name": "French Avenue Liquid Brun 100 ml",
            "size_ml": 100,
            "url": "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html",
        }
        self.assertIsNone(self.matcher.match(offer, "Liquid Brun"))

    def test_rejects_100ml_title_when_structured_size_says_150ml(self):
        offer = {
            "store": "deloox",
            "name": "French Avenue Liquid Brun 100 ml",
            "size_ml": 150,
            "url": "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html",
        }
        self.assertIsNone(self.matcher.match(offer, "Liquid Brun"))


if __name__ == "__main__":
    unittest.main()
