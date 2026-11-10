"""Four Armaf EU edition names reconciled to existing identities by matching note pyramids."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Odyssey Marshmallow": (100, "Odyssey Marshmallow Gourmand Edition", "https://cz.armaf.eu/en/products/odyssey-marshmallow-gourmand-edition"),
    "Odyssey Toffee Coffee": (100, "Odyssey Toffee Coffee Cafe Edition", "https://cz.armaf.eu/en/products/odyssey-toffee-coffee-cafe-edition"),
    "Odyssey Black Forest": (100, "Odyssey Black Forest Dessert Edition", "https://cz.armaf.eu/en/products/odyssey-black-forest-dessert-edition"),
    "Odyssey Go Mango": (100, "Odyssey Go Mango Tropical Collection", "https://cz.armaf.eu/en/products/odyssey-go-mango-tropical-collection-1"),
}


class ArmafFourEditionAliasVariantsTests(unittest.TestCase):
    def test_edition_aliases_match_existing_official_identities(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "armaf_catalog")
        products = [p for p in CATALOG["products"] if p.get("brand") == "Armaf"]
        for name, (size, alias, url) in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in products if p.get("canonical_name") == name)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertIn(alias, product.get("aliases", []))
                self.assertEqual(product.get("formats_ml"), [size])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("source_product_url"), product.get("source_url"))
                self.assertEqual(product.get("source_evidence_url"), product.get("source_url"))
                self.assertEqual(product.get("source_size_evidence_url"), url)
                variant = next(v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"])
                self.assertEqual(variant.get("size_ml"), size)
                self.assertIn(alias, variant.get("aliases", []))
                self.assertEqual(variant.get("source_size_evidence_url"), url)
                row = next(p for p in family["products"] if p.get("canonical_name") == name)
                self.assertIn(alias, row.get("aliases", []))
                self.assertEqual(row.get("formats_ml"), [size])


if __name__ == "__main__":
    unittest.main()
