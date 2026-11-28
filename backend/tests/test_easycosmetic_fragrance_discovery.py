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

    def test_live_observed_dior_makeup_and_skincare_categories_are_rejected(self):
        observed_products = (
            ("Backstage Eye Palette", "/dior/backstage-eye-palette/product.aspx"),
            ("Backstage Rosy Glow Rouge", "/dior/backstage-rosy-glow/product.aspx"),
            ("Capture Totale Crème Fine Rechargeable", "/dior/capture-totale/creme-fine.aspx"),
            ("Capture Totale Crème Riche Rechargeable", "/dior/capture-totale/creme-riche.aspx"),
            ("Capture Totale Hyalushot Classic Serum", "/dior/capture-totale/hyalushot-classic.aspx"),
            ("Capture Totale Hyalushot Serum", "/dior/capture-totale/hyalushot.aspx"),
            ("Capture Totale Le Baume Tagescreme", "/dior/capture-totale/le-baume.aspx"),
            ("Capture Totale Le Sérum Serum", "/dior/capture-totale/le-serum.aspx"),
            ("Capture Totale PDRN-Shot Serum", "/dior/capture-totale/pdrn-shot.aspx"),
        )
        html = "<html><body>" + "".join(
            f'<a href="{url}">{name}</a>' for name, url in observed_products
        ) + "</body></html>"
        candidates = scraper._extract_candidate_links(
            BeautifulSoup(html, "html.parser"), "Dior"
        )
        self.assertEqual(candidates, [])

    def test_live_observed_dior_non_fragrance_products_are_rejected(self):
        observed_products = (
            ("Capture Totale Pro-Collagen Shot Augenfluid", "/dior/capture-totale/pro-collagen-shot-augenfluid.aspx"),
            ("Capture Totale Retishot Serum", "/dior/capture-totale/retishot-serum.aspx"),
            ("Diorskin Forever Contour Stick", "/dior/diorskin/forever-contour-stick.aspx"),
            ("Eau Sauvage Aftershave Spray", "/dior/eau-sauvage/aftershave-spray.aspx"),
            ("Eau Sauvage Seife", "/dior/eau-sauvage/seife.aspx"),
            ("Capture Totale Dreamskin 1-Minute Mask Pflegemaske", "/dior/capture-totale/dreamskin-mask.aspx"),
            ("Forever Glow Luminizer Highlighter", "/dior/forever-glow-luminizer.aspx"),
            ("Forever Glow Star Filter Spezialprodukt", "/dior/forever-glow-star-filter.aspx"),
            ("Homme Dermo System Sérum Yeux Tenseur Hydratant Augenserum", "/dior/homme-dermo-system-serum-yeux.aspx"),
        )
        html = "<html><body>" + "".join(
            f'<a href="{url}">{name}</a>' for name, url in observed_products
        ) + "</body></html>"
        candidates = scraper._extract_candidate_links(
            BeautifulSoup(html, "html.parser"), "Dior"
        )
        self.assertEqual(candidates, [])

    def test_brand_is_recovered_only_when_url_category_matches_visible_title(self):
        self.assertEqual(
            scraper._brand_from_product_url_title(
                "https://www.easycosmetic.de/giorgio-armani/acqua-di-gio/product.aspx",
                "Giorgio Armani Acqua di Gio Homme Profondo Eau de Parfum Spray",
            ),
            "Giorgio Armani",
        )
        self.assertEqual(
            scraper._brand_from_product_url_title(
                "https://www.easycosmetic.de/dior/sauvage/product.aspx",
                "Giorgio Armani Acqua di Gio Homme Profondo Eau de Parfum Spray",
            ),
            "",
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
