"""Armaf EU detail-page evidence for existing and newly cataloged Odyssey identities."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Odyssey French Kiss": ([60], "https://cz.armaf.eu/products/odyssey-french-kiss"),
    "Odyssey Candee Special Edition": ([60, 100, 200], "https://cz.armaf.eu/products/odyssey-candee-special-edition"),
    "Dubai Nights Midnight": ([100], "https://cz.armaf.eu/products/dubai-nights-midnight"),
    "Odyssey Eau de Montagne": ([100], "https://cz.armaf.eu/products/odyssey-eau-de-montagne-mountain-edition"),
    "Odyssey Ba Ha Mas": ([100], "https://cz.armaf.eu/products/odyssey-ba-ha-mas"),
    "Odyssey Spectra Rainbow Edition": ([100], "https://cz.armaf.eu/products/odyssey-spectra-rainbow-edition"),
    "Odyssey Dubai Chocolat": ([60, 100], "https://cz.armaf.eu/products/odyssey-dubai-chocolat"),
}


class ArmafEuAdditionalCatalogProductsVariantsTests(unittest.TestCase):
    def test_all_detail_pages_are_mapped_to_canonical_products_and_variants(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "armaf_catalog")
        for name, (sizes, url) in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in CATALOG["products"] if p.get("brand") == "Armaf" and p.get("canonical_name") == name)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), sizes)
                self.assertEqual(product.get("source_size_evidence_url"), url)
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
                self.assertTrue(set(sizes).issubset({v.get("size_ml") for v in variants}))
                self.assertTrue(all(any(v.get("size_ml") == size and v.get("source_size_evidence_url") == url for v in variants) for size in sizes))
                row = next(p for p in family["products"] if p.get("canonical_name") == name)
                self.assertEqual(row.get("formats_ml"), sizes)
                self.assertEqual(row.get("concentration"), "Eau de Parfum")

    def test_two_new_canonical_products_have_unique_ids_and_family_rows(self):
        new_names = {"Odyssey Spectra Rainbow Edition", "Odyssey Dubai Chocolat"}
        products = [p for p in CATALOG["products"] if p.get("brand") == "Armaf" and p.get("canonical_name") in new_names]
        self.assertEqual(len(products), 2)
        ids = [p["product_id"] for p in products]
        self.assertEqual(len(ids), len(set(ids)))
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "armaf_catalog")
        for p in products:
            self.assertEqual(sum(1 for row in family["products"] if row.get("canonical_name") == p["canonical_name"]), 1)


if __name__ == "__main__":
    unittest.main()
