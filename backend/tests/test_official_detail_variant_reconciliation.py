"""Official detail-page reconciliation for Velixir and Khadlaj."""
import json
import unittest
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[1] / "product_catalog.json").read_text(encoding="utf-8"))

VELIXIR = {
    "Adonis": "https://velixirparfums.com/products/adonis",
    "Aphrodite": "https://velixirparfums.com/products/velixir-aphrodite-eau-de-parfum-for-unisex",
    "Apollo": "https://velixirparfums.com/products/apollo",
    "Ares": "https://velixirparfums.com/products/ares",
    "Artemis": "https://velixirparfums.com/products/velixir-artemis-for-unisex-eau-de-parfum",
    "Asteria": "https://velixirparfums.com/products/velixir-asteria-for-unisex-eau-de-parfum",
    "Athena": "https://velixirparfums.com/products/athena",
    "Comus": "https://velixirparfums.com/products/velixir-parfums-comus-extrait-de-parfum-for-unisex",
    "Concordia": "https://velixirparfums.com/products/velixir-concordia-for-unisex-eau-de-parfum",
    "Demeter": "https://velixirparfums.com/products/demeter-for-unisex-edp-100ml",
    "Ether": "https://velixirparfums.com/products/velixir-parfums-ether-extrait-de-parfum-for-unisex",
    "Galatea": "https://velixirparfums.com/products/velixir-galatea-eau-de-parfum-for-unisex",
    "Harmonia": "https://velixirparfums.com/products/velixir-parfums-harmonia",
    "Helios": "https://velixirparfums.com/products/helios",
    "Hera": "https://velixirparfums.com/products/hera",
    "Himeros": "https://velixirparfums.com/products/velixir-himeros-for-unisex-eau-de-parfum",
    "Icarus": "https://velixirparfums.com/products/icarus",
    "Morpheus": "https://velixirparfums.com/products/velixir-morpheus-for-unisex-eau-de-parfum",
    "Narcisus": "https://velixirparfums.com/products/narcisus",
    "Nyx": "https://velixirparfums.com/products/velixir-parfums-nyx-eau-de-parfum-for-unisex",
    "Orion": "https://velixirparfums.com/products/orion",
    "Orpheus": "https://velixirparfums.com/products/velixir-parfums-orpheus-extrait-de-parfum-for-unisex",
    "Paladin": "https://velixirparfums.com/products/paladin",
    "Panacea": "https://velixirparfums.com/products/velixir-parfums-panacea-extrait-de-parfum-for-unisex",
    "Persephone": "https://velixirparfums.com/products/velixir-persephone-for-unisex-eau-de-parfum",
    "Poseidon": "https://velixirparfums.com/products/velixir-poseidon-for-unisex-eau-de-parfum",
    "Selene": "https://velixirparfums.com/products/velixir-parfums-selene-eau-de-parfum-for-unisex",
    "Uranus": "https://velixirparfums.com/products/velixir-uranus-for-unisex-eau-de-parfum"
}
VELIXIR_WITH_VARIANTS = [
    "Adonis",
    "Aphrodite",
    "Apollo",
    "Ares",
    "Artemis",
    "Asteria",
    "Athena",
    "Concordia",
    "Demeter",
    "Galatea",
    "Harmonia",
    "Helios",
    "Hera",
    "Himeros",
    "Icarus",
    "Morpheus",
    "Narcisus",
    "Nyx",
    "Orion",
    "Paladin",
    "Persephone",
    "Poseidon",
    "Selene",
    "Uranus"
]
KHADLAJ = {
    "Muse": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-muse-100-ml-eau-de-parfum-spray-for-women",
        "size": 100,
        "concentration": "Eau de Parfum",
        "existing_variant": False
    },
    "Sueno": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/sueno-100ml-extrait-de-parfum-for-women",
        "size": 100,
        "concentration": "Extrait de Parfum",
        "existing_variant": False
    },
    "Saraya": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-saraya-60-ml-extrait-de-parfum-spray-for-men-women",
        "size": 60,
        "concentration": "Extrait de Parfum",
        "existing_variant": False
    },
    "Zayaan Silver": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/zayaan-silver-fresh-aquatic-spicy-woody-eau-de-parfum-for-men",
        "size": 100,
        "concentration": "Eau de Parfum",
        "existing_variant": False
    },
    "Qarar": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-qarar-unisex-bold-oriental-extrait-de-parfum",
        "size": 60,
        "concentration": "Extrait de Parfum",
        "existing_variant": False
    },
    "Ihthiraam": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/ihthraam-extrait-de-parfum-spray-oriental-unisex-fragrance",
        "size": 60,
        "concentration": "Extrait de Parfum",
        "existing_variant": False
    },
    "Icon": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-icon-100-ml-eau-de-parfum-spray-for-men",
        "size": 100,
        "concentration": "Eau de Parfum",
        "existing_variant": False
    },
    "Onyx Galaxy": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-onyx-galaxy-100-ml-eau-de-parfum-for-men",
        "size": 100,
        "concentration": "Eau de Parfum",
        "existing_variant": False
    },
    "Island Sun": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-island-sun-100-ml-extrait-de-parfum",
        "size": 100,
        "concentration": "Extrait de Parfum",
        "existing_variant": True
    },
    "Karus Gold Absolu": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/karus-gold-absolu-100-ml-edp-spray",
        "size": 100,
        "concentration": "Eau de Parfum",
        "existing_variant": True
    },
    "Shiyaaka Sky": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/special-edition-shiyaaka-sky-100-ml",
        "size": 100,
        "concentration": "Eau de Parfum",
        "existing_variant": True
    },
    "Panache Angel Dust": {
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/panache-angel-dust-100-ml-extrait-de-parfum-spray-for-women-shop-online-dubai-uae",
        "size": 100,
        "concentration": "Extrait de Parfum",
        "existing_variant": True
    }
}

