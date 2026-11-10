"""Official Armaf 70 ml evidence for Club de Nuit Intense Man Extrait de Parfum.

The official detail-page title identifies the 70 ml size. The page does not
expose a GTIN in the available evidence, so this variant intentionally has
no GTIN field.
"""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

PRODUCT_ID = "SH-ARMAF-909fec22"
VARIANT_ID = "SHV-SH-ARMAF-909fec22-70-000"
SOURCE = "https://armaf.com/products/cdn-intense-extrait-de-parfum-spr"


class ArmafCdnIntenseExtrait70mlTests(unittest.TestCase):
    def test_existing_canonical_identity_is_upgraded_in_place(self):
        rows = [p for p in CATALOG["products"] if p.get("product_id") == PRODUCT_ID]
        self.assertEqual(len(rows), 1)
        product = rows[0]
        self.assertEqual(product.get("canonical_name"), "Club de Nuit Intense Man Extrait de Parfum")
        self.assertEqual(product.get("identity_status"), "source_verified_name")
        self.assertEqual(product.get("concentration"), "Extrait de Parfum")
        self.assertEqual(product.get("gender"), "Men")
        self.assertEqual(product.get("formats_ml"), [70])
        self.assertEqual(product.get("source_product_url"), SOURCE)

    def test_one_70ml_variant_uses_official_page_and_does_not_invent_gtin(self):
        rows = [v for v in CATALOG["variants"] if v.get("variant_id") == VARIANT_ID]
        self.assertEqual(len(rows), 1)
        variant = rows[0]
        self.assertEqual(variant.get("product_id"), PRODUCT_ID)
        self.assertEqual(variant.get("size_ml"), 70)
        self.assertEqual(variant.get("concentration"), "Extrait de Parfum")
        self.assertEqual(variant.get("gender"), "Men")
        self.assertEqual(variant.get("source_url"), SOURCE)
        self.assertEqual(variant.get("source_evidence_url"), SOURCE)
        self.assertNotIn("gtin", variant)

    def test_armaf_family_registry_is_synchronized(self):
        families = [f for f in REGISTRY["families"] if f.get("family_id") == "armaf_catalog"]
        self.assertEqual(len(families), 1)
        rows = [p for p in families[0].get("products", []) if p.get("canonical_name") == "Club de Nuit Intense Man Extrait de Parfum"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("formats_ml"), [70])


if __name__ == "__main__":
    unittest.main()
