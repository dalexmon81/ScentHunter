"""Regression tests for Deloox navigation URLs leaking into the product catalog."""

import unittest

from backend import catalog_engine


class DelooxProductUrlAdmissionTests(unittest.TestCase):
    def test_localized_search_pages_are_rejected(self):
        urls = (
            "https://www.deloox.com/search.html",
            "https://www.deloox.com/en/search.html",
            "https://www.deloox.be/chercher.html",
            "https://www.deloox.lu/chercher.html",
            "https://www.deloox.lu/fr/chercher.html",
            "https://www.deloox.es/buscar.html",
            "https://www.deloox.nl/zoeken.html",
            "https://www.deloox.com/search",
            "https://www.deloox.nl/zoeken.HTML",
        )

        for url in urls:
            with self.subTest(url=url):
                self.assertIsNone(
                    catalog_engine._html_product_url(
                        "deloox", url, catalog_engine.STORES["deloox"]
                    ),
                    msg=f"navigation URL must not be admitted: {url}",
                )

    def test_canonical_localized_product_urls_are_kept(self):
        urls = (
            "https://www.deloox.com/product/1380881/chloe-le-parfum-parfum-150-ml.html",
            "https://www.deloox.be/produit/1009926/hermes-eau-de-pamplemousse-rose-eau-de-cologne-100-ml.html",
            "https://www.deloox.lu/produit/1321602/armani-acqua-di-gio-profondo-eau-de-parfum-30-ml.html",
            "https://www.deloox.es/producto/1234567/perfume-example-100-ml.html",
            "https://www.deloox.nl/product/1234567/perfume-example-100-ml.html",
        )

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(
                    catalog_engine._html_product_url(
                        "deloox", url, catalog_engine.STORES["deloox"]
                    ),
                    url,
                )


if __name__ == "__main__":
    unittest.main()
