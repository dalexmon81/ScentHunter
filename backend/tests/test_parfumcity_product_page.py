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

    def test_extracts_product_from_open_graph_metadata_without_jsonld_or_h1(self):
        html = """<!doctype html><html><head>
        <meta property="og:title" content="Liquid Brun Limited Edition French Avenue 150ML">
        <meta property="product:price:amount" content="39.99">
        <meta property="product:availability" content="out of stock">
        </head><body><div>Sold out</div></body></html>"""
        rows = scraper.extract_product_page(
            None,
            "https://www.parfumcity.nl/products/liquid-brun-limited-edition-french-avenue-150-ml",
            "liquid-brun-limited-edition",
            html=html,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Liquid Brun Limited Edition French Avenue 150ML")
        self.assertEqual(rows[0]["price_num"], 39.99)
        self.assertEqual(rows[0]["availability"], "out_of_stock")


if __name__ == "__main__":
    unittest.main()
