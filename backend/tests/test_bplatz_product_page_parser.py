import unittest

from bs4 import BeautifulSoup

from backend.scrapers.bplatz.scraper import product_from_page


class BplatzProductPageParserTests(unittest.TestCase):
    def test_shopify_handle_brand_prefix_does_not_hide_matching_product(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
            "brand": {"@type": "Brand", "name": "French Avenue"},
            "offers": {
              "@type": "Offer",
              "price": "29.00",
              "priceCurrency": "EUR",
              "availability": "https://schema.org/InStock"
            }
          }
          </script>
        </head><body><h1>French Avenue Liquid Brun Eau de Parfum 100 ml</h1></body></html>
        """
        url = "https://en.bplatz.de/products/fragrance-world-liquid-brun-eau-de-parfum-100ml"
        parsed = product_from_page(
            session=None,
            url=url,
            query="fragrance world liquid brun eau de parfum 100ml",
            html=html,
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["name"], "French Avenue Liquid Brun Eau de Parfum 100 ml")
        self.assertEqual(parsed["brand"], "French Avenue")
        self.assertEqual(parsed["size_ml"], 100)
        self.assertEqual(parsed["price_num"], 29.0)
        self.assertEqual(parsed["availability"], "in_stock")

    def test_long_handle_still_rejects_unrelated_product_page(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {"@type":"Product","name":"French Avenue Liquid Brun Eau de Parfum 100 ml",
           "brand":{"@type":"Brand","name":"French Avenue"},
           "offers":{"@type":"Offer","price":"29.00","availability":"https://schema.org/InStock"}}
          </script>
        </head><body><h1>French Avenue Liquid Brun Eau de Parfum 100 ml</h1></body></html>
        """
        parsed = product_from_page(
            session=None,
            url="https://en.bplatz.de/products/other-brand-other-fragrance-100ml",
            query="other brand other fragrance 100ml",
            html=html,
        )
        self.assertIsNone(parsed)


if __name__ == "__main__":
    unittest.main()
