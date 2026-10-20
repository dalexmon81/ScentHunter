import unittest
from decimal import Decimal
from scenthunter_next_engine.models import Product, Variant, Offer, SourceObservation, price_to_minor_units


class ModelTests(unittest.TestCase):
    def test_minor_units(self):
        self.assertEqual(price_to_minor_units("129,99", "EUR"), 12999)
        self.assertEqual(price_to_minor_units("0.10", "EUR"), 10)

    def test_invalid_currency(self):
        with self.assertRaises(ValueError):
            price_to_minor_units("10", "EURO")

    def test_reject_non_http_url(self):
        with self.assertRaises(ValueError):
            Offer("o1", "v1", "shop", "javascript:alert(1)", 100, "EUR")

    def test_reject_float_minor_units(self):
        with self.assertRaises(ValueError):
            Offer("o1", "v1", "shop", "https://shop.example/p", 10.5, "EUR")

    def test_identity_consistency(self):
        p = Product("p1", "Brand", "Fragrance")
        v = Variant("v1", "p1", "edp", Decimal("100"))
        o = Offer("o1", "v2", "shop", "https://shop.example/p", 10000, "EUR")
        with self.assertRaises(ValueError):
            SourceObservation("shop", o.product_url, "2026-01-01T00:00:00+00:00",
                             p, v, o, "Brand Fragrance", "100", "v1", "trace")


if __name__ == "__main__":
    unittest.main()
