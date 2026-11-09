"""Official detail-page evidence for Al Wataniah EDPs."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Abyat": "https://www.alwataniah.com/products/abyat",
    "Ain Emarat": "https://www.alwataniah.com/products/ain-emarat",
    "Ain Emarat Extrait": "https://www.alwataniah.com/products/ain-emarat-extrait",
    "Al Daiem": "https://www.alwataniah.com/products/al-daiem",
    "Al Daiem Elixir": "https://www.alwataniah.com/products/al-daiem-elixir",
    "Al Layl": "https://www.alwataniah.com/products/al-layl",
    "Alya": "https://www.alwataniah.com/products/alya",
    "Ameerati": "https://www.alwataniah.com/products/ameerati",
    "Ameeri": "https://www.alwataniah.com/products/ameeri",
    "Arya": "https://www.alwataniah.com/products/arya",
    "Arya Peony Rose": "https://www.alwataniah.com/products/arya-peony-rose",
    "Attar Al Wesal": "https://www.alwataniah.com/products/attar-al-wesal",
    "Baraa": "https://www.alwataniah.com/products/baraa",
    "Bareeq Al Dhahab": "https://www.alwataniah.com/products/bareeq-al-dhahab",
    "Brownie Bite": "https://www.alwataniah.com/products/brownie-bite",
    "Castilla": "https://www.alwataniah.com/products/castilla",
    "Choco Truffle": "https://www.alwataniah.com/products/choco-truffle",
    "Cloud": "https://www.alwataniah.com/products/cloud",
    "Emiran": "https://www.alwataniah.com/products/emiran",
    "Fayroz": "https://www.alwataniah.com/products/fayroz",
    "Golden Honey": "https://www.alwataniah.com/products/golden-honey",
    "Kayaan Classic": "https://www.alwataniah.com/products/kayaan-classic",
    "Kayaan Gold": "https://www.alwataniah.com/products/kayaan-gold",
    "Kayaan Midnight": "https://www.alwataniah.com/products/kayaan-midnight",
    "Kayaan Terra": "https://www.alwataniah.com/products/kayaan-terra",
    "Layali": "https://www.alwataniah.com/products/layali",
    "Lemon Souffle": "https://www.alwataniah.com/products/lemon-souffle",
    "Nada": "https://www.alwataniah.com/products/nada",
    "Oud Mystery Intense": "https://www.alwataniah.com/products/oud-mystery-intense",
    "Praline Toffee": "https://www.alwataniah.com/products/praline-toffee",
    "Rose Eclat": "https://www.alwataniah.com/products/rose-eclat",
    "Rose Mystery Intense": "https://www.alwataniah.com/products/rose-mystery-intense",
    "Royal Oak I": "https://www.alwataniah.com/products/royal-oak-i",
    "Royal Oak II": "https://www.alwataniah.com/products/royal-oak-ii",
    "Sabah Al Ward": "https://www.alwataniah.com/products/sabah-al-ward",
    "Sabah Al Ward Sugar": "https://www.alwataniah.com/products/saba-al-ward-sugar",
    "Sahari": "https://www.alwataniah.com/products/sahari",
    "Special Oud": "https://www.alwataniah.com/products/special-oud",
    "Sultan Al Lail": "https://www.alwataniah.com/products/sultan-al-lail",
    "Turquois": "https://www.alwataniah.com/products/turquois"
}


NEW_EXPECTED = {
    "Milele": "https://www.alwataniah.com/products/milele",
    "Durrat Al Aroos": "https://www.alwataniah.com/products/durrat-al-aroos",
    "Thahaani": "https://www.alwataniah.com/products/thahaani",
    "Crème": "https://www.alwataniah.com/products/creme",
    "Watani Purple": "https://www.alwataniah.com/products/watani-purple",
    "Granada": "https://www.alwataniah.com/products/granada",
    "Tibyan": "https://www.alwataniah.com/products/tibyan",
    "Ghala": "https://www.alwataniah.com/products/ghala",
    "Sevilla": "https://www.alwataniah.com/products/sevilla",
    "Kenz Al Malik": "https://www.alwataniah.com/products/kenz-al-malik"
}

ADDITIONAL_EXPECTED = {
    "Nawal Alexandrite": "https://www.alwataniah.com/products/nawal-alexandrite",
    "Watani Noir": "https://www.alwataniah.com/products/watani-noir",
    "Fikrah": "https://www.alwataniah.com/products/fikrah",
    "Hayat": "https://www.alwataniah.com/products/hayat",
    "Marjaan": "https://www.alwataniah.com/products/marjaan",
    "Muheeb": "https://www.alwataniah.com/products/muheeb",
    "Shagaf Al Ward": "https://www.alwataniah.com/products/shagaf-al-ward",
    "Hala": "https://www.alwataniah.com/products/hala",
    "Nawal Bronzite": "https://www.alwataniah.com/products/nawal-bronzite",
    "Nawal Tanzanite": "https://www.alwataniah.com/products/nawal-tanzanite",
    "Nawal Fluorite": "https://www.alwataniah.com/products/nawal-fluorite",
    "Da'im": "https://www.alwataniah.com/products/da-im",
    "Duha": "https://www.alwataniah.com/products/duha",
    "Eqaab": "https://www.alwataniah.com/products/eqaab",
    "Tiara Pink": "https://www.alwataniah.com/products/tiara-pink",
    "Watani Intense Gold": "https://www.alwataniah.com/products/watani-intense-gold",
    "Shagaf Al Ward Gardenia": "https://www.alwataniah.com/products/shagaf-al-ward-gardenia",
    "Sabah Al Ward Garden of Eden": "https://www.alwataniah.com/products/sabah-al-ward-garden-of-eden",
    "Attar Al Wesal Elixir": "https://www.alwataniah.com/products/attar-al-wesal-elixir",
    "Ziyana": "https://www.alwataniah.com/products/ziyana"
}

FINAL_EXPECTED = {
    "Lazuli": "https://www.alwataniah.com/products/lazuli",
    "Fayyad": "https://www.alwataniah.com/products/fayyad",
    "Amnia": "https://www.alwataniah.com/products/amnia",
    "Lily": "https://www.alwataniah.com/products/lily",
    "Qasar Al Watan": "https://www.alwataniah.com/products/qasar-al-watan",
    "Rawaee Elite": "https://www.alwataniah.com/products/rawaee-elite",
    "Rawaee Monarch": "https://www.alwataniah.com/products/rawaee-monarch",
    "Emiran Selar": "https://www.alwataniah.com/products/emiran-selar",
    "Massad Royale": "https://www.alwataniah.com/products/massad-royale",
    "White Chocolate Ganache": "https://www.alwataniah.com/products/white-chocolate-ganache",
    "Sugar Rush": "https://www.alwataniah.com/products/sugar-rush"
}

IDENTITY_ONLY_EXPECTED = {
    "House Of Oud": "https://www.alwataniah.com/products/house-of-oud",
    "Anwan": "https://www.alwataniah.com/products/anwan"
}

class AlWataniahDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_all_forty_identities_have_official_100ml_edp_evidence(self):
        self.assertEqual(len(EXPECTED), 40)
        for name, url in EXPECTED.items():
            with self.subTest(product=name):
                matches = [p for p in self.products if p.get("brand_name") == "Al Wataniah" and p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertIn(100, product.get("formats_ml", []))
                matching = [v for v in self.variants if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(matching), 1)
                variant = matching[0]
                self.assertEqual(variant.get("size_ml"), 100)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("source_evidence_url"), url)


    def test_ten_more_existing_identities_have_official_100ml_edp_variants(self):
        family_path = Path(__file__).resolve().parents[1] / "family_registry.json"
        with family_path.open(encoding="utf-8") as handle:
            registry = json.load(handle)
        family = next(f for f in registry["families"] if f.get("family_id") == "al_wataniah_catalog")

        for name, url in NEW_EXPECTED.items():
            with self.subTest(product=name):
                product = next(
                    p for p in self.products
                    if p.get("brand_name") == "Al Wataniah" and p.get("canonical_name") == name
                )
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [100])

                variants = [v for v in self.variants if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("variant_id"), f"SHV-{product['product_id']}-100-000")
                self.assertEqual(variants[0].get("size_ml"), 100)
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(variants[0].get("source_evidence_url"), url)

                family_product = next(p for p in family["products"] if p.get("canonical_name") == name)
                self.assertEqual(family_product.get("aliases"), product.get("aliases"))
                self.assertEqual(family_product.get("formats_ml"), [100])



    def test_twenty_additional_existing_identities_have_official_100ml_edp_variants(self):
        family_path = Path(__file__).resolve().parents[1] / "family_registry.json"
        with family_path.open(encoding="utf-8") as handle:
            registry = json.load(handle)
        family = next(f for f in registry["families"] if f.get("family_id") == "al_wataniah_catalog")

        for name, url in ADDITIONAL_EXPECTED.items():
            with self.subTest(product=name):
                product = next(
                    p for p in self.products
                    if p.get("brand_name") == "Al Wataniah" and p.get("canonical_name") == name
                )
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [100])

                variants = [v for v in self.variants if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("variant_id"), f"SHV-{product['product_id']}-100-000")
                self.assertEqual(variants[0].get("size_ml"), 100)
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(variants[0].get("source_evidence_url"), url)

                family_product = next(p for p in family["products"] if p.get("canonical_name") == name)
                self.assertEqual(family_product.get("aliases"), product.get("aliases"))
                self.assertEqual(family_product.get("formats_ml"), [100])



    def test_final_eleven_detail_pages_have_official_100ml_edp_variants(self):
        family_path = Path(__file__).resolve().parents[1] / "family_registry.json"
        with family_path.open(encoding="utf-8") as handle:
            registry = json.load(handle)
        family = next(f for f in registry["families"] if f.get("family_id") == "al_wataniah_catalog")
        for name, url in FINAL_EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in self.products if p.get("brand_name") == "Al Wataniah" and p.get("canonical_name") == name)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [100])
                variants = [v for v in self.variants if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("variant_id"), f"SHV-{product['product_id']}-100-000")
                self.assertEqual(variants[0].get("size_ml"), 100)
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(variants[0].get("source_evidence_url"), url)
                family_product = next(p for p in family["products"] if p.get("canonical_name") == name)
                self.assertEqual(family_product.get("aliases"), product.get("aliases"))
                self.assertEqual(family_product.get("formats_ml"), [100])

    def test_two_identity_only_official_pages_do_not_invent_variants(self):
        for name, url in IDENTITY_ONLY_EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in self.products if p.get("brand_name") == "Al Wataniah" and p.get("canonical_name") == name)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertNotIn("concentration", product)
                self.assertNotIn("formats_ml", product)
                self.assertEqual([v for v in self.variants if v.get("product_id") == product["product_id"]], [])


if __name__ == "__main__":
    unittest.main()
