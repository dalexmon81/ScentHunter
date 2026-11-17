"""Exercise the real Alembic SQLite upgrade path with linked catalog rows.

This intentionally tests migrations, not Base.metadata.create_all(): model-only
tests cannot detect a broken revision graph or table-rebuild foreign keys.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid


BACKEND = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND / "alembic.ini"
PRE_PRECISION_REVISION = "0007_ingestion_dead_letters"
EXPECTED_HEAD = "0015_user_sessions"


class SQLiteAlembicUpgradeTests(unittest.TestCase):
    def _run_alembic(self, database_url: str, *args: str) -> None:
        env = os.environ.copy()
        env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
        env.pop("SCENTHUNTER_DATABASE_URL", None)
        env.pop("SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL", None)
        env["PYTHONPATH"] = str(BACKEND)
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=(
                f"Alembic {' '.join(args)} failed.\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            ),
        )

    def test_upgrade_from_pre_precision_schema_preserves_linked_rows(self):
        with tempfile.TemporaryDirectory(prefix="scenthunter-alembic-") as tmp:
            db_path = Path(tmp) / "migration.sqlite3"
            database_url = f"sqlite:///{db_path}"
            self._run_alembic(database_url, "upgrade", PRE_PRECISION_REVISION)

            brand_id, fragrance_id, variant_id, store_id, raw_id, offer_id = [
                str(uuid.uuid4()) for _ in range(6)
            ]
            legacy_product_id = "legacy-product-" + uuid.uuid4().hex
            legacy_variant_id = "legacy-variant-" + uuid.uuid4().hex

            with sqlite3.connect(db_path) as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute(
                    "INSERT INTO brands (id,name,slug,normalized_name) VALUES (?,?,?,?)",
                    (brand_id, "Migration Test", "migration-test-" + brand_id[:8], "migration-test-" + brand_id[:8]),
                )
                connection.execute(
                    "INSERT INTO fragrances (id,brand_id,name,slug) VALUES (?,?,?,?)",
                    (fragrance_id, brand_id, "Migration Fragrance", "migration-fragrance-" + fragrance_id[:8]),
                )
                connection.execute(
                    "INSERT INTO product_variants (id,fragrance_id,size_ml,canonical_key) VALUES (?,?,?,?)",
                    (variant_id, fragrance_id, 100, "migration-test|edp|100"),
                )
                connection.execute(
                    "INSERT INTO stores (id,name,slug) VALUES (?,?,?)",
                    (store_id, "Migration Store", "migration-store-" + store_id[:8]),
                )
                connection.execute(
                    "INSERT INTO legacy_product_id_map (legacy_product_id,fragrance_id) VALUES (?,?)",
                    (legacy_product_id, fragrance_id),
                )
                connection.execute(
                    "INSERT INTO legacy_variant_id_map (legacy_variant_id,product_variant_id) VALUES (?,?)",
                    (legacy_variant_id, variant_id),
                )
                connection.execute(
                    """INSERT INTO ingestion_raw
                       (id,store_id,raw_payload,external_product_id,status,product_variant_id)
                       VALUES (?,?,?,?,'matched',?)""",
                    (raw_id, store_id, '{"fixture":true}', "external-" + raw_id, variant_id),
                )
                connection.execute(
                    """INSERT INTO offers
                       (id,store_id,product_variant_id,external_product_id,ingestion_raw_id,
                        url,price,currency,availability,source,status)
                       VALUES (?,?,?,?,?,?,?,'EUR','in_stock','migration-test','active')""",
                    (offer_id, store_id, variant_id, "external-" + raw_id, raw_id,
                     "https://example.invalid/" + offer_id, 42.50),
                )

            self._run_alembic(database_url, "upgrade", "head")

            with sqlite3.connect(db_path) as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                revision = connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()[0]
                self.assertEqual(revision, EXPECTED_HEAD)
                self.assertEqual(
                    connection.execute(
                        "SELECT size_ml FROM product_variants WHERE id=?", (variant_id,)
                    ).fetchone()[0],
                    100,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT product_variant_id FROM offers WHERE id=?", (offer_id,)
                    ).fetchone()[0],
                    variant_id,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT product_variant_id FROM legacy_variant_id_map WHERE legacy_variant_id=?",
                        (legacy_variant_id,),
                    ).fetchone()[0],
                    variant_id,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT product_variant_id FROM ingestion_raw WHERE id=?", (raw_id,)
                    ).fetchone()[0],
                    variant_id,
                )
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                connection.execute(
                    "UPDATE product_variants SET size_ml=? WHERE id=?",
                    (50.5, variant_id),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT size_ml FROM product_variants WHERE id=?", (variant_id,)
                    ).fetchone()[0],
                    50.5,
                )


if __name__ == "__main__":
    unittest.main()
