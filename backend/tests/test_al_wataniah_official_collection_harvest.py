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
        "https://www.alwataniah.com/products/sabah-al-ward"
    ],
    "Sabah Al Ward Sugar": [
        "Classic",
        "https://www.alwataniah.com/products/saba-al-ward-sugar"
    ],
    "Attar Al Wesal": [
        "Classic",
        "https://www.alwataniah.com/products/attar-al-wesal"
    ],
    "Special Oud": [
        "Classic",
        "https://www.alwataniah.com/products/special-oud"
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
        "https://www.alwataniah.com/products/ameerati"
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
        "https://www.alwataniah.com/products/kayaan-midnight"
    ],
    "Kayaan Classic": [
        "Eternal",
        "https://www.alwataniah.com/products/kayaan-classic"
    ],
    "Kayaan Terra": [
        "Eternal",
        "https://www.alwataniah.com/products/kayaan-terra"
    ],
    "Lazuli": [
        "Eternal",
        "https://www.alwataniah.com/collections/eternal"
    ],
    "Kayaan Gold": [
        "Eternal",
        "https://www.alwataniah.com/products/kayaan-gold"
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
        "https://www.alwataniah.com/products/ain-emarat"
    ],
    "Ain Emarat Extrait": [
        "Niche",
        "https://www.alwataniah.com/products/ain-emarat-extrait"
    ],
    "Arya": [
        "Niche",
        "https://www.alwataniah.com/products/arya"
    ],
    "Arya Peony Rose": [
        "Niche",
        "https://www.alwataniah.com/products/arya-peony-rose"
    ],
    "Royal Oak I": [
        "Niche",
        "https://www.alwataniah.com/products/royal-oak-i"
    ],
    "Royal Oak II": [
        "Niche",
        "https://www.alwataniah.com/products/royal-oak-ii"
    ],
    "Al Daiem": [
        "Niche",
        "https://www.alwataniah.com/products/al-daiem"
    ],
    "Al Daiem Elixir": [
        "Niche",
        "https://www.alwataniah.com/products/al-daiem-elixir"
    ],
    "Massad Royale": [
        "Niche",
        "https://www.alwataniah.com/collections/niche"
    ],
    "Lemon Souffle": [
        "Munchies",
        "https://www.alwataniah.com/products/lemon-souffle"
    ],
    "Praline Toffee": [
        "Munchies",
        "https://www.alwataniah.com/products/praline-toffee"
    ],
    "Rose Eclat": [
        "Munchies",
        "https://www.alwataniah.com/products/rose-eclat"
    ],
    "Choco Truffle": [
        "Munchies",
        "https://www.alwataniah.com/products/choco-truffle"
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
                if "/products/" in listing_url:
                    self.assertEqual(product.get("identity_status"), "source_verified_name")
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
        self.assertEqual(len(variants), 2)
        self.assertEqual(
            {next(p["canonical_name"] for p in CATALOG["products"] if p["product_id"] == v["product_id"]) for v in variants},
            {"Lemon Souffle", "Choco Truffle"},
        )


if __name__ == "__main__":
    unittest.main()
