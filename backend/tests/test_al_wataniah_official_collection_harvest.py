"""Al Wataniah official perfume collection harvest regression tests."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Milele": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Turquois": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Cloud": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Crème": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Sabah Al Ward": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Sabah Al Ward Sugar": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Attar Al Wesal": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Special Oud": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Durrat Al Aroos": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Bareeq Al Dhahab": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Rose Mystery Intense": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Granada": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Ameerati": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Ameeri": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Oud Mystery Intense": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Thahaani": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Castilla": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Sultan Al Lail": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Al Layl": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Ghala": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Kenz Al Malik": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Sevilla": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Tibyan": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Watani Purple": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Nawal Alexandrite": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Watani Noir": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Abyat": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Alya": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Fikrah": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Hayat": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Marjaan": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Muheeb": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Shagaf Al Ward": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Hala": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Nawal Bronzite": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Nawal Tanzanite": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Nawal Fluorite": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Da'im": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Duha": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Eqaab": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Tiara Pink": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Watani Intense Gold": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Shagaf Al Ward Gardenia": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Sabah Al Ward Garden of Eden": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Attar Al Wesal Elixir": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Fayroz": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Ziyana": [
        "Classic",
        "https://www.alwataniah.com/collections/classic"
    ],
    "Kayaan Midnight": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Kayaan Classic": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Kayaan Terra": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Lazuli": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Kayaan Gold": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "House Of Oud": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Fayyad": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Sahari": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Amnia": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Baraa": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Layali": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Anwan": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Lily": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Nada": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Qasar Al Watan": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Rawaee Elite": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Rawaee Monarch": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Rawaee Noble": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Rawaee Regina": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Redaa": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Emiran Selar": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Emiran": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Ain Emarat": [
        "Niche",
        "https://www.alwataniah.com/collections/niche"
    ],
    "Ain Emarat Extrait": [
        "Niche",
        "https://www.alwataniah.com/collections/niche"
    ],
    "Arya": [
        "Niche",
        "https://www.alwataniah.com/collections/niche"
    ],
    "Arya Peony Rose": [
        "Niche",
        "https://www.alwataniah.com/collections/niche"
    ],
    "Royal Oak I": [
        "Niche",
        "https://www.alwataniah.com/collections/niche"
    ],
    "Royal Oak II": [
        "Niche",
        "https://www.alwataniah.com/collections/niche"
    ],
    "Al Daiem": [
        "Niche",
        "https://www.alwataniah.com/collections/niche"
    ],
    "Al Daiem Elixir": [
        "Niche",
        "https://www.alwataniah.com/collections/niche"
    ],
    "Massad Royale": [
        "Niche",
        "https://www.alwataniah.com/collections/niche"
    ],
    "Lemon Souffle": [
        "Munchies",
        "https://www.alwataniah.com/collections/munchies"
    ],
    "Praline Toffee": [
        "Munchies",
        "https://www.alwataniah.com/collections/munchies"
    ],
    "Rose Eclat": [
        "Munchies",
        "https://www.alwataniah.com/collections/munchies"
    ],
    "Choco Truffle": [
        "Munchies",
        "https://www.alwataniah.com/collections/munchies"
    ],
    "Golden Honey": [
        "Munchies",
        "https://www.alwataniah.com/collections/munchies"
    ],
    "Brownie Bite": [
        "Munchies",
        "https://www.alwataniah.com/collections/munchies"
    ],
    "White Chocolate Ganache": [
        "Munchies",
        "https://www.alwataniah.com/collections/munchies"
    ],
    "Sugar Rush": [
        "Munchies",
        "https://www.alwataniah.com/collections/munchies"
    ]
}

VERIFIED_DETAIL_URLS = {
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
    "Turquois": "https://www.alwataniah.com/products/turquois",
    "Milele": "https://www.alwataniah.com/products/milele",
    "Durrat Al Aroos": "https://www.alwataniah.com/products/durrat-al-aroos",
    "Thahaani": "https://www.alwataniah.com/products/thahaani",
    "Crème": "https://www.alwataniah.com/products/creme",
    "Watani Purple": "https://www.alwataniah.com/products/watani-purple",
    "Granada": "https://www.alwataniah.com/products/granada",
    "Tibyan": "https://www.alwataniah.com/products/tibyan",
    "Ghala": "https://www.alwataniah.com/products/ghala",
    "Sevilla": "https://www.alwataniah.com/products/sevilla",
    "Kenz Al Malik": "https://www.alwataniah.com/products/kenz-al-malik",
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
    "Ziyana": "https://www.alwataniah.com/products/ziyana",
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


VERIFIED_IDENTITY_ONLY_URLS = {
    "House Of Oud": "https://www.alwataniah.com/products/house-of-oud",
    "Anwan": "https://www.alwataniah.com/products/anwan"
}

class AlWataniahOfficialCollectionHarvestTests(unittest.TestCase):
    def test_all_official_collection_fragrances_are_present_once(self):
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand") == "Al Wataniah"
        }
        self.assertEqual(len(products), 86)
        self.assertEqual(set(products), set(EXPECTED))
        for name, (collection, listing_url) in EXPECTED.items():
            with self.subTest(product=name):
                product = products[name]
                self.assertEqual(product.get("collection_name"), collection)
                self.assertEqual(product.get("brand_name"), "Al Wataniah")
                self.assertIn(product.get("identity_status"), {"source_listed_name", "source_verified_name"})
                if name in VERIFIED_DETAIL_URLS:
                    self.assertEqual(product.get("identity_status"), "source_verified_name")
                    self.assertEqual(product.get("source_product_url"), VERIFIED_DETAIL_URLS[name])
                    self.assertEqual(product.get("source_evidence_url"), VERIFIED_DETAIL_URLS[name])
                    self.assertIn(product.get("source_url"), {listing_url, VERIFIED_DETAIL_URLS[name]})
                    self.assertEqual(product.get("concentration"), "Eau de Parfum")
                    self.assertIn(100, product.get("formats_ml", []))
                elif name in VERIFIED_IDENTITY_ONLY_URLS:
                    self.assertEqual(product.get("identity_status"), "source_verified_name")
                    self.assertEqual(product.get("source_product_url"), VERIFIED_IDENTITY_ONLY_URLS[name])
                    self.assertEqual(product.get("source_evidence_url"), VERIFIED_IDENTITY_ONLY_URLS[name])
                    self.assertIn(product.get("source_url"), {listing_url, VERIFIED_IDENTITY_ONLY_URLS[name]})
                    self.assertNotIn("concentration", product)
                    self.assertNotIn("formats_ml", product)
                else:
                    self.assertEqual(product.get("identity_status"), "source_listed_name")
                    self.assertEqual(product.get("source_url"), listing_url)

    def test_every_catalog_identity_is_in_family_registry(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "al_wataniah_catalog")
        names = [p["canonical_name"] for p in family["products"]]
        self.assertEqual(len(names), len(set(names)))
        for name in EXPECTED:
            with self.subTest(product=name):
                self.assertIn(name, names)

    def test_only_explicit_product_detail_variants_are_retained(self):
        alwataniah_ids = {
            p["product_id"] for p in CATALOG["products"]
            if p.get("brand") == "Al Wataniah"
        }
        variants = [v for v in CATALOG["variants"] if v.get("product_id") in alwataniah_ids]
        variant_names = {
            next(p["canonical_name"] for p in CATALOG["products"] if p["product_id"] == v["product_id"])
            for v in variants
        }
        self.assertEqual(len(variants), len(VERIFIED_DETAIL_URLS))
        self.assertEqual(variant_names, set(VERIFIED_DETAIL_URLS))
        for variant in variants:
            with self.subTest(variant=variant.get("variant_id")):
                self.assertEqual(variant.get("size_ml"), 100)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                product = next(p for p in CATALOG["products"] if p["product_id"] == variant["product_id"])
                self.assertEqual(variant.get("source_evidence_url"), product.get("source_product_url"))
                self.assertEqual(variant.get("variant_id"), f"SHV-{variant['product_id']}-100-000")


if __name__ == "__main__":
    unittest.main()
