import unittest

from scrapers.deloox import scraper
import catalog_engine as catalog


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
            "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
            "brand": {"@type": "Brand", "name": "French Avenue"},
            "size": {"@type": "QuantitativeValue", "value": 100, "unitText": "ml"},
            "offers": {"@type": "Offer", "price": "32.99", "priceCurrency": "EUR"}
          }
          </script>
        </head><body><h1>French Avenue Liquid Brun Eau de Parfum 100 ml</h1></body></html>
        """
        result = scraper._product(
            "https://www.deloox.be/produit/123/liquid-brun-eau-de-parfum-100-ml",
            html,
            "Liquid Brun Eau de Parfum 100 ml",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["offer"]["price"], 32.99)


    def test_multiple_jsonld_offers_select_the_exact_requested_size(self):
        html = """
        <html><head><script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Valentino Born in Roma Donna Eau de Parfum",
          "brand": {"@type": "Brand", "name": "Valentino"},
          "offers": [
            {"@type": "Offer", "size": {"@type": "QuantitativeValue", "value": 30, "unitText": "ml"}, "price": "60.99", "priceCurrency": "EUR"},
            {"@type": "Offer", "size": {"@type": "QuantitativeValue", "value": 50, "unitText": "ml"}, "price": "82.59", "priceCurrency": "EUR"},
            {"@type": "Offer", "size": {"@type": "QuantitativeValue", "value": 100, "unitText": "ml"}, "price": "109.99", "priceCurrency": "EUR"}
          ]
        }
        </script></head><body><h1>Valentino Born in Roma Donna Eau de Parfum</h1></body></html>
        """
        result = scraper._product(
            "https://www.deloox.lu/produit/1215287/valentino-born-in-roma-donna-eau-de-parfum-50-ml.html",
            html,
            "Valentino Born in Roma Donna Eau de Parfum 50 ml",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["offer"]["price"], 82.59)

    def test_multiple_jsonld_offers_without_offer_level_size_fail_closed(self):
        html = """
        <html><head><script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Valentino Born in Roma Donna Eau de Parfum",
          "brand": {"@type": "Brand", "name": "Valentino"},
          "size": {"@type": "QuantitativeValue", "value": 50, "unitText": "ml"},
          "offers": [
            {"@type": "Offer", "price": "80.79", "priceCurrency": "EUR"},
            {"@type": "Offer", "price": "82.59", "priceCurrency": "EUR"}
          ]
        }
        </script></head><body><h1>Valentino Born in Roma Donna Eau de Parfum</h1></body></html>
        """
        result = scraper._product(
            "https://www.deloox.lu/produit/1215287/valentino-born-in-roma-donna-eau-de-parfum-50-ml.html",
            html,
            "Valentino Born in Roma Donna Eau de Parfum 50 ml",
        )
        self.assertIsNone(result)

    def test_out_of_stock_deloox_offer_remains_visible_without_price(self):
        # Confirmed stock status should be visible, but it must not invent a price.
        self.assertFalse(catalog._should_hide_deloox_offer("deloox", "out_of_stock", None))
        self.assertFalse(catalog._should_hide_deloox_offer("deloox", "out_of_stock", 44.79))
        self.assertTrue(catalog._should_hide_deloox_offer("deloox", "in_stock", None))
        self.assertFalse(catalog._should_hide_deloox_offer("deloox", "in_stock", 32.99))
        self.assertTrue(catalog._should_hide_deloox_offer("deloox", "discontinued", None))
        self.assertFalse(catalog._should_hide_deloox_offer("sabina", "out_of_stock", 38.90))

    def test_limited_edition_150ml_out_of_stock_is_parsed_without_price(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "French Avenue Liquid Brun Limited Edition 150 ml",
            "brand": {"@type": "Brand", "name": "French Avenue"},
            "size": {"@type": "QuantitativeValue", "value": 150, "unitText": "ml"},
            "offers": {"@type": "Offer", "availability": "https://schema.org/OutOfStock", "priceCurrency": "EUR"}
          }
          </script>
        </head><body>
          <h1>French Avenue Liquid Brun Limited Edition 150 ml</h1>
          <div class="availability">Out of stock</div>
        </body></html>
        """
        url = "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
        result = scraper.extract_product_page(None, url, html=html)
        self.assertIsNotNone(result)
        self.assertEqual(result["attributes"]["size_ml"]["value"], 150)
        self.assertEqual(result["offer"]["availability"], "out_of_stock")
        self.assertIsNone(result["offer"]["price"])
        self.assertIsNone(result["price"])

        # An explicit 150 ml variant must never satisfy the 100 ml search.
        self.assertIsNone(scraper._product(url, html, "Liquid Brun Limited Edition 100 ml"))




    def test_visible_sold_out_control_overrides_stale_jsonld_in_stock(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "French Avenue Liquid Brun Limited Edition 150 ml",
            "brand": {"@type": "Brand", "name": "French Avenue"},
            "size": {"@type": "QuantitativeValue", "value": 150, "unitText": "ml"},
            "offers": {
              "@type": "Offer",
              "availability": "https://schema.org/InStock",
              "price": "44.79",
              "priceCurrency": "EUR"
            }
          }
          </script>
        </head><body>
          <h1>French Avenue Liquid Brun Limited Edition 150 ml</h1>
          <div class="availability">Uitverkocht</div>
          <button class="add-to-cart" disabled>Niet op voorraad</button>
        </body></html>
        """
        url = (
            "https://www.deloox.be/produit/1385920/"
            "french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
        )

        result = scraper.extract_product_page(
            None, url, query="Liquid Brun Limited Edition 150 ml", html=html
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["attributes"]["size_ml"]["value"], 150)
        self.assertEqual(result["offer"]["availability"], "out_of_stock")
        self.assertIsNone(result["offer"]["price"])
        self.assertIsNone(result["price"])
        self.assertFalse(result["available"])

if __name__ == "__main__":
    unittest.main()
