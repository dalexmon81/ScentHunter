"""Maison Asrar official-page identity and variant coverage."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
EXPECTED = [
    {
        "name": "Milky Way",
        "id": "SH-MAISON-ASRAR-1061bdf1",
        "url": "https://maisonasrar.com/products/milky-way",
        "concentration": null,
        "variant_id": null
    },
    {
        "name": "Mohra",
        "id": "SH-MAISON-ASRAR-678d2fcd",
        "url": "https://maisonasrar.com/products/mohrab",
        "concentration": null,
        "variant_id": null
    },
    {
        "name": "Nada",
        "id": "SH-MAISON-ASRAR-e471ac92",
        "url": "https://maisonasrar.com/products/nada",
        "concentration": null,
        "variant_id": null
    },
    {
        "name": "Never Forget Me",
        "id": "SH-MAISON-ASRAR-bfb4583f",
        "size": 90,
        "url": "https://maisonasrar.com/products/never-forget-me-maison-asrar-eau-de-perfum-90ml",
        "concentration": "Eau de Parfum",
        "variant_id": "SHV-SH-MAISON-ASRAR-bfb4583f-90-EDP"
    },
    {
        "name": "Lily",
        "id": "SH-MAISON-ASRAR-a0c32340",
        "size": 100,
        "url": "https://maisonasrar.com/products/lily-eau-de-parfum-100ml",
        "concentration": "Eau de Parfum",
        "variant_id": "SHV-SH-MAISON-ASRAR-a0c32340-100-EDP"
    },
    {
        "name": "Lolita",
        "id": "SH-MAISON-ASRAR-7b2833f9",
        "size": 100,
        "url": "https://maisonasrar.com/products/lolita-eau-de-parfum-100ml",
        "concentration": "Eau de Parfum",
        "variant_id": "SHV-SH-MAISON-ASRAR-7b2833f9-100-EDP"
    },
    {
        "name": "Luna",
        "id": "SH-MAISON-ASRAR-abdcc53a",
        "size": 100,
        "url": "https://maisonasrar.com/products/luna-eau-de-parfum-100ml",
        "concentration": "Eau de Parfum",
        "variant_id": "SHV-SH-MAISON-ASRAR-abdcc53a-100-EDP"
    },
    {
        "name": "Magic Night",
        "id": "SH-MAISON-ASRAR-a810f08d",
        "size": 100,
        "url": "https://maisonasrar.com/products/magic-night-eau-de-perfum-100ml",
        "concentration": "Eau de Parfum",
        "variant_id": "SHV-SH-MAISON-ASRAR-a810f08d-100-EDP"
    }
]

class MaisonAsrarOfficialPagesBatchTests(unittest.TestCase):
    def test_official_product_identity_and_available_variant_evidence(self):
        products = {p["product_id"]: p for p in CATALOG["products"]}
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "maison_asrar_catalog")
        for item in EXPECTED:
            with self.subTest(name=item["name"]):
                product = products[item["id"]]
                self.assertEqual(product["brand"], "Maison Asrar")
                self.assertEqual(product["canonical_name"], item["name"])
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_product_url"], item["url"])
                self.assertEqual(product["source_evidence_url"], item["url"])
                family_product = next(p for p in family["products"] if p["canonical_name"] == item["name"])
                if item["size"]:
                    self.assertIn(item["size"], product["formats_ml"])
                    self.assertIn(item["size"], family_product["formats_ml"])
                    matches = [v for v in CATALOG["variants"] if v["product_id"] == item["id"] and v["size_ml"] == item["size"] and v.get("concentration") == item["concentration"]]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0]["variant_id"], item["variant_id"])
                    self.assertEqual(matches[0]["source_evidence_url"], item["url"])
                else:
                    self.assertFalse(any(v["product_id"] == item["id"] for v in CATALOG["variants"]))

    def test_catalog_integrity(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        known = set(product_ids)
        self.assertTrue(all(v["product_id"] in known for v in CATALOG["variants"]))
        tuples = [(v["product_id"], v["size_ml"], v.get("concentration")) for v in CATALOG["variants"]]
        self.assertEqual(len(tuples), len(set(tuples)))
        gtins = [v["gtin"] for v in CATALOG["variants"] if v.get("gtin")]
        self.assertEqual(len(gtins), len(set(gtins)))

if __name__ == "__main__":
    unittest.main()
