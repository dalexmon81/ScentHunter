"""Regression guard for the audited Gulf Orchid official store catalog."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
EXPECTED_URLS = {
    "Al Qasr": "https://shop-gulforchid.com/products/al-qasr-silver",
    "Al Qasr Dahab": "https://shop-gulforchid.com/products/al-qasr-gold",
    "Almalek": "https://shop-gulforchid.com/products/almalek-by-gulf-orchid-eau-de-parfum",
    "Angel Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-angel",
    "Angham": "https://shop-gulforchid.com/products/angham-by-gulf-orchid-eau-de-parfum",
    "Arabian Nights": "https://shop-gulforchid.com/products/arabian_nights_eau_de_parfum",
    "Baklava Bite": "https://shop-gulforchid.com/products/baklava-bite",
    "Bali": "https://shop-gulforchid.com/products/bali-by-gulf-orchid-eau-de-parfum",
    "Candy Bite": "https://shop-gulforchid.com/products/candy-bite",
    "Coco Blanco": "https://shop-gulforchid.com/products/coco-blanco",
    "Coffee Note": "https://shop-gulforchid.com/products/coffee_note_eau_de_parfum",
    "Cookie Bite": "https://shop-gulforchid.com/products/cookie-bite",
    "Cotton Candy Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-cotton-candy",
    "Creamy Pistachio": "https://shop-gulforchid.com/products/creamy_pistachio_eau_de_parfum",
    "Crème Caramel": "https://shop-gulforchid.com/products/creme_caramel_eau_de_parfum",
    "Dark Chocolate": "https://shop-gulforchid.com/products/dark_chocolate_eau_de_parfum",
    "El Capitan": "https://shop-gulforchid.com/products/el_capitan_eau_de_parfum",
    "El Capitan Elixir": "https://shop-gulforchid.com/products/el_capitan_elixir_eau_de_parfum",
    "El Capitan Extreme": "https://shop-gulforchid.com/products/el_capitan_extreme_eau_de_parfum",
    "El Capitan Legacy": "https://shop-gulforchid.com/products/el_capitan_legacy_eau_de_parfum",
    "Evening Dance": "https://shop-gulforchid.com/products/evening_dance_eau_de_parfum",
    "Exotic Oud": "https://shop-gulforchid.com/products/exotic_oud_eau_de_parfum",
    "Flame": "https://shop-gulforchid.com/products/flame-by-gulf-orchid-eau-de-parfum",
    "Heavenly Lychee": "https://shop-gulforchid.com/products/heavenly_lychee_eau_de_parfum",
    "Love & Beyond": "https://shop-gulforchid.com/products/love_-_beyond_eau_de_parfum",
    "Love Me Now": "https://shop-gulforchid.com/products/love_me_now_eau_de_parfum",
    "Mango Heaven": "https://shop-gulforchid.com/products/mango-heaven",
    "Mango Ice": "https://shop-gulforchid.com/products/mango_ice_eau_de_parfum",
    "Mangotini": "https://shop-gulforchid.com/products/mangotini_eau_de_parfum",
    "Marine": "https://shop-gulforchid.com/products/marine-by-gulf-orchid-eau-de-parfum",
    "Marshmallow": "https://shop-gulforchid.com/products/marshmallow",
    "Mawj": "https://shop-gulforchid.com/products/mawj",
    "Melody": "https://shop-gulforchid.com/products/melody_eau_de_parfum",
    "Mojito Obsession": "https://shop-gulforchid.com/products/mojito_obsession_eau_de_parfum",
    "Mood for Oud": "https://shop-gulforchid.com/products/mood_for_oud_eau_de_parfum",
    "Mysterious Tahara Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-mysterious-tahara",
    "Naseem": "https://shop-gulforchid.com/products/naseem_eau_de_parfum",
    "Naughty Vanilla": "https://shop-gulforchid.com/products/naughty-vanilla",
    "Nobilty": "https://shop-gulforchid.com/products/nobilty_eau_de_parfum",
    "Old Fashioned": "https://shop-gulforchid.com/products/old_fashioned_eau_de_parfum",
    "Omsiah": "https://shop-gulforchid.com/products/omsiah_eau_de_parfum",
    "Pacific": "https://shop-gulforchid.com/products/pacific_eau_de_parfum",
    "Piña Colada Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-pina-colada",
    "Pink Marshmallow": "https://shop-gulforchid.com/products/pink-marshmallow",
    "Pistachio Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-pistachio",
    "Pomegranate Musk": "https://shop-gulforchid.com/products/pomegranate-musk-eau-de-parfum-60ml",
    "Rare Rose": "https://shop-gulforchid.com/products/rare_rose_eau_de_parfum",
    "Riwaya": "https://shop-gulforchid.com/products/riwaya_eau_de_parfum",
    "Riwaya Chapter I": "https://shop-gulforchid.com/products/riwaya_chapter_1_brown_eau_de_parfum",
    "Riwaya Chapter II": "https://shop-gulforchid.com/products/riwaya_chapter_2_eau_de_parfum",
    "Romantic For Her": "https://shop-gulforchid.com/products/romantic-perfume-by-gulf-orchid-eau-de-parfum-for-women",
    "Romantic For Him": "https://shop-gulforchid.com/products/romantic-perfume-by-gulf-orchid-eau-de-parfum-for-men",
    "Ruby Fizz": "https://shop-gulforchid.com/products/ruby_fizz_eau_de_parfum",
    "Shiekh Aloud Navy": "https://shop-gulforchid.com/products/shiekh_aloud_blue-navy_eau_de_parfum",
    "Shisha": "https://shop-gulforchid.com/products/shisha_eau_de_parfum",
    "Sweet Cherry Kiss": "https://shop-gulforchid.com/products/sweet_cherry_kiss_eau_de_parfum",
    "Sweet Heaven": "https://shop-gulforchid.com/products/sweet-heaven-by-gulf-orchid-eau-de-parfum-20ml",
    "Sweet Heaven Cherry": "https://shop-gulforchid.com/products/sweet_heaven_cherry_20_ml_eau_de_parfum",
    "Sweet Heaven Extreme": "https://shop-gulforchid.com/products/sweet-heaven-extreme-by-gulf-orchid-eau-de-parfum-20ml",
    "Sweet Heaven Ice": "https://shop-gulforchid.com/products/sweet_heaven_ice_eau_de_parfum",
    "Sweet Heaven Tobacco": "https://shop-gulforchid.com/products/sweet_heaven_tobacco_20_ml_eau_de_parfum",
    "Sweet Like Candy": "https://shop-gulforchid.com/products/sweet_like_candy_eau_de_parfum",
    "Tahara Vanilla Musk": "https://shop-gulforchid.com/products/musk-eau-de-parfum-60-ml",
    "Tahiti Colada": "https://shop-gulforchid.com/products/tahiti_colada_eau_de_parfum",
    "Toffee Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-toffee",
    "Toxic Love": "https://shop-gulforchid.com/products/toxic_love_eau_de_parfum",
    "Vanilla Addiction": "https://shop-gulforchid.com/products/vanilla_addiction_eau_de_parfum",
    "Vanilla Latte": "https://shop-gulforchid.com/products/vanilla_latte_eau_de_parfum",
    "Vanilla on the Beach": "https://shop-gulforchid.com/products/vanilla_on_the_beach_eau_de_parfum",
    "Yacht Club": "https://shop-gulforchid.com/products/yacht_club_eau_de_parfum",
}
EXPECTED_VARIANTS = {
    "Al Qasr": [100],
    "Al Qasr Dahab": [100],
    "Almalek": [100],
    "Angel Musk": [60],
    "Angham": [110],
    "Baklava Bite": [100],
    "Bali": [100],
    "Candy Bite": [100],
    "Coco Blanco": [100],
    "Coffee Note": [100],
    "Cookie Bite": [100],
    "Creamy Pistachio": [100],
    "Crème Caramel": [100],
    "Dark Chocolate": [100],
    "El Capitan": [100],
    "El Capitan Elixir": [100],
    "El Capitan Extreme": [100],
    "El Capitan Legacy": [100],
    "Evening Dance": [110],
    "Exotic Oud": [100],
    "Flame": [110],
    "Heavenly Lychee": [100],
    "Love & Beyond": [100],
    "Love Me Now": [100],
    "Mango Heaven": [100],
    "Mango Ice": [100],
    "Mangotini": [100],
    "Marine": [110],
    "Marshmallow": [100],
    "Mawj": [110],
    "Melody": [100],
    "Mojito Obsession": [100],
    "Mood for Oud": [110],
    "Mysterious Tahara Musk": [60],
    "Naseem": [100],
    "Naughty Vanilla": [100],
    "Nobilty": [100],
    "Old Fashioned": [100],
    "Omsiah": [100],
    "Pacific": [100],
    "Piña Colada Musk": [60],
    "Pink Marshmallow": [100],
    "Pistachio Musk": [60],
    "Pomegranate Musk": [60],
    "Rare Rose": [100],
    "Riwaya": [100],
    "Riwaya Chapter I": [100],
    "Riwaya Chapter II": [100],
    "Romantic For Her": [100],
    "Romantic For Him": [100],
    "Ruby Fizz": [100],
    "Shiekh Aloud Navy": [100],
    "Shisha": [100],
    "Sweet Cherry Kiss": [100],
    "Sweet Heaven": [20,100],
    "Sweet Heaven Cherry": [20, 100],
    "Sweet Heaven Extreme": [20,100],
    "Sweet Heaven Ice": [20,100],
    "Sweet Heaven Tobacco": [20, 100],
    "Sweet Like Candy": [100],
    "Tahiti Colada": [100],
    "Toffee Musk": [60],
    "Toxic Love": [100],
    "Vanilla Addiction": [100],
    "Vanilla Latte": [100],
    "Vanilla on the Beach": [100],
    "Yacht Club": [100],
}
COLLECTION_ONLY_LABELS = ("Asala", "Hamsat", "Hikma", "Jawhara", "Jewel", "Turath")
BUNDLES = ("Sweet Edition", "Flirt Edition")


class GulfOrchidOfficialCollectionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (BACKEND / "product_catalog.json").open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = [p for p in cls.catalog["products"] if p.get("brand") == "Gulf Orchid"]
        cls.by_name = {p.get("canonical_name"): p for p in cls.products}
        cls.variants = cls.catalog["variants"]

    def test_audited_official_collection_pages_are_represented(self):
        self.assertEqual(set(self.by_name), set(EXPECTED_URLS))
        self.assertEqual(len(self.products), 70)

    def test_all_canonical_names_have_official_product_page_provenance(self):
        for name, url in EXPECTED_URLS.items():
            with self.subTest(name=name):
                row = self.by_name[name]
                self.assertEqual(row.get("source_url"), url)
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("concentration"), "Eau de Parfum")

    def test_only_explicitly_documented_sizes_become_variants(self):
        for name, sizes in EXPECTED_VARIANTS.items():
            with self.subTest(name=name):
                row = self.by_name[name]
                self.assertEqual(row.get("formats_ml"), sizes)
                actual = sorted(v["size_ml"] for v in self.variants if v.get("product_id") == row["product_id"])
                self.assertEqual(actual, sorted(sizes))
                for variant in (v for v in self.variants if v.get("product_id") == row["product_id"]):
                    self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                    self.assertTrue(variant.get("source_evidence_url"))

    def test_products_without_verified_size_have_no_invented_variants(self):
        for name in ("Cotton Candy Musk", "Tahara Vanilla Musk", "Arabian Nights"):
            with self.subTest(name=name):
                row = self.by_name[name]
                self.assertNotIn("formats_ml", row)
                self.assertFalse(any(v.get("product_id") == row["product_id"] for v in self.variants))

    def test_collection_labels_and_gift_bundles_are_not_canonical_perfumes(self):
        names = set(self.by_name)
        for name in COLLECTION_ONLY_LABELS + BUNDLES:
            with self.subTest(name=name):
                self.assertNotIn(name, names)

    def test_vanilla_aura_and_vanilla_voyage_are_not_misattributed_to_gulf_orchid(self):
        names = set(self.by_name)
        self.assertNotIn("Vanilla Aura", names)
        self.assertNotIn("Vanilla Voyage", names)

    def test_family_registry_matches_the_audited_gulf_orchid_product_set(self):
        with (BACKEND / "family_registry.json").open(encoding="utf-8") as handle:
            registry = json.load(handle)
        family = next(row for row in registry["families"] if row.get("family_id") == "gulf_orchid_catalog")
        names = {row.get("canonical_name") for row in family["products"]}
        self.assertEqual(names, set(EXPECTED_URLS))

    def test_no_duplicate_gulf_orchid_product_names(self):
        names = [p.get("canonical_name", "").casefold() for p in self.products]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
