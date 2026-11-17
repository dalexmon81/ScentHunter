"""Cross-file recovery checks for the canonical fragrance seed.

These checks run only against the isolated recovery candidate. They validate
catalog structure and referential integrity; they do not validate live offers,
retailer coverage, or source truth beyond recorded provenance.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "product_catalog.json"
FAMILIES = ROOT / "family_registry.json"
GTIN_MAP = ROOT / "scenthunter_next_engine" / "verified_gtin_variant_map.json"


def read_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def normalized(value):
    return " ".join(str(value or "").casefold().split())


def valid_gtin13(value):
    if not re.fullmatch(r"\d{13}", str(value or "")):
        return False
    digits = [int(char) for char in value]
    weighted = sum(digits[0:12:2]) + 3 * sum(digits[1:12:2])
    return (10 - weighted % 10) % 10 == digits[12]


class RecoveryCatalogIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = read_json(CATALOG)
        cls.families = read_json(FAMILIES)
        cls.gtin_map = read_json(GTIN_MAP)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]
        cls.products_by_id = {p["product_id"]: p for p in cls.products}
        cls.variants_by_id = {v["variant_id"]: v for v in cls.variants}

    def test_product_ids_and_normalized_identities_are_unique(self):
        ids = [p["product_id"] for p in self.products]
        identities = [
            (normalized(p["brand"]), normalized(p["canonical_name"]))
            for p in self.products
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(identities), len(set(identities)))

    def test_products_have_source_provenance_and_required_identity(self):
        for product in self.products:
            with self.subTest(product_id=product.get("product_id")):
                self.assertTrue(normalized(product.get("brand")))
                self.assertTrue(normalized(product.get("canonical_name")))
                self.assertTrue(normalized(product.get("source_url")))
                self.assertIn(
                    product.get("identity_status"),
                    {"source_verified_name", "source_listed_name"},
                )

    def test_variant_ids_and_product_size_pairs_are_unique(self):
        ids = [v["variant_id"] for v in self.variants]
        pairs = [(v["product_id"], v["size_ml"]) for v in self.variants]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_variants_reference_existing_products_and_valid_sizes(self):
        for variant in self.variants:
            with self.subTest(variant_id=variant.get("variant_id")):
                self.assertIn(variant["product_id"], self.products_by_id)
                self.assertIsInstance(variant["size_ml"], int)
                self.assertNotIsInstance(variant["size_ml"], bool)
                self.assertGreater(variant["size_ml"], 0)

    def test_family_ids_and_names_are_unique_within_each_family(self):
        family_ids = [family["family_id"] for family in self.families["families"]]
        self.assertEqual(len(family_ids), len(set(family_ids)))
        for family in self.families["families"]:
            with self.subTest(family_id=family["family_id"]):
                names = [normalized(product["canonical_name"]) for product in family.get("products", [])]
                self.assertEqual(len(names), len(set(names)))

    def test_every_catalog_family_id_exists_in_registry(self):
        family_ids = {family["family_id"] for family in self.families["families"]}
        missing = sorted({
            product.get("family_id")
            for product in self.products
            if product.get("family_id") not in family_ids
        })
        self.assertEqual(missing, [])

    def test_family_registry_covers_every_canonical_product(self):
        family_keys = {
            (normalized(family.get("brand")), normalized(product.get("canonical_name")))
            for family in self.families["families"]
            for product in family.get("products", [])
        }
        missing = [
            (product["brand"], product["canonical_name"])
            for product in self.products
            if (normalized(product["brand"]), normalized(product["canonical_name"]))
            not in family_keys
        ]
        self.assertEqual(missing, [])

    def test_gtin_records_are_unique_verified_and_resolve_exact_variants(self):
        records = self.gtin_map["records"]
        gtins = [record["gtin"] for record in records]
        self.assertEqual(len(gtins), len(set(gtins)))
        for record in records:
            with self.subTest(gtin=record.get("gtin")):
                self.assertEqual(record.get("status"), "verified")
                self.assertTrue(record.get("source_urls"))
                if record.get("gtin_type") == "GTIN-13":
                    self.assertTrue(valid_gtin13(record["gtin"]))
                product = self.products_by_id.get(record.get("product_id"))
                variant = self.variants_by_id.get(record.get("variant_id"))
                self.assertIsNotNone(product)
                self.assertIsNotNone(variant)
                self.assertEqual(variant["product_id"], record["product_id"])
                self.assertEqual(variant["size_ml"], record["size_ml"])


if __name__ == "__main__":
    unittest.main()
