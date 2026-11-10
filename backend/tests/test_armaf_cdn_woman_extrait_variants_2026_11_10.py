"""Official Armaf size evidence for Club de Nuit Woman Extrait de Parfum.

The official detail-page description explicitly lists 30, 105, 200 and 250 ml.
Its page title mentions 70 ml, but the detailed size list does not; 70 ml is
therefore intentionally excluded. The page identifies Extrait de Parfum and
Women. No GTIN is exposed in the reviewed evidence.
"""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

PRODUCT_ID = "SH-ARMAF-CLUB-DE-NUIT-WOMAN-EXTRAIT"
SOURCE = "https://armaf.com/products/cdn-club-de-nuit-extrait-de-parfum-spr"
EXPECTED_SIZES = [30, 105, 200, 250]


class ArmafCdnWomanExtraitVariantsTests(unittest.TestCase):
    def test_existing_canonical_identity_uses_only_explicit_sizes(self):
        rows = [p for p in CATALOG["products"] if p.get("product_id") == PRODUCT_ID]
        self.assertEqual(len(rows), 1)
        product = rows[0]
        self.assertEqual(product.get("canonical_name"), "Club de Nuit Woman Extrait de Parfum")
        self.assertEqual(product.get("identity_status"), "source_verified_name")
        self.assertEqual(product.get("concentration"), "Extrait de Parfum")
        self.assertEqual(product.get("gender"), "Women")
        self.assertEqual(product.get("formats_ml"), EXPECTED_SIZES)
        self.assertEqual(product.get("source_product_url"), SOURCE)

    def test_exactly_four_variants_are_present_and_no_70ml_variant_is_added(self):
        rows = [v for v in CATALOG["variants"] if v.get("product_id") == PRODUCT_ID]
        self.assertEqual(sorted(v.get("size_ml") for v in rows), EXPECTED_SIZES)
        self.assertEqual(len({v.get("variant_id") for v in rows}), 4)
        for variant in rows:
            self.assertEqual(variant.get("variant_id"), f"SHV-{PRODUCT_ID}-{variant['size_ml']}-000")
            self.assertEqual(variant.get("concentration"), "Extrait de Parfum")
            self.assertEqual(variant.get("gender"), "Women")
            self.assertEqual(variant.get("source_url"), SOURCE)
            self.assertEqual(variant.get("source_evidence_url"), SOURCE)
            self.assertNotIn("gtin", variant)

    def test_armaf_family_registry_is_synchronized(self):
        families = [f for f in REGISTRY["families"] if f.get("family_id") == "armaf_catalog"]
        self.assertEqual(len(families), 1)
        rows = [p for p in families[0].get("products", []) if p.get("canonical_name") == "Club de Nuit Woman Extrait de Parfum"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("formats_ml"), EXPECTED_SIZES)


if __name__ == "__main__":
    unittest.main()
