import unittest
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scrapers.deloox.scraper import _product


class DelooxOutOfStockNoPriceTests(unittest.TestCase):
    def test_limited_edition_150ml_is_preserved_without_inventing_price(self):
        url = (
            "https://www.deloox.be/produit/1385920/"
            "french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
        )
        name = "French Avenue Liquid Brun Extrait de Parfum Limited Edition"
        jsonld = {
            "@type": "Product",
            "name": name,
            "brand": {"@type": "Brand", "name": "French Avenue"},
            "size": {"@type": "QuantitativeValue", "value": 150, "unitText": "ml"},
            "offers": {
                "@type": "Offer",
                "availability": "https://schema.org/OutOfStock",
                "priceCurrency": "EUR",
            },
        }

        result = _product(
            url,
            '<html><body><h1>French Avenue Liquid Brun Extrait de Parfum Limited Edition</h1></body></html>',
            "Liquid Brun Limited Edition 150 ml",
            jsonld_data=jsonld,
            h1_override=name,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["url"], url)
        self.assertEqual(result["name"], name)
        self.assertEqual(result["attributes"]["size_ml"]["value"], 150)
        self.assertIsNone(result["offer"]["price"])
        self.assertEqual(result["offer"]["availability"], "out_of_stock")
        self.assertIsNone(result["price"])
        self.assertFalse(result["available"])

    def test_in_stock_product_without_price_is_still_rejected(self):
        url = (
            "https://www.deloox.be/produit/1385920/"
            "french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
        )
        jsonld = {
            "@type": "Product",
            "name": "French Avenue Liquid Brun Extrait de Parfum Limited Edition",
            "brand": {"@type": "Brand", "name": "French Avenue"},
            "size": {"@type": "QuantitativeValue", "value": 150, "unitText": "ml"},
            "offers": {
                "@type": "Offer",
                "availability": "https://schema.org/InStock",
                "priceCurrency": "EUR",
            },
        }

        result = _product(
            url,
            "<html><body>French Avenue Liquid Brun</body></html>",
            "Liquid Brun Limited Edition 150 ml",
            jsonld_data=jsonld,
            h1_override="French Avenue Liquid Brun Extrait de Parfum Limited Edition",
        )

        self.assertIsNone(result)


    def test_list_price_is_discarded_when_jsonld_marks_product_out_of_stock(self):
        url = (
            "https://www.deloox.be/produit/1385920/"
            "french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
        )
        name = "French Avenue Liquid Brun Extrait de Parfum Limited Edition"
        jsonld = {
            "@type": "Product",
            "name": name,
            "brand": {"@type": "Brand", "name": "French Avenue"},
            "gtin13": "6298042001831",
            "sku": "1385920",
            "size": {"@type": "QuantitativeValue", "value": 150, "unitText": "ml"},
            "offers": {
                "@type": "Offer",
                "availability": "https://schema.org/OutOfStock",
                "price": "44.79",
                "priceCurrency": "EUR",
            },
        }
        result = _product(
            url,
            "<html><body><h1>" + name + "</h1></body></html>",
            "Liquid Brun Limited Edition 150 ml",
            jsonld_data=jsonld,
            h1_override=name,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["identity"]["gtin"]["value"], "6298042001831")
        self.assertEqual(result["identity"]["sku"]["value"], "1385920")
        self.assertEqual(result["attributes"]["size_ml"]["value"], 150)
        self.assertEqual(result["offer"]["availability"], "out_of_stock")
        self.assertIsNone(result["offer"]["price"])
        self.assertIsNone(result["price"])
        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
