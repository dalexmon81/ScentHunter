"""Regression tests for Easycosmetic product-page identity validation."""
import unittest

from scrapers.easycosmetic import scraper


class EasycosmeticProductIdentityTests(unittest.TestCase):
    def test_category_page_with_h1_and_unrelated_price_is_rejected(self):
        html = """
        <html><body>
          <main><h1>Parfum für Damen</h1>
            <p>Entdecken Sie unsere Auswahl.</p>
          </main>
          <aside><span class="price">29,99 €</span></aside>
        </body></html>
        """
        self.assertIsNone(
            scraper._parse_product_html(
                "https://www.easycosmetic.de/damen/parfum/", html
            )
        )

    def test_product_jsonld_without_price_is_kept_for_out_of_stock_detail(self):
        html = """
        <html><body><main>
          <h1>Beispiel Eau de Parfum</h1>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Beispiel Eau de Parfum",
            "brand": {"@type": "Brand", "name": "Beispiel"}
          }
          </script>
          <p>Derzeit nicht auf Lager</p>
        </main></body></html>
        """
        result = scraper._parse_product_html(
            "https://www.easycosmetic.de/beispiel-eau-de-parfum/", html
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Beispiel Eau de Parfum")
        self.assertIsNone(result["price_num"])
        self.assertFalse(result["available"])

    def test_detail_with_product_scoped_price_is_kept_without_jsonld(self):
        html = """
        <html><body><main class="product-detail">
          <h1>Beispiel Eau de Parfum</h1>
          <div class="product-price">49,95 €</div>
        </main></body></html>
        """
        result = scraper._parse_product_html(
            "https://www.easycosmetic.de/beispiel-eau-de-parfum/", html
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["price_num"], 49.95)


if __name__ == "__main__":
    unittest.main()
