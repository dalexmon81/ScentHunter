import unittest
from scenthunter_next_engine.adapters.deloox import DelooxProductPageAdapter, _product_jsonld
from scenthunter_next_engine.errors import AdapterFailure, ErrorKind

URL = "https://www.deloox.nl/product/12345/test"


def page(product, extra=""):
    import json
    return ("<html><head>" + extra + '<script type="application/ld+json">' +
            json.dumps(product) + "</script></head><body><h1>Fallback title</h1></body></html>").encode()


class DelooxAdapterTests(unittest.TestCase):
    def test_parses_product_jsonld_offer(self):
        body = page({"@type": "Product", "name": "Maison Test 100 ml Eau de Parfum",
                     "brand": {"@type": "Brand", "name": "Maison Test"},
                     "offers": {"@type": "Offer", "price": "89.95", "priceCurrency": "EUR",
                                "availability": "https://schema.org/InStock"}})
        result = DelooxProductPageAdapter().parse(URL, body)
        self.assertEqual(result.title, "Maison Test 100 ml Eau de Parfum")
        self.assertEqual(result.brand, "Maison Test")
        self.assertEqual(result.price_minor, 8995)
        self.assertEqual(result.availability, "in_stock")
        self.assertEqual(str(result.size_ml), "100")

    def test_parses_product_inside_graph_and_aggregate_low_price(self):
        product = {"@graph": [{"@type": "WebPage"}, {"@type": "Product", "name": "Brand X 50 ml",
                    "brand": "Brand X", "offers": {"@type": "AggregateOffer", "lowPrice": "42.50",
                    "priceCurrency": "EUR"}}]}
        self.assertTrue(_product_jsonld('<script type="application/ld+json">' + __import__('json').dumps(product) + '</script>'))
        result = DelooxProductPageAdapter().parse(URL, page(product))
        self.assertEqual(result.price_minor, 4250)

    def test_metadata_fallback_for_brand_and_product_price(self):
        extra = ('<meta property="product:brand" content="Brand Meta">'
                 '<meta property="product:price:amount" content="31,90">'
                 '<meta property="product:price:currency" content="EUR">')
        body = ("<html><head>" + extra + "</head><body><h1>Brand Meta perfume 30 ml</h1></body></html>").encode()
        result = DelooxProductPageAdapter().parse(URL, body)
        self.assertEqual(result.brand, "Brand Meta")
        self.assertEqual(result.price_minor, 3190)

    def test_rejects_missing_brand_instead_of_guessing(self):
        body = page({"@type": "Product", "name": "Unknown 50 ml", "offers": {"price": "12.00"}})
        with self.assertRaises(AdapterFailure) as caught:
            DelooxProductPageAdapter().parse(URL, body)
        self.assertEqual(caught.exception.kind, ErrorKind.INVALID_PRODUCT)

    def test_rejects_non_deloox_url(self):
        with self.assertRaises(AdapterFailure) as caught:
            DelooxProductPageAdapter().parse("https://example.com/product/12345", b"")
        self.assertEqual(caught.exception.kind, ErrorKind.INVALID_URL)


if __name__ == "__main__":
    unittest.main()
