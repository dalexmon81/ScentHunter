import unittest

from scrapers.deloox import scraper


class DelooxVariantIntegrityTests(unittest.TestCase):
    def test_product_page_with_wrong_explicit_size_is_rejected(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "French Avenue Liquid Brun 150 ml",
            "brand": {"@type": "Brand", "name": "French Avenue"},
            "offers": {"@type": "Offer", "price": "44.79", "priceCurrency": "EUR"}
          }
          </script>
        </head><body><h1>French Avenue Liquid Brun 150 ml</h1></body></html>
        """
        result = scraper._product(
            "https://www.deloox.be/produit/123/liquid-brun-150-ml",
            html,
            "Liquid Brun 100 ml",
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
