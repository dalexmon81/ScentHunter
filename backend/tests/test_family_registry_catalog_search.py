from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Brand, Fragrance
from app.search.catalog import search_catalog
from scripts.seed_catalog import merge_family_registry_identities


class FamilyRegistryCatalogSearchTests(unittest.TestCase):
    def test_family_registry_adds_identity_only_products_without_fabricated_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "product_catalog.json"
            registry_path = root / "family_registry.json"
            catalog_path.write_text("{}", encoding="utf-8")
            registry_path.write_text(json.dumps({
                "families": [{
                    "family_id": "rasasi_hawas",
                    "brand": "Rasasi",
                    "products": [
                        {"canonical_name": "Hawas Black"},
                        {"canonical_name": "Hawas Fire"},
                    ],
                }]
            }), encoding="utf-8")
            raw = {"products": [], "variants": []}
            merged = merge_family_registry_identities(raw, catalog_path)
            self.assertEqual(merged["_family_registry_identities_added"], 2)
            self.assertEqual(len(merged["products"]), 2)
            self.assertEqual(merged["products"][0]["family_name"], "rasasi_hawas")
            self.assertFalse(merged["variants"])

    def test_broad_search_returns_family_identity_without_inventing_offer(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as session, session.begin():
                brand = Brand(
                    name="Rasasi", slug="rasasi", normalized_name="rasasi"
                )
                session.add(brand)
                session.flush()
                session.add(Fragrance(
                    brand_id=brand.id,
                    name="Hawas Fire",
                    slug="hawas-fire",
                    family="rasasi_hawas",
                ))
            with Session(engine) as session:
                result = search_catalog(session, "Hawas")
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["results"][0]["name"], "Hawas Fire")
            self.assertTrue(result["results"][0]["identity_only"])
            self.assertEqual(result["results"][0]["offers"], [])
            self.assertEqual(result["offer_count"], 0)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
