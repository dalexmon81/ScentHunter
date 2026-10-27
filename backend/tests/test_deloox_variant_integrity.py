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


    def test_product_page_with_structured_150ml_size_is_rejected_even_when_title_and_url_omit_size(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "French Avenue Liquid Brun",
            "brand": {"@type": "Brand", "name": "French Avenue"},
            "size": {"@type": "QuantitativeValue", "value": 150, "unitText": "ml"},
            "offers": {"@type": "Offer", "price": "44.79", "priceCurrency": "EUR"}
          }
          </script>
        </head><body><h1>French Avenue Liquid Brun</h1></body></html>
        """
        result = scraper._product(
            "https://www.deloox.be/produit/123/liquid-brun",
            html,
            "Liquid Brun 100 ml",
        )
        self.assertIsNone(result)

    def test_explicit_size_request_fails_closed_when_page_has_no_size_evidence(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "French Avenue Liquid Brun",
            "brand": {"@type": "Brand", "name": "French Avenue"},
            "offers": {"@type": "Offer", "price": "44.79", "priceCurrency": "EUR"}
          }
          </script>
        </head><body><h1>French Avenue Liquid Brun</h1></body></html>
        """
        result = scraper._product(
            "https://www.deloox.be/produit/123/liquid-brun",
            html,
            "Liquid Brun 100 ml",
        )
        self.assertIsNone(result)

    def test_structured_matching_size_is_accepted(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "French Avenue Liquid Brun",
            "brand": {"@type": "Brand", "name": "French Avenue"},
            "size": {"@type": "QuantitativeValue", "value": 100, "unitText": "ml"},
            "offers": {"@type": "Offer", "price": "32.99", "priceCurrency": "EUR"}
          }
          </script>
        </head><body><h1>French Avenue Liquid Brun 100 ml</h1></body></html>
        """
        result = scraper._product(
            "https://www.deloox.be/produit/123/liquid-brun-100-ml",
            html,
            "Liquid Brun 100 ml",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["offer"]["price"], 32.99)


if __name__ == "__main__":
    unittest.main()
