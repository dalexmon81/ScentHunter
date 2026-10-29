import unittest

from scrapers.deloox import scraper


class DelooxSlugDiscoveryTests(unittest.TestCase):
    def test_discovers_relevant_slug_product_url_without_numeric_product_path(self):
        html = """
        <html><body>
          <article class="product-card">
            <a href="/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html">
              French Avenue Liquid Brun Extrait de Parfum Limited Edition 150 ml
            </a>
          </article>
        </body></html>
        """
        urls = scraper._candidate_product_urls(
            html,
            "Liquid Brun Limited Edition 150 ml",
            base_url="https://www.deloox.be",
            accept_all_products=False,
        )
        self.assertEqual(
            urls,
            ["https://www.deloox.be/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"],
        )

    def test_does_not_discover_unrelated_slug_pages(self):
        html = """
        <html><body>
          <a href="/shampoo-for-dry-hair.html">Shampoo for dry hair</a>
          <a href="/category/liquid-brun.html">Liquid Brun</a>
          <a href="/cart.html">Liquid Brun</a>
        </body></html>
        """
        urls = scraper._candidate_product_urls(
            html,
            "Liquid Brun Limited Edition 150 ml",
            base_url="https://www.deloox.be",
            accept_all_products=False,
        )
        self.assertEqual(urls, [])

    def test_slug_discovery_remains_generic_for_other_products(self):
        html = """
        <html><body>
          <article class="product-card">
            <a href="/dior-sauvage-eau-de-parfum-100-ml.html">
              Dior Sauvage Eau de Parfum 100 ml
            </a>
          </article>
        </body></html>
        """
        urls = scraper._candidate_product_urls(
            html,
            "Dior Sauvage 100 ml",
            base_url="https://www.deloox.be",
            accept_all_products=False,
        )
        self.assertEqual(
            urls,
            ["https://www.deloox.be/dior-sauvage-eau-de-parfum-100-ml.html"],
        )


if __name__ == "__main__":
    unittest.main()
