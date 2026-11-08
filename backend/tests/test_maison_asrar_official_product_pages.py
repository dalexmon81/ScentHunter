"""Regression coverage for Maison Asrar official individual product-page provenance."""
import json
import unittest
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Ameer": "https://maisonasrar.com/products/ameer",
    "Veyra": "https://maisonasrar.com/products/veyra",
    "Vanilla Voyage": "https://maisonasrar.com/products/vanilla-voyage-eau-de-parfum",
    "Last Swim": "https://maisonasrar.com/products/last-swim",
    "Silent Surge": "https://maisonasrar.com/products/silent-surge",
    "DXB Jumeirah": "https://maisonasrar.com/products/dxb-jumeirah",
    "Vanilla Aura": "https://maisonasrar.com/products/vanilla-aura",
    "Faris Al Arab": "https://maisonasrar.com/products/faris-al-arab",
    "III Thriller": "https://maisonasrar.com/products/iii-thriller",
    "Muharib": "https://maisonasrar.com/products/muharib",
    "Hunter": "https://maisonasrar.com/products/maison-asrar-hunter-eau-de-parfum-100ml",
    "1963": "https://maisonasrar.com/products/1963-eau-de-perfum-100ml",
    "Lumiere": "https://maisonasrar.com/products/lumiere",
    "Milky Way": "https://maisonasrar.com/products/milky-way",
    "Mohra": "https://maisonasrar.com/products/mohrab",
    "Luna": "https://maisonasrar.com/products/luna-eau-de-parfum-100ml",
    "Magic Night": "https://maisonasrar.com/products/magic-night-eau-de-perfum-100ml",
    "Omniya": "https://maisonasrar.com/products/omniya",
    "Qamar": "https://maisonasrar.com/products/qamar",
    "Oh Honey!": "https://maisonasrar.com/products/oh-honey-eau-de-parfum",
    "Patchouli with Love": "https://maisonasrar.com/products/patchouli-with-love-maison-asrar-eau-de-perfum-100-ml",
    "Pink Crush": "https://maisonasrar.com/products/maison-asrar-pink-crush-eau-de-parfum-100-ml-for-women",
    "Oscar": "https://maisonasrar.com/products/oscar-eau-de-perfum-100ml",
    "Petra": "https://maisonasrar.com/products/petra-maison-asrar-eau-de-perfum-100ml",
    "Never Forget Me": "https://maisonasrar.com/products/never-forget-me-maison-asrar-eau-de-perfum-90ml",
}


class MaisonAsrarOfficialProductPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(CATALOG.read_text(encoding="utf-8"))
        cls.products = {
            p["canonical_name"]: p
            for p in cls.data["products"]
            if p.get("brand_name") == "Maison Asrar"
        }

    def test_selected_listing_only_rows_have_official_detail_pages(self):
        for name, url in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)

    def test_no_unverified_size_or_concentration_was_invented(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                product = self.products[name]
                self.assertNotIn("formats_ml", product)
                if name == "Patchouli with Love":
                    self.assertEqual(product["concentration"], "Eau de Parfum")
                else:
                    self.assertNotIn("concentration", product)


if __name__ == "__main__":
    unittest.main()
