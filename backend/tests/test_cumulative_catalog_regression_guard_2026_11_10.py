"""Regression guard for the cumulative, evidence-checked catalog snapshot."""

import json
import re
import unicodedata
import unittest
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


EXPECTED_VARIANTS = {
    ("Gulf Orchid", "Maze"): (100, "Eau de Parfum", "https://shop-gulforchid.com/products/maze"),
    ("Gulf Orchid", "Mosaic"): (100, "Eau de Parfum", "https://shop-gulforchid.com/products/mosaic"),
    ("Gulf Orchid", "Rice Milk"): (100, "Eau de Parfum", "https://shop-gulforchid.com/products/rice-milk"),
    ("Gulf Orchid", "Royal Rose"): (100, "Eau de Parfum", "https://shop-gulforchid.com/products/royal-rose"),
    ("Zimaya", "Afrah"): (20, "Concentrated Oil", "https://fr.zimayaperfumes.com/products/afrah"),
    ("Zimaya", "Al Embratur Elixir"): (100, "Eau de Parfum", "https://fr.zimayaperfumes.com/products/al-embratur-elixir"),
    ("Zimaya", "Ghali Imperial"): (100, "Eau de Parfum", "https://fr.zimayaperfumes.com/products/ghali-imperial"),
    ("Khadlaj", "Cream Velvet"): (100, "Extrait de Parfum", "https://khadlaj-perfumes.com/products/cream-velvet-100-ml-extrait-de-parfum-for-women-best-perfumes"),
}


class CumulativeCatalogRegressionGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.products_by_id = {row["product_id"]: row for row in cls.products}

    def test_cumulative_product_and_variant_coverage_does_not_regress(self):
        # Baseline from the exact 2026-11-10 cumulative head. These are
        # minimums, not claims that the worldwide fragrance universe is complete.
        self.assertGreaterEqual(len(self.products), 2207)
        self.assertGreaterEqual(len(self.variants), 1107)

    def test_product_variant_and_normalized_identity_keys_are_unique(self):
        product_ids = [row["product_id"] for row in self.products]
        variant_ids = [row["variant_id"] for row in self.variants]
        identities = [
            (normalize(row.get("brand_name") or row.get("brand")),
             normalize(row.get("canonical_name") or row.get("name")))
            for row in self.products
        ]
        variant_tuples = [
            (row["product_id"], row.get("size_ml"), row.get("concentration"))
            for row in self.variants
        ]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(len(variant_tuples), len(set(variant_tuples)))

    def test_variants_have_valid_parent_and_declared_size(self):
        for variant in self.variants:
            with self.subTest(variant=variant.get("variant_id")):
                product = self.products_by_id.get(variant.get("product_id"))
                self.assertIsNotNone(product)
                formats = product.get("formats_ml")
                if formats is not None:
                    self.assertIn(variant.get("size_ml"), formats)

    def test_family_registry_ids_are_unique(self):
        family_ids = [row["family_id"] for row in REGISTRY["families"]]
        self.assertEqual(len(family_ids), len(set(family_ids)))

    def test_recent_official_variant_batches_are_preserved(self):
        for (brand, name), (size, concentration, source_url) in EXPECTED_VARIANTS.items():
            with self.subTest(brand=brand, product=name):
                products = [
                    row for row in self.products
                    if (row.get("brand_name") or row.get("brand")) == brand
                    and (row.get("canonical_name") or row.get("name")) == name
                ]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source_url)
                self.assertIn(size, product.get("formats_ml", []))
                matches = [
                    row for row in self.variants
                    if row.get("product_id") == product["product_id"]
                    and row.get("size_ml") == size
                    and row.get("concentration") == concentration
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(
                    matches[0].get("source_evidence_url") or matches[0].get("source_url"),
                    source_url,
                )

    def test_vanilla_aura_and_vanilla_voyage_keep_maison_asrar_attribution(self):
        # The Gulf Orchid storefront is a retailer for these Maison Asrar items;
        # a retailer host must not silently change the perfume's brand.
        for name in ("Vanilla Aura", "Vanilla Voyage"):
            with self.subTest(product=name):
                rows = [
                    row for row in self.products
                    if (row.get("canonical_name") or row.get("name")) == name
                ]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("brand_name"), "Maison Asrar")

    def test_khadlaj_musk_pure_is_not_duplicated_as_a_second_canonical_identity(self):
        rows = [
            row for row in self.products
            if row.get("brand_name") == "Khadlaj"
            and normalize(row.get("canonical_name") or row.get("name")) in {
                "musk pure musk blend",
                "musk pure musk blend creation of iqbal",
            }
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            normalize(rows[0].get("canonical_name") or rows[0].get("name")),
            "musk pure musk blend",
        )


if __name__ == "__main__":
    unittest.main()
