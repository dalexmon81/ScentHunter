"""Official Maison Alhambra source verification for Kismet and Jean Lowe Matiere."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED_PRODUCTS = {
    "Jean Lowe Matiere": {
        "product_id": "SH-MAISON-ALHAMBRA-7247b143",
        "source": "https://maisonalhambra-usa.com/products/maison-alhambra-jean-lowe-matiere-eau-de-parfum-for-everyone",
        "gtin": "6291108735558",
        "variant_id": "SHV-SH-MAISON-ALHAMBRA-7247b143-100-000",
    },
    "Kismet for Men": {
        "product_id": "SH-MAISON-ALHAMBRA-dd2c5772",
        "source": "https://maisonalhambra-usa.com/products/maison-alhambra-kismet-eau-de-parfum-for-men",
        "gtin": "6291107459257",
        "variant_id": "SHV-SH-MAISON-ALHAMBRA-dd2c5772-100-MEN",
    },
    "Kismet for Women": {
        "product_id": "SH-MAISON-ALHAMBRA-KISMET-WOMEN",
        "source": "https://maisonalhambra-usa.com/products/maison-alhambra-kismet-eau-de-parfum-for-women",
        "gtin": "6291107459264",
        "variant_id": "SHV-SH-MAISON-ALHAMBRA-KISMET-WOMEN-100-EDP",
    },
    "Kismet Lunar Magic": {
        "product_id": "SH-MAISON-ALHAMBRA-8686c885",
        "source": "https://maisonalhambra-usa.com/products/maison-alhambra-kismet-magic-eau-de-parfum-for-everyone",
        "gtin": "6291108736579",
        "variant_id": "SHV-SH-MAISON-ALHAMBRA-8686c885-100-EDP",
    },
}


class MaisonAlhambraKismetMatiereOfficialTests(unittest.TestCase):
    def test_existing_and_new_canonical_products_have_official_evidence(self):
        for name, expected in EXPECTED_PRODUCTS.items():
            with self.subTest(product=name):
                products = [
                    p for p in CATALOG["products"]
                    if p.get("brand_name", p.get("brand")) == "Maison Alhambra"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product.get("product_id"), expected["product_id"])
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("gender"), "Men" if "Men" in name else "Women" if "Women" in name else "Unisex")
                self.assertEqual(product.get("source_url"), expected["source"])

    def test_each_gender_specific_kismet_is_a_distinct_canonical_variant(self):
        expected = {
            "Kismet for Men": ("SH-MAISON-ALHAMBRA-dd2c5772", "6291107459257", "Men", "SHV-SH-MAISON-ALHAMBRA-dd2c5772-100-MEN"),
            "Kismet for Women": ("SH-MAISON-ALHAMBRA-KISMET-WOMEN", "6291107459264", "Women", "SHV-SH-MAISON-ALHAMBRA-KISMET-WOMEN-100-EDP"),
        }
        for name, (product_id, gtin, gender, variant_id) in expected.items():
            with self.subTest(product=name):
                product = next(p for p in CATALOG["products"] if p.get("product_id") == product_id)
                variant = next(v for v in CATALOG["variants"] if v.get("variant_id") == variant_id)
                self.assertEqual(product.get("canonical_name"), name)
                self.assertEqual(variant.get("product_id"), product_id)
                self.assertEqual(variant.get("size_ml"), 100)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("gtin"), gtin)
                self.assertEqual(variant.get("gender"), gender)

    def test_registry_mapping_and_global_catalog_integrity(self):
        products = CATALOG["products"]
        variants = CATALOG["variants"]
        families = {f["family_id"]: f for f in REGISTRY["families"]}
        pids = [p.get("product_id") for p in products]
        vids = [v.get("variant_id") for v in variants]
        gtins = [v.get("gtin") for v in variants if v.get("gtin")]
        known = set(pids)
        self.assertEqual(len(pids), len(set(pids)))
        self.assertEqual(len(vids), len(set(vids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertTrue(all(v.get("product_id") in known for v in variants))
        for name in EXPECTED_PRODUCTS:
            product = next(p for p in products if p.get("canonical_name") == name and p.get("brand_name") == "Maison Alhambra")
            family = families[product["family_id"]]
            entry = next(p for p in family["products"] if p.get("canonical_name") == name)
            self.assertEqual(entry.get("formats_ml"), [100])

    def test_no_offer_fields_are_added(self):
        forbidden = {"price", "currency", "availability", "stock", "shipping_cost", "retailer", "offer_url", "store_url"}
        target = {e["product_id"] for e in EXPECTED_PRODUCTS.values()}
        for variant in CATALOG["variants"]:
            if variant.get("product_id") in target:
                self.assertFalse(forbidden.intersection(variant))


if __name__ == "__main__":
    unittest.main()
