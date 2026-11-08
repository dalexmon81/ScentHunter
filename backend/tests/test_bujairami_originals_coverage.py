"""Coverage tests for Bujairami's UAE catalog and Australian Originals collection."""
import json
import unittest
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "product_catalog.json"
FAMILY_REGISTRY_PATH = ROOT / "family_registry.json"

UAE_CURRENT = [
    "2000", "Absolute Power", "ACE", "Agha", "Ahla Sabiyeh", "Apex",
    "Arabian Valley", "Beautiful Lady", "Blush", "Booz Extreme", "Boss Life",
    "Boujee", "Candy Carousel", "Candy Crush", "Catch Me At Sunset", "Chic Wood",
    "Chroma", "City Life", "Cosmic Fever", "Damn Wild", "Darkwood", "Date Night",
    "Dead Serious", "Delulu", "Dom", "Drip No. 7", "Dubai Crush", "Emperor",
    "Enforcer", "Executor", "Extra Pulse", "Fairy Dust", "Freeze", "Full Throttle",
    "Gem", "Gladiator", "Golden Night", "Grand Affair", "Happy Place", "Hectic",
    "Helou", "Her", "High Roller", "Honcho", "Houdini", "Ibiza", "Inferno",
    "KingsMan", "Last Kingdom", "Legacy", "Limonana", "Lychee", "Mad Love", "Madam",
    "Madness", "Mafia Boss", "Mi Amor", "Miss Vanilla", "Mohabbat", "Mojito Splash",
    "Mood Swings", "Mysterious", "New York", "Next Level", "Nile Bloom", "No Limit",
    "Noctis Blue", "Non Stop", "Nuclear", "Obsidian", "Ocean Eyes", "Omega",
    "Only Ever", "Perfect Life", "Petals of Paradise", "Power", "Powerful Lady",
    "Psycho", "Pulse", "Pulse Intense", "Rain Man", "Rare Edition", "Red Eclipse",
    "Red Static", "Resolution", "Rizz", "Ruby Oud", "Ruthless Vanilla", "Saddle Up",
    "Say Less", "Silent Halo", "Smokilla", "Sovereign", "Special Day", "Sugar Rush",
    "Suns Out", "Sweet Banana", "Sweet Rebel", "Tangy", "Tea Splash", "Tempted",
    "Tenfold", "The Aftermath", "The Rock Intensely", "The Rock Powerfully",
    "The Sheikh", "Too Damn Good", "Top Tier", "Unforgettable", "V-Luxe",
    "Vanilla Dream", "Vanilla Storm", "Vibration", "When in Rome", "Why Not?",
    "Wicked", "Ya Habibi",
]

AU_ORIGINALS_PERFUMES = [
    "Ruthless Vanilla", "The Aftermath", "Australian Watermelon", "Sasha",
    "Top Life", "Iconic", "Her", "The F*ck Up", "Luxe Noir", "Woolloomooloo",
    "Australian Tonka", "Dubai Crush", "Snow White", "Mohabbat", "Down Under",
    "Coco Dream", "HIM", "Love Spell", "Queens Avenue", "Gold Coast", "Riverina",
    "Happy Hour", "Aussie Glow", "Apple Crumble", "Knefeh", "Madeira Cake", "Gday",
    "Boujee Oud", "Midnight in Melbourne", "Harbour Tea", "Cherry Cherry Lady",
    "Pistachio Cake", "Mousse Cake", "Gold Coast Shiraz", "No.1 Father",
    "Pretty F**ked Up", "Vicious", "Sunset Bay",
]

NEW_PRODUCTS = {
    "Sasha": ("https://bujairami.com.au/products/sasha-original-creation", None, None),
    "Iconic": ("https://bujairami.com.au/products/iconic-by-bujairami", [100], None),
    "Australian Tonka": ("https://bujairami.com.au/products/australian-tonka-original-creation", [100], None),
    "Happy Hour": ("https://bujairami.com.au/products/happy-hour-inspired-by-mango-mood-phlur", [100], None),
    "Boujee Oud": ("https://bujairami.com.au/products/sexy-oud-original-creation-extrait", None, "Extrait de Parfum"),
    "Mousse Cake": ("https://bujairami.com.au/products/mousse-cake-original-creation", None, None),
    "No.1 Father": ("https://bujairami.com.au/products/no-1-father-original-creation", None, None),
    "Pretty F**ked Up": ("https://bujairami.com.au/products/pretty-f-ked-up-original-creation-50ml", [50], None),
    "Vicious": ("https://bujairami.com.au/products/vicious-inspired-by-dirty-heaven-borntostandout", None, None),
    "Sunset Bay": ("https://bujairami.com.au/products/sunset-bay-inspired-by-cap-camarat-memo-paris", None, None),
}

