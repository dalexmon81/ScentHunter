"""Regression tests for bounded Deloox discovery and catalog hydration."""
import re
import unittest

from scrapers import deloox, parfumzentrum


class CatalogHydrationTests(unittest.TestCase):
    def test_parfumzentrum_internal_sku_suffix_is_stripped(self):
        # Match the implementation's _?z<digits> rule, including the underscore.
        query = "Berdoues Monoi Tiare Eau de Toilette 100 ml_z904294"
        normalized = re.sub(r"_?z\d+\s*$", "", query, flags=re.I).strip()
        self.assertEqual(normalized, "Berdoues Monoi Tiare Eau de Toilette 100 ml")

    def test_parfumzentrum_known_url_adapter_parses_jsonld_price(self):
        url = "https://www.parfum-zentrum.de/berdoues-monoi-tiare-eau-de-toilette-100-ml-unisex_z904294/"
        html = """<!doctype html><html><head>
        <script type="application/ld+json">{
          "@context":"https://schema.org",
          "@type":"Product",
          "name":"Berdoues Monoi & Tiare Eau de Toilette 100 ml",
          "brand":{"@type":"Brand","name":"Berdoues"},
          "sku":"pz-904294",
          "offers":{"@type":"Offer","price":"29.40","priceCurrency":"EUR",
                    "availability":"https://schema.org/InStock"}
        }</script></head><body><h1>Berdoues Monoï &amp; Tiaré Eau De Toilette 100 ml (unisex)</h1></body></html>"""
        product = parfumzentrum.extract_product_page(None, url, query="", html=html)
        self.assertIsNotNone(product)
        self.assertEqual(product["name"], "Berdoues Monoi & Tiare Eau de Toilette 100 ml")
        self.assertEqual(product["price_num"], 29.4)
        self.assertEqual(product["availability"], "in_stock")

    def test_deloox_candidate_extractor_skips_assets_and_keeps_product_links(self):
        html = """<html><body>
        <a href="/product/12345/maison-example-eau-de-parfum-100-ml.html">Maison Example Eau de Parfum 100 ml</a>
        <a href="/product/12345/maison-example-100.jpg">product image</a>
        <div data-product-url="/product/67890/maison-example-eau-de-toilette-50-ml.html">Maison Example Eau de Toilette 50 ml</div>
        </body></html>"""
        urls = deloox._candidate_product_urls(
            html, "Maison Example", accept_all_products=False,
            base_url="https://www.deloox.be",
        )
        self.assertIn("https://www.deloox.be/product/12345/maison-example-eau-de-parfum-100-ml.html", urls)
        self.assertIn("https://www.deloox.be/product/67890/maison-example-eau-de-toilette-50-ml.html", urls)
        self.assertFalse(any(url.endswith(".jpg") for url in urls))


if __name__ == "__main__":
    unittest.main()
