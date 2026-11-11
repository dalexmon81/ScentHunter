"""ParfumCity Shopify product-page extraction regressions."""
import unittest

from scrapers.parfumcity import scraper


class ParfumCityProductPageTests(unittest.TestCase):
    def test_extracts_price_and_out_of_stock_from_embedded_jsonld(self):
        html = """<!doctype html><html><head>
        <script type="application/ld+json">{
          "@context":"https://schema.org",
          "@type":"Product",
          "name":"Liquid Brun Limited Edition French Avenue 150ML",
          "brand":{"@type":"Brand","name":"French Avenue"},
          "sku":"pc-150",
          "gtin13":"6298042001831",
          "offers":{"@type":"Offer","price":"39.99","priceCurrency":"EUR",
                    "availability":"https://schema.org/OutOfStock"}
        }</script></head><body>
        <h1>Liquid Brun Limited Edition French Avenue 150ML</h1>
        <div>Épuisé</div></body></html>"""
        rows = scraper.extract_product_page(
            None,
            "https://www.parfumcity.nl/fr/products/liquid-brun-limited-edition-french-avenue-100-ml",
            "liquid-brun-limited-edition",
            html=html,
        )
        self.assertEqual(len(rows), 1)
        item = rows[0]
        self.assertEqual(item["name"], "Liquid Brun Limited Edition French Avenue 150ML")
        self.assertEqual(item["price_num"], 39.99)
        self.assertEqual(item["offer"]["currency"], "EUR")
        self.assertEqual(item["availability"], "out_of_stock")
        self.assertEqual(item["identity"]["gtin"], "6298042001831")
        self.assertIn("/products/liquid-brun-limited-edition-french-avenue-100-ml", item["url"])


if __name__ == "__main__":
    unittest.main()
