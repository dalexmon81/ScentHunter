"""Regression tests for Paris Corner official collection reconciliation."""
import json
import unittest
import unicodedata
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
OFFICIAL_NAMES = ["Affogato Al Caffe","Aira","Arwa","Atoof","Azm","Bayn Al Asrar","Caramel Bash","Choco Lait","Ciao Citrus","Confidential 100ML","Cosmic Giardino","Dar Al Oud","Date Caramel","December Ambar","December Rose","December Vanilla","Dulzura","Dulzura Vanilla Envie","Eshal Musk","Eshal Vanilla","Eternal Coffee","Eternal Meadows","Eternal Musk","Farah","Fatal Embrace","Fayora","Fayora Oshino","Green Bet","Heer","Hurriya","Ibisco Nirvana","Indomitable","Jardin des Papillons","Kaheela Platinum","Khair","Khair Confection","Khair Felicity","Khair Fusion","Khair Peach Delulu","Khair Pistachio","Khayal 100ML","Manaal","Marshmallow Blush","Mawj Appletini","Mawj Cognac Blaze","Mawj Moscow Mule","Mehwish","Midnight Sin by Daniel René","Miel Obscura","Miel Vanille","Minya 100ML","Minya Caramel Dulce","Minya Coco Lush","Misty Dawn Musk Collection","Molten Caramel","Mysterium","Nada Blumingle","Nada Whimsical","Nada Wink","Nouf","Ophidian Black Cherry 100ML","Ophidian Mango Bliss","Ophidian Sweet Surrender","Oravea","Oud Faek","Oud Wahaaj","Papillon des Vents","Perseviron","Perseviron Fig Hug","Pinkling","Plum Liquor","Prodigy","Prodigy Noir","Qawafi 100ML","Qissa","Qissa Delicious","Qissa Gala","Qissa Pink","Rawq","Reham Rose Petals","Reham Vanilla Mood","Reham Wild Mineral","Rifaaqat","Rifaaqat Adorn","Rua","Rua Radiant Roses","Soothing Zephyr","Taskeen","Taskeen Caramel Cascade","Taskeen Lactea Divina","Taskeen Marina","Taskeen Wowie","Tawaaq","The Show Magnifique","Tranquil Night Musk Collection","Twilight Shadow Musk Collection","Virilis","Zahi","Zahri Amara","Zaman Al Ula","Zariya","Zodiac","Zodiac Lunaris","Zodiac Solmaris","Zodiac Stratos"]

class ParisCornerOfficialCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = [p for p in cls.catalog["products"] if p.get("brand") == "Paris Corner"]

    @staticmethod
    def normalize(value):
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return "".join(ch for ch in value.casefold() if ch.isalnum())

    def test_all_official_collection_names_are_represented(self):
        names = {self.normalize(name) for p in self.products for name in [p["canonical_name"], *(p.get("aliases") or [])]}
        for name in OFFICIAL_NAMES:
            with self.subTest(name=name):
                self.assertIn(self.normalize(name), names)

    def test_new_official_identities_present(self):
        names = {self.normalize(p["canonical_name"]) for p in self.products}
        self.assertIn(self.normalize("The Show Magnifique"), names)
        self.assertIn(self.normalize("Zariya"), names)

    def test_no_duplicate_product_ids_or_brand_names(self):
        ids = [p["product_id"] for p in self.catalog["products"]]
        pairs = [(p.get("brand"), self.normalize(p["canonical_name"])) for p in self.catalog["products"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))

if __name__ == "__main__":
    unittest.main()
