"""Regression guard for Gulf Orchid official perfume collection reconciliation."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
OFFICIAL_COLLECTION = "https://shop-gulforchid.com/collections/gulf-orchid-perfume"

EXPECTED = {
    "Vanilla Addiction": "https://shop-gulforchid.com/products/vanilla_addiction_eau_de_parfum",
    "Mango Ice": "https://shop-gulforchid.com/products/mango_ice_eau_de_parfum",
    "Cotton Candy Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-cotton-candy",
    "Tahara Vanilla Musk": "https://shop-gulforchid.com/products/musk-eau-de-parfum-60-ml",
    "Sweet Heaven 20ML": "https://shop-gulforchid.com/products/sweet-heaven-by-gulf-orchid-eau-de-parfum-20ml",
    "Pink Marshmallow": "https://shop-gulforchid.com/products/pink-marshmallow",
    "Coco Blanco": "https://shop-gulforchid.com/products/coco-blanco",
    "Exotic Oud": "https://shop-gulforchid.com/products/exotic_oud_eau_de_parfum",
    "Vanilla Latte": "https://shop-gulforchid.com/products/vanilla_latte_eau_de_parfum",
    "Cookie Bite": "https://shop-gulforchid.com/products/cookie-bite",
    "Sweet Like Candy": OFFICIAL_COLLECTION,
    "Sweet Heaven Extreme 20ML": OFFICIAL_COLLECTION,
    "Piña Colada Musk": OFFICIAL_COLLECTION,
}

# These names occur as collection labels, not as independently evidenced
# Gulf Orchid perfume product identities in the audited source snapshot.
COLLECTION_ONLY_LABELS = (
    "Al Qasr", "Asala", "Hamsat", "Hikma",
    "Jawhara", "Jewel", "Riwaya", "Turath",
)


class GulfOrchidOfficialCollectionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = [
            row for row in cls.catalog["products"]
            if row.get("brand") == "Gulf Orchid"
        ]

    def test_officially_listed_gulf_orchid_perfumes_have_exact_source_provenance(self):
        by_name = {row.get("canonical_name"): row for row in self.products}
        self.assertEqual(set(by_name), set(EXPECTED))
        for name, source_url in EXPECTED.items():
            with self.subTest(name=name):
                row = by_name[name]
                self.assertEqual(row.get("source_url"), source_url)
                self.assertEqual(row.get("identity_status"), "source_listed_name")
                self.assertNotIn("concentration", row)
                self.assertNotIn("formats_ml", row)

    def test_collection_labels_are_not_canonical_perfume_products(self):
        names = {row.get("canonical_name") for row in self.products}
        for name in COLLECTION_ONLY_LABELS:
            with self.subTest(name=name):
                self.assertNotIn(name, names)

    def test_vanilla_aura_and_vanilla_voyage_are_not_misattributed_to_gulf_orchid(self):
        names = {row.get("canonical_name") for row in self.products}
        self.assertNotIn("Vanilla Aura", names)
        self.assertNotIn("Vanilla Voyage", names)

    def test_family_registry_matches_the_audited_gulf_orchid_product_set(self):
        registry_path = Path(__file__).resolve().parents[1] / "family_registry.json"
        with registry_path.open(encoding="utf-8") as handle:
            registry = json.load(handle)
        family = next(
            row for row in registry["families"]
            if row.get("family_id") == "gulf_orchid_catalog"
        )
        names = {row.get("canonical_name") for row in family["products"]}
        self.assertEqual(names, set(EXPECTED))

    def test_no_duplicate_gulf_orchid_product_names(self):
        names = [row.get("canonical_name", "").casefold() for row in self.products]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
