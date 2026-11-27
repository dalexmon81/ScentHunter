import unittest

from bs4 import BeautifulSoup

from scrapers.easycosmetic import scraper


class EasycosmeticFragranceDiscoveryTests(unittest.TestCase):
    def test_discovery_keeps_perfume_and_rejects_makeup_and_skincare(self):
        html = """
        <html><body>
          <a href="/dior/sauvage/dior-sauvage-eau-de-parfum-100ml.aspx">
            Dior Sauvage Eau de Parfum 100 ml
          </a>
          <a href="/dior/beauty/dior-addict-lip-glow.aspx">
            Dior Addict Lip Glow
          </a>
          <a href="/dior/skincare/dior-capture-totale-face-cream.aspx">
            Dior Capture Totale Face Cream
          </a>
          <a href="/dior/makeup/dior-forever-foundation.aspx">
            Dior Forever Foundation
          </a>
        </body></html>
        """
        candidates = scraper._extract_candidate_links(
            BeautifulSoup(html, "html.parser"), "Dior"
        )

        self.assertEqual(
            [item["url"] for item in candidates],
            [
                "https://www.easycosmetic.de/dior/sauvage/"
                "dior-sauvage-eau-de-parfum-100ml.aspx"
            ],
        )

    def test_unknown_product_category_is_not_rejected_by_default(self):
        html = """
        <html><body>
          <a href="/dior/new-product.aspx">Dior New Product</a>
        </body></html>
        """
        candidates = scraper._extract_candidate_links(
            BeautifulSoup(html, "html.parser"), "Dior"
        )
        self.assertEqual(len(candidates), 1)


if __name__ == "__main__":
    unittest.main()
