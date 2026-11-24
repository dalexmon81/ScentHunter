from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from scrapers.sabina.scraper import availability_from_product_page


class SabinaAvailabilityTests(unittest.TestCase):
    def test_product_unavailable_message_overrides_stale_jsonld_in_stock(self):
        html = """
        <html><head>
          <script type="application/ld+json">
            {"@type":"Product","offers":{"@type":"Offer",
             "availability":"https://schema.org/InStock"}}
          </script>
        </head><body>
          <main class="product-container">
            <h1>French Avenue Liquid Brun Limited Edition</h1>
            <p>Este producto no está disponible</p>
            <button class="add-to-cart" disabled>Añadir a la cesta</button>
          </main>
        </body></html>
        """
        availability, source = availability_from_product_page(BeautifulSoup(html, "html.parser"))
        self.assertEqual(availability, "out_of_stock")
        self.assertEqual(source, "sabina_product_unavailable_message")

    def test_explicit_jsonld_out_of_stock_is_preserved(self):
        html = """
        <html><body><main class="product-container">
          <h1>Liquid Brun</h1>
        </main></body></html>
        """
        availability, source = availability_from_product_page(
            BeautifulSoup(html, "html.parser"),
            {"availability": "https://schema.org/OutOfStock"},
        )
        self.assertEqual(availability, "out_of_stock")
        self.assertEqual(source, "sabina_html_availability")

    def test_unavailable_text_on_related_product_does_not_mark_current_product_out_of_stock(self):
        html = """
        <html><body><main>
          <section class="product-container">
            <h1>Liquid Brun</h1>
            <button class="add-to-cart">Añadir a la cesta</button>
          </section>
          <section class="related-products">
            <p>Producto agotado</p>
          </section>
        </main></body></html>
        """
        availability, source = availability_from_product_page(BeautifulSoup(html, "html.parser"))
        self.assertEqual(availability, "in_stock")
        self.assertEqual(source, "sabina_purchase_control")
    def test_active_product_purchase_control_remains_in_stock_without_unavailable_message(self):
        html = """
        <html><body><main class="product-container">
          <h1>Liquid Brun</h1>
          <button class="add-to-cart">Añadir a la cesta</button>
        </main></body></html>
        """
        availability, source = availability_from_product_page(BeautifulSoup(html, "html.parser"))
        self.assertEqual(availability, "in_stock")
        self.assertEqual(source, "sabina_purchase_control")


if __name__ == "__main__":
    unittest.main()
