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

    def test_dutch_niet_op_voorraad_is_not_misread_as_in_stock(self):
        url = (
            "https://www.deloox.be/produit/1385920/"
            "french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
        )
        name = "French Avenue Liquid Brun Extrait de Parfum Limited Edition"
        html = (
            "<html><body><h1>" + name + "</h1>"
            '<div class="availability">Niet op voorraad</div>'
            "</body></html>"
        )

        result = _product(
            url,
            html,
            "Liquid Brun Limited Edition 150 ml",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["attributes"]["size_ml"]["value"], 150)
        self.assertEqual(result["offer"]["availability"], "out_of_stock")
        self.assertIsNone(result["offer"]["price"])
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


if __name__ == "__main__":
    unittest.main()
