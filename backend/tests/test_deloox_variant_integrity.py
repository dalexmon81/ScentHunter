import unittest
import time
from unittest.mock import patch

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


    def test_persisted_price_is_stale_after_24_hours_or_without_timestamp(self):
        now = 2_000_000.0
        self.assertFalse(catalog._catalog_price_is_stale(now - 23 * 60 * 60, now=now))
        self.assertTrue(catalog._catalog_price_is_stale(now - 25 * 60 * 60, now=now))
        self.assertTrue(catalog._catalog_price_is_stale(None, now=now))
        self.assertTrue(catalog._catalog_price_is_stale("not-a-timestamp", now=now))

    def test_out_of_stock_deloox_offer_remains_visible_without_price(self):
        # Confirmed stock status should be visible, but it must not invent a price.
        self.assertFalse(catalog._should_hide_deloox_offer("deloox", "out_of_stock", None))
        self.assertFalse(catalog._should_hide_deloox_offer("deloox", "out_of_stock", 44.79))
        self.assertTrue(catalog._should_hide_deloox_offer("deloox", "in_stock", None))
        self.assertFalse(catalog._should_hide_deloox_offer("deloox", "in_stock", 32.99))
        self.assertTrue(catalog._should_hide_deloox_offer("deloox", "discontinued", None))
        self.assertFalse(catalog._should_hide_deloox_offer("sabina", "out_of_stock", 38.90))

    def test_both_liquid_brun_deloox_pages_keep_separate_explicit_formats(self):
        limited_url = "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
        standard_url = "https://www.deloox.be/produit/1355229/french-avenue-liquid-brun-eau-de-parfum-100-ml.html"
        limited_html = """
        <html><head><script type="application/ld+json">
        {
          "@context":"https://schema.org",
          "@type":"Product",
          "name":"French Avenue Liquid Brun Limited Edition 150 ml",
          "brand":{"@type":"Brand","name":"French Avenue"},
          "size":{"@type":"QuantitativeValue","value":150,"unitText":"ml"},
          "gtin13":"6298042001831",
          "sku":"1385920",
          "offers":{"@type":"Offer","availability":"https://schema.org/OutOfStock","priceCurrency":"EUR"}
        }
        </script></head><body>
        <h1>French Avenue Liquid Brun Limited Edition 150 ml</h1>
        <div class="availability">Out of stock</div>
        </body></html>
        """
        standard_html = """
        <html><head><script type="application/ld+json">
        {
          "@context":"https://schema.org",
          "@type":"Product",
          "name":"French Avenue Liquid Brun Eau de Parfum 100 ml",
          "brand":{"@type":"Brand","name":"French Avenue"},
          "size":{"@type":"QuantitativeValue","value":100,"unitText":"ml"},
          "gtin13":"6290360375694",
          "sku":"1355229",
          "offers":{"@type":"Offer","price":"32.99","priceCurrency":"EUR","availability":"https://schema.org/InStock"}
        }
        </script></head><body>
        <h1>French Avenue Liquid Brun Eau de Parfum 100 ml</h1>
        <div class="availability">In stock</div>
        </body></html>
        """
        limited = scraper.extract_product_page(None, limited_url, html=limited_html)
        standard = scraper.extract_product_page(None, standard_url, html=standard_html)

        self.assertIsNotNone(limited)
        self.assertIsNotNone(standard)
        self.assertEqual(limited["attributes"]["size_ml"]["value"], 150)
        self.assertEqual(limited["offer"]["availability"], "out_of_stock")
        self.assertIsNone(limited["offer"]["price"])
        self.assertEqual(standard["attributes"]["size_ml"]["value"], 100)
        self.assertEqual(standard["offer"]["availability"], "in_stock")
        self.assertEqual(standard["offer"]["price"], 32.99)
        self.assertIsNone(scraper._product(limited_url, limited_html, "Liquid Brun 100 ml"))
        self.assertIsNone(scraper._product(standard_url, standard_html, "Liquid Brun Limited Edition 150 ml"))

    def test_generic_search_discovered_urls_are_persisted_for_catalog_hydration(self):
        product_url = "https://www.deloox.be/product/2222222/generic-fragrance-100-ml.html"

        class FakeConnection:
            def execute(self, *_args, **_kwargs):
                class Cursor:
                    def fetchone(self):
                        return {"pending": 0, "processing": 0, "done": 0, "error": 0, "dead": 0, "total": 0}
                return Cursor()

            def close(self):
                pass

        with (
            patch.object(catalog, "_deloox_retire_invalid_active_urls", return_value={}),
            patch.object(catalog, "_deloox_queue_seed", return_value=[]),
            patch.object(catalog, "_deloox_queue_recover_stale", return_value=0),
            patch.object(catalog, "_deloox_queue_requeue_stale_done", return_value=0),
            patch.object(catalog, "_discover_deloox_search_catalog", return_value={"product_urls": {product_url: ""}, "errors": [], "queries": []}),
            patch.object(catalog, "_deloox_persist_products") as persist,
            patch.object(catalog, "_deloox_queue_claim", return_value=[]),
            patch.object(catalog, "db", return_value=FakeConnection()),
        ):
            result = catalog._discover_deloox_catalog([], deadline=time.time() + 5)

        persist.assert_called_once_with({product_url: ""})
        self.assertIn(product_url, result["product_urls"])

    def test_discovery_continues_to_generic_fallback_when_search_has_candidates(self):
        search_url = "https://www.deloox.be/product/1111111/french-avenue-liquid-brun-eau-de-parfum-100-ml.html"
        category_url = "https://www.deloox.be/product/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
        with patch.object(scraper, "_discover_from_search", return_value=[search_url]) as search, \
             patch.object(scraper, "_discover_from_categories", return_value=[category_url]) as categories, \
             patch.object(scraper, "_sitemap_product_urls", return_value=[]), \
             patch.object(scraper.time, "time", return_value=100.0):
            result = scraper._discover(object(), "Liquid Brun", deadline=110.0)
        self.assertIn(search_url, result)
        self.assertIn(category_url, result)
        categories.assert_called_once()
        # Search must leave time for category fallback rather than consuming
        # the entire discovery deadline and silently skipping alternate sources.
        self.assertLessEqual(search.call_args.kwargs["deadline"], 105.0)

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


if __name__ == "__main__":
    unittest.main()
