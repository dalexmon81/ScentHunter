"""Official Velixir storefront detail pages, concentrations and explicit size options."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Panacea": ("SH-VELIXIR-1738e7af", "https://velixirparfums.store/products/panacea", "Extrait de Parfum", [35,100]),
    "Comus": ("SH-VELIXIR-50b87cfb", "https://velixirparfums.store/products/comus", "Extrait de Parfum", [35,100]),
    "Ether": ("SH-VELIXIR-36e7a5ca", "https://velixirparfums.store/products/ether", "Extrait de Parfum", [35,100]),
    "Orpheus": ("SH-VELIXIR-7e147c46", "https://velixirparfums.store/products/orpheus", "Extrait de Parfum", [35,100]),
    "Comus": ("SH-VELIXIR-50b87cfb", "https://velixirparfums.com/collections/frontpage/products/velixir-parfums-comus-extrait-de-parfum-for-unisex", "Extrait de Parfum", []),
    "Harmonia": ("SH-VELIXIR-e49794d3", "https://velixirparfums.com/collections/frontpage/products/velixir-parfums-harmonia", "Eau de Parfum", [35,100]),
    "Nyx": ("SH-VELIXIR-153bbbed", "https://velixirparfums.com/collections/frontpage/products/velixir-parfums-nyx-eau-de-parfum-for-unisex", "Eau de Parfum", [35,100]),
    "Morpheus": ("SH-VELIXIR-21cface3", "https://velixirparfums.com/collections/frontpage/products/velixir-morpheus-for-unisex-eau-de-parfum", "Eau de Parfum", [35,100]),
    "Aphrodite": ("SH-VELIXIR-8b429b66", "https://velixirparfums.com/collections/frontpage/products/velixir-aphrodite-eau-de-parfum-for-unisex", "Eau de Parfum", [35,100]),
    "Artemis": ("SH-VELIXIR-058bec99", "https://velixirparfums.com/collections/frontpage/products/velixir-artemis-for-unisex-eau-de-parfum", "Eau de Parfum", [35,100]),
    "Asteria": ("SH-VELIXIR-9b764bf3", "https://velixirparfums.com/collections/frontpage/products/velixir-asteria-for-unisex-eau-de-parfum", "Eau de Parfum", [35,100]),
    "Concordia": ("SH-VELIXIR-6f7b377c", "https://velixirparfums.com/collections/frontpage/products/velixir-concordia-for-unisex-eau-de-parfum", "Eau de Parfum", [35,100]),
    "Himeros": ("SH-VELIXIR-71f3ac99", "https://velixirparfums.com/collections/frontpage/products/velixir-himeros-for-unisex-eau-de-parfum", "Eau de Parfum", [35,100]),
    "Demeter": ("SH-VELIXIR-c0952852", "https://velixirparfums.com/collections/frontpage/products/demeter-for-unisex-edp-100ml", "Eau de Parfum", [35,100]),
    "Galatea": ("SH-VELIXIR-76046795", "https://velixirparfums.com/collections/frontpage/products/velixir-galatea-eau-de-parfum-for-unisex", "Eau de Parfum", [35,100]),
    "Hera": ("SH-VELIXIR-06211958", "https://velixirparfums.com/collections/frontpage/products/hera", "Eau de Parfum", [35,100]),
    "Icarus": ("SH-VELIXIR-3a619af9", "https://velixirparfums.com/collections/frontpage/products/icarus", "Eau de Parfum", [35,100]),
    "Persephone": ("SH-VELIXIR-12baca03", "https://velixirparfums.com/collections/frontpage/products/velixir-persephone-for-unisex-eau-de-parfum", "Eau de Parfum", [35,100]),
    "Poseidon": ("SH-VELIXIR-c43f9b63", "https://velixirparfums.com/collections/frontpage/products/velixir-poseidon-for-unisex-eau-de-parfum", "Eau de Parfum", [35,100]),
    "Uranus": ("SH-VELIXIR-029d80ce", "https://velixirparfums.com/collections/frontpage/products/velixir-uranus-for-unisex-eau-de-parfum", "Eau de Parfum", [35,100]),
    "Selene": ("SH-VELIXIR-bc687534", "https://velixirparfums.com/collections/frontpage/products/velixir-parfums-selene-eau-de-parfum-for-unisex", "Eau de Parfum", [35,100]),
    "Orpheus": ("SH-VELIXIR-7e147c46", "https://velixirparfums.com/collections/frontpage/products/velixir-parfums-orpheus-extrait-de-parfum-for-unisex", "Extrait de Parfum", []),
    "Ether": ("SH-VELIXIR-36e7a5ca", "https://velixirparfums.com/collections/frontpage/products/velixir-parfums-ether-extrait-de-parfum-for-unisex", "Extrait de Parfum", []),
}


class VelixirOfficialStorefrontTests(unittest.TestCase):
    def test_all_twenty_current_storefront_products_have_detail_page_provenance(self):
        for name, (product_id, url, concentration, sizes) in EXPECTED.items():
            with self.subTest(name=name):
                matches = [
                    p for p in CATALOG["products"]
                    if p.get("brand") == "Velixir" and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product["product_id"], product_id)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["concentration"], concentration)
                if sizes:
                    self.assertEqual(product["formats_ml"], sizes)
                else:
                    self.assertNotIn("formats_ml", product)

    def test_explicit_size_variants_match_official_options_and_registry(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "velixir_catalog")
        for name, (product_id, url, concentration, sizes) in EXPECTED.items():
            with self.subTest(name=name):
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product_id]
                self.assertEqual({v["size_ml"] for v in variants}, set(sizes))
                for variant in variants:
                    self.assertEqual(variant["concentration"], concentration)
                    self.assertEqual(variant["source_evidence_url"], url)
                entry = next(p for p in family["products"] if p["canonical_name"] == name)
                if sizes:
                    self.assertEqual(entry["formats_ml"], sizes)
                else:
                    self.assertNotIn("formats_ml", entry)


    def test_sacred_four_bundle_is_not_a_fifth_canonical_fragrance(self):
        self.assertFalse(any(
            p.get("brand") == "Velixir" and p.get("canonical_name") == "Sacred Four Bundle"
            for p in CATALOG["products"]
        ))


if __name__ == "__main__":
    unittest.main()
