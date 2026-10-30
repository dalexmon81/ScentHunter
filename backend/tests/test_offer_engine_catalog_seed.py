from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.offer_engine import runtime


class CanonicalCatalogSeedTests(unittest.TestCase):
    def test_seed_stages_explicit_products_and_variants_without_publishing_offers(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "offer-engine.sqlite3"
            runtime.apply_migration(db_path=db_path)

            result = runtime.seed_canonical_catalog(db_path=db_path)

            self.assertEqual(result["status"], "staged")
            self.assertGreater(result["products_upserted"], 0)
            self.assertGreater(result["variants_upserted"], 0)
            self.assertEqual(result["offers_published"], 0)
            self.assertFalse(result["catalog_mutated"])
            self.assertEqual(result["automatic_identity_repairs"], 0)

            connection = runtime.connect_offer_engine_db(db_path=db_path)
            try:
                products = connection.execute("SELECT COUNT(*) FROM sh_products").fetchone()[0]
                variants = connection.execute("SELECT COUNT(*) FROM sh_variants").fetchone()[0]
                observations = connection.execute("SELECT COUNT(*) FROM sh_offer_observations").fetchone()[0]
                current_offers = connection.execute("SELECT COUNT(*) FROM sh_current_offers").fetchone()[0]
                self.assertEqual(products, result["products_upserted"])
                self.assertEqual(variants, result["variants_upserted"])
                self.assertEqual(observations, 0)
                self.assertEqual(current_offers, 0)
            finally:
                connection.close()

    def test_seed_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "offer-engine.sqlite3"
            runtime.apply_migration(db_path=db_path)

            first = runtime.seed_canonical_catalog(db_path=db_path)
            second = runtime.seed_canonical_catalog(db_path=db_path)

            self.assertEqual(first["products_upserted"], second["products_upserted"])
            self.assertEqual(first["variants_upserted"], second["variants_upserted"])
            connection = runtime.connect_offer_engine_db(db_path=db_path)
            try:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM sh_products").fetchone()[0],
                    first["products_upserted"],
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM sh_variants").fetchone()[0],
                    first["variants_upserted"],
                )
            finally:
                connection.close()

    def test_products_without_explicit_variants_are_staged_without_inventing_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "offer-engine.sqlite3"
            runtime.apply_migration(db_path=db_path)
            result = runtime.seed_canonical_catalog(db_path=db_path)
            self.assertGreater(result["products_without_variants"], 0)

            from backend.scenthunter_next_engine.catalog_repository import CatalogRepository
            catalog = CatalogRepository.from_file(runtime.CATALOG_PATH)
            no_variant_ids = {
                product.product_id for product in catalog.all_products()
                if not product.variants
            }
            connection = runtime.connect_offer_engine_db(db_path=db_path)
            try:
                self.assertTrue(no_variant_ids)
                for product_id in no_variant_ids:
                    count = connection.execute(
                        "SELECT COUNT(*) FROM sh_variants WHERE product_id = ?",
                        (product_id,),
                    ).fetchone()[0]
                    self.assertEqual(count, 0, product_id)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
