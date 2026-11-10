"""Official Maison Alhambra detail-page coverage for three existing catalog identities."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Glacier Pour Homme": {
        "product_id": "SH-MAISON-ALHAMBRA-7a451afc",
        "source": "https://maisonalhambra-usa.com/products/maison-alhambra-glacier-pour-homme-eau-de-parfum-for-men",
        "size": 100,
        "gtin": "6290360590615",
        "gender": "Men",
    },
    "Fusion Intense": {
        "product_id": "SH-MAISON-ALHAMBRA-7d94b36d",
        "source": "https://maisonalhambra-usa.com/products/maison-alhambra-fusion-intense-eau-de-parfum-for-everyone",
        "size": 80,
        "gtin": "6291108735800",
        "gender": "Unisex",
    },
    "Mysterious Amber": {
        "product_id": "SH-MAISON-ALHAMBRA-e51860be",
        "source": "https://maisonalhambra-usa.com/products/maison-alhambra-mysterious-amber-eau-de-parfum-for-everyone",
        "size": 80,
        "gtin": "6290360599182",
        "gender": "Unisex",
    },
}


class MaisonAlhambraOfficialThreeVariantsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.families = {f["family_id"]: f for f in REGISTRY["families"]}

    def test_existing_product_ids_are_verified_with_official_detail_evidence(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [
                    p for p in self.products
                    if p.get("brand_name", p.get("brand")) == "Maison Alhambra"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(rows), 1)
                product = rows[0]
                self.assertEqual(product.get("product_id"), expected["product_id"])
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), expected["source"])
                self.assertEqual(product.get("source_product_url"), expected["source"])
                self.assertEqual(product.get("source_evidence_url"), expected["source"])
                self.assertEqual(product.get("formats_ml"), [expected["size"]])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("gender"), expected["gender"])
                self.assertEqual(product.get("gtins"), [expected["gtin"]])

    def test_variants_and_family_registry_match_the_official_product_pages(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [
                    v for v in self.variants
                    if v.get("product_id") == expected["product_id"]
                ]
                self.assertEqual(len(rows), 1)
                variant = rows[0]
                self.assertEqual(variant.get("size_ml"), expected["size"])
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("gtin"), expected["gtin"])
                self.assertEqual(variant.get("gender"), expected["gender"])
                self.assertEqual(variant.get("source_url"), expected["source"])
                self.assertEqual(variant.get("source_evidence_url"), expected["source"])
                product = next(p for p in self.products if p.get("product_id") == expected["product_id"])
                family = self.families[product["family_id"]]
                family_rows = [r for r in family["products"] if r.get("canonical_name") == name]
                self.assertEqual(len(family_rows), 1)
                self.assertEqual(family_rows[0].get("formats_ml"), [expected["size"]])

    def test_global_identity_variant_gtin_and_parent_integrity(self):
        pids = [p.get("product_id") for p in self.products]
        vids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        known = set(pids)
        self.assertEqual(len(pids), len(set(pids)))
        self.assertEqual(len(vids), len(set(vids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertTrue(all(v.get("product_id") in known for v in self.variants))


if __name__ == "__main__":
    unittest.main()
