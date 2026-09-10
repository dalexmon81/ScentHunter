import unittest

from backend.scrapers.parfumzentrum import scraper


class ParfumzentrumUrlDiscoveryTests(unittest.TestCase):
    def test_extracts_legacy_z_product_links(self):
        html = '<a href="/acqua-di-gio-homme-edt-100ml_z12345">Product</a>'
        urls = scraper._extract_product_urls_from_html(html)
        self.assertEqual(
            urls,
            ["https://www.parfum-zentrum.de/acqua-di-gio-homme-edt-100ml_z12345"],
        )

    def test_extracts_product_like_links_without_z_suffix(self):
        html = """
        <a href="/armaf-club-de-nuit-intense-man-eau-de-toilette-105ml">Product</a>
        <a href="/suchen/?search=armaf">Search</a>
        """
        urls = scraper._extract_product_urls_from_html(html)
        self.assertEqual(
            urls,
            ["https://www.parfum-zentrum.de/armaf-club-de-nuit-intense-man-eau-de-toilette-105ml"],
        )

    def test_ignores_offsite_and_deduplicates(self):
        html = """
        <a href="https://evil.example/something_z123">Offsite</a>
        <a href="/dior-homme-intense-edp-100ml_z555?ref=abc">One</a>
        <a href="https://www.parfum-zentrum.de/dior-homme-intense-edp-100ml_z555#x">Two</a>
        """
        urls = scraper._extract_product_urls_from_html(html)
        self.assertEqual(
            urls,
            ["https://www.parfum-zentrum.de/dior-homme-intense-edp-100ml_z555"],
        )


if __name__ == "__main__":
    unittest.main()
