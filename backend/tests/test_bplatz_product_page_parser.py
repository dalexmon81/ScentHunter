import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from backend.scrapers.bplatz import scraper
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

    def test_catalog_hydration_slug_with_products_prefix_uses_handle_only(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {"@type":"Product","name":"French Avenue Liquid Brun Eau de Parfum 100 ml",
           "brand":{"@type":"Brand","name":"French Avenue"},
           "offers":{"@type":"Offer","price":"29.00","availability":"https://schema.org/InStock"}}
          </script>
        </head><body><h1>French Avenue Liquid Brun Eau de Parfum 100 ml</h1></body></html>
        """
        from backend.scrapers.bplatz.scraper import extract_product_page

        url = "https://en.bplatz.de/products/fragrance-world-liquid-brun-eau-de-parfum-100ml"
        # This is the exact shape produced by catalog_engine.url_slug(url).
        catalog_slug = "products fragrance world liquid brun eau de parfum 100ml"
        parsed = extract_product_page(None, url, catalog_slug, html=html)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["size_ml"], 100)
        self.assertEqual(parsed["price_num"], 29.0)

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


    def test_query_scoped_shopify_results_skip_full_catalog_and_sitemap_crawls(self):
        product = {
            "title": "French Avenue Atlantis Extrait Extrait de Parfum 100 ml",
            "vendor": "French Avenue",
            "url": "/products/french-avenue-atlantis-extrait-extrait-de-parfum-100-ml",
        }

        def request_json(_session, url, _params):
            if url.endswith("/search/suggest.json"):
                return {"resources": {"results": {"products": [product]}}}
            if url.endswith("/search.json"):
                return {"products": []}
            raise AssertionError(f"unexpected discovery URL: {url}")

        with (
            patch.object(scraper, "request_json", side_effect=request_json),
            patch.object(scraper, "_discover_products_json", side_effect=AssertionError("full catalog crawl should be skipped")),
            patch.object(scraper, "_discover_from_sitemap", side_effect=AssertionError("sitemap crawl should be skipped")),
        ):
            candidates, errors, verified = scraper.discover(
                object(), "French Avenue Atlantis 100 ml"
            )

        self.assertTrue(verified)
        self.assertEqual(errors, [])
        self.assertEqual(
            candidates,
            ["https://en.bplatz.de/products/french-avenue-atlantis-extrait-extrait-de-parfum-100-ml"],
        )

    def test_visible_product_stock_overrides_stale_jsonld_out_of_stock(self):
        html = """
        <html><body>
          <main>
            <section class="product__info-container">
              <h1>French Avenue Liquid Brun Limited Edition Extrait de Parfum 150 ml</h1>
              <p>Available immediately from French Avenue</p>
              <form action="/cart/add"><button>Add to cart</button></form>
            </section>
            <section id="shopify-section-reviews">
              <p>Some older review says the item was out of stock.</p>
            </section>
          </main>
          <script type="application/ld+json">
          {"@type":"Product",
           "name":"French Avenue Liquid Brun Limited Edition Extrait de Parfum 150 ml",
           "brand":{"@type":"Brand","name":"French Avenue"},
           "offers":{"@type":"Offer","price":"36.80",
                     "availability":"https://schema.org/OutOfStock"}}
          </script>
        </body></html>
        """
        parsed = product_from_page(
            session=None,
            url="https://en.bplatz.de/products/liquid-brun-limited-edition-eau-de-parfum-150-ml",
            query="French Avenue Liquid Brun Limited Edition 150 ml",
            html=html,
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["size_ml"], 150)
        self.assertEqual(parsed["price_num"], 36.80)
        self.assertEqual(parsed["availability"], "in_stock")
        self.assertTrue(parsed["available"])

    def test_visible_sold_out_product_status_overrides_jsonld_in_stock(self):
        html = """
        <html><body>
          <main>
            <section class="product__info-container">
              <h1>French Avenue Liquid Brun Limited Edition Extrait de Parfum 150 ml</h1>
              <p>Out of stock</p>
              <form action="/cart/add"><button>Sold out</button></form>
            </section>
          </main>
          <script type="application/ld+json">
          {"@type":"Product",
           "name":"French Avenue Liquid Brun Limited Edition Extrait de Parfum 150 ml",
           "brand":{"@type":"Brand","name":"French Avenue"},
           "offers":{"@type":"Offer","price":"36.80",
                     "availability":"https://schema.org/InStock"}}
          </script>
        </body></html>
        """
        parsed = product_from_page(
            session=None,
            url="https://en.bplatz.de/products/liquid-brun-limited-edition-eau-de-parfum-150-ml",
            query="French Avenue Liquid Brun Limited Edition 150 ml",
            html=html,
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["availability"], "out_of_stock")
        self.assertFalse(parsed["available"])

    def test_shopify_product_price_metadata_fills_missing_jsonld_price(self):
        html = """
        <html><head>
          <meta property="product:price:amount" content="38.99">
          <meta property="product:price:currency" content="EUR">
          <script type="application/ld+json">
          {"@type":"Product","name":"French Avenue Atlantis Extrait Extrait de Parfum 100 ml",
           "brand":{"@type":"Brand","name":"French Avenue"},
           "offers":{"@type":"Offer","availability":"https://schema.org/InStock"}}
          </script>
        </head><body><h1>French Avenue Atlantis Extrait Extrait de Parfum 100 ml</h1></body></html>
        """
        parsed = product_from_page(
            session=None,
            url="https://bplatz.de/products/french-avenue-atlantis-extrait-extrait-de-parfum-100-ml",
            query="french avenue atlantis extrait extrait de parfum 100 ml",
            html=html,
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["brand"], "French Avenue")
        self.assertEqual(parsed["size_ml"], 100)
        self.assertEqual(parsed["price_num"], 38.99)
        self.assertEqual(parsed["availability"], "in_stock")


if __name__ == "__main__":
    unittest.main()