class OfficialDetailVariantReconciliationTests(unittest.TestCase):
    def product(self, brand, name):
        rows = [p for p in CATALOG["products"] if (p.get("brand_name") or p.get("brand")) == brand and p.get("canonical_name") == name]
        self.assertEqual(len(rows), 1, f"{brand}/{name}")
        return rows[0]

    def variants_for(self, product):
        return [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]

    def test_all_velixir_names_have_individual_official_detail_sources(self):
        rows = [p for p in CATALOG["products"] if (p.get("brand_name") or p.get("brand")) == "Velixir"]
        self.assertEqual(len(rows), 28)
        for name, url in VELIXIR.items():
            with self.subTest(name=name):
                p = self.product("Velixir", name)
                self.assertEqual(p.get("identity_status"), "source_verified_name")
                self.assertEqual(p.get("source_url"), url)
                self.assertEqual(p.get("source_evidence_url"), url)

    def test_velixir_24_edp_products_have_two_officially_documented_sizes(self):
        for name in VELIXIR_WITH_VARIANTS:
            with self.subTest(name=name):
                p = self.product("Velixir", name)
                variants = self.variants_for(p)
                self.assertEqual({v.get("size_ml") for v in variants}, {35, 100})
                self.assertEqual(len(variants), 2)
                for v in variants:
                    self.assertEqual(v.get("concentration"), "Eau de Parfum")
                    self.assertEqual(v.get("source_evidence_url"), VELIXIR[name])

    def test_velixir_four_extrait_products_have_no_guessed_sizes(self):
        for name in set(VELIXIR) - set(VELIXIR_WITH_VARIANTS):
            with self.subTest(name=name):
                p = self.product("Velixir", name)
                self.assertEqual(p.get("concentration"), "Extrait de Parfum")
                self.assertEqual(self.variants_for(p), [])

    def test_twelve_khadlaj_individual_pages_and_variants_are_reconciled(self):
        for name, spec in KHADLAJ.items():
            with self.subTest(name=name):
                p = self.product("Khadlaj", name)
                self.assertEqual(p.get("identity_status"), "source_verified_name")
                self.assertEqual(p.get("source_url"), spec["url"])
                self.assertEqual(p.get("source_evidence_url"), spec["url"])
                variants = self.variants_for(p)
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("size_ml"), spec["size"])
                self.assertEqual(variants[0].get("concentration"), spec["concentration"])
                self.assertEqual(variants[0].get("source_evidence_url"), spec["url"])

    def test_global_product_and_variant_ids_are_unique(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))

    def test_no_commercial_offer_values_are_added(self):
        audited_ids = {p["product_id"] for p in CATALOG["products"] if (p.get("brand_name") or p.get("brand")) in {"Velixir", "Khadlaj"}}
        forbidden = {"price", "stock", "availability", "shipping_cost", "store_url"}
        for row in CATALOG["products"] + CATALOG["variants"]:
            if row.get("product_id") in audited_ids:
                self.assertTrue(forbidden.isdisjoint(row))

if __name__ == "__main__":
    unittest.main()