EXPECTED_VARIANTS = [
    ("Iconic", 100, "https://bujairami.com.au/products/iconic-by-bujairami"),
    ("Australian Tonka", 100, "https://bujairami.com.au/products/australian-tonka-original-creation"),
    ("Happy Hour", 100, "https://bujairami.com.au/products/happy-hour-inspired-by-mango-mood-phlur"),
    ("Pretty F**ked Up", 50, "https://bujairami.com.au/products/pretty-f-ked-up-original-creation-50ml"),
    ("The F*ck Up", 50, "https://bujairami.com.au/products/the-f-ck-up-original-creation"),
    ("Love Spell", 50, "https://bujairami.com.au/products/love-spell-original-creation-50ml"),
    ("Love Spell", 100, "https://bujairami.com.au/products/love-spell-original-creation"),
]

class BujairamiOriginalsCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        with FAMILY_REGISTRY_PATH.open(encoding="utf-8") as handle:
            cls.registry = json.load(handle)
        cls.products = [p for p in cls.catalog["products"] if p.get("brand") == "Bujairami"]
        cls.family = next(f for f in cls.registry["families"] if f.get("family_id") == "bujairami_catalog")

    @staticmethod
    def normalize(value):
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return "".join(ch for ch in value.casefold() if ch.isalnum())

    def all_names_and_aliases(self):
        return {
            self.normalize(value)
            for product in self.products
            for value in [product["canonical_name"], *product.get("aliases", [])]
        }

    def test_all_117_current_uae_collection_names_are_present(self):
        names = self.all_names_and_aliases()
        self.assertEqual(len(UAE_CURRENT), 117)
        for name in UAE_CURRENT:
            with self.subTest(name=name):
                self.assertIn(self.normalize(name), names)

    def test_all_38_australian_originals_perfumes_are_present(self):
        names = self.all_names_and_aliases()
        self.assertEqual(len(AU_ORIGINALS_PERFUMES), 38)
        for name in AU_ORIGINALS_PERFUMES:
            with self.subTest(name=name):
                self.assertIn(self.normalize(name), names)

    def test_new_original_products_have_first_party_product_pages(self):
        by_name = {p["canonical_name"]: p for p in self.products}
        for name, (url, formats, concentration) in NEW_PRODUCTS.items():
            with self.subTest(name=name):
                product = by_name[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product.get("formats_ml"), formats)
                self.assertEqual(product.get("concentration"), concentration)
                self.assertEqual(product["family_id"], "bujairami_catalog")

    def test_known_size_variants_are_explicit_and_traceable(self):
        by_name = {p["canonical_name"]: p for p in self.products}
        for name, size, url in EXPECTED_VARIANTS:
            with self.subTest(name=name, size=size):
                product = by_name[name]
                self.assertIn(size, product["formats_ml"])
                matching = [
                    v for v in self.catalog["variants"]
                    if v["product_id"] == product["product_id"] and v["size_ml"] == size
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0]["source_url"], url)
                self.assertNotIn("concentration", matching[0])

    def test_family_registry_contains_all_new_originals(self):
        family_names = {
            self.normalize(p["canonical_name"])
            for p in self.family["products"]
        }
        for name in NEW_PRODUCTS:
            with self.subTest(name=name):
                self.assertIn(self.normalize(name), family_names)

    def test_distinct_originals_are_not_collapsed(self):
        names = {self.normalize(p["canonical_name"]) for p in self.products}
        self.assertIn(self.normalize("Boujee Oud"), names)
        self.assertIn(self.normalize("Boujee"), names)
        self.assertIn(self.normalize("Pretty F**ked Up"), names)
        self.assertIn(self.normalize("The F*ck Up"), names)
        self.assertIn(self.normalize("Happy Hour"), names)
        self.assertIn(self.normalize("Happy Place"), names)

    def test_body_spray_is_not_in_the_perfume_catalog(self):
        names = self.all_names_and_aliases()
        self.assertNotIn(self.normalize("Almura Body Spray"), names)

    def test_no_duplicate_bujairami_product_ids_or_canonical_names(self):
        ids = [p["product_id"] for p in self.products]
        names = [self.normalize(p["canonical_name"]) for p in self.products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(names), len(set(names)))

if __name__ == "__main__":
    unittest.main()
