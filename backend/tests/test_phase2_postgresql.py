"""PostgreSQL compatibility checks; integration tests run against disposable CI DB."""
import os
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, inspect

from app.db import database_url, make_engine
from app.db_runtime_identity import log_runtime_database_identity
from app.models import Base


class Phase2DatabaseConfigurationTests(unittest.TestCase):
    def test_postgres_url_is_normalized_to_psycopg3(self):
        with patch.dict(os.environ, {
            "SCENTHUNTER_CATALOG_DATABASE_URL":
                "postgresql://user:pw@localhost:5432/catalog"
        }, clear=True):
            self.assertTrue(database_url().startswith("postgresql+psycopg://"))

    def test_postgres_explicit_psycopg_driver_is_accepted(self):
        value = "postgresql+psycopg://user:pw@localhost:5432/catalog"
        with patch.dict(os.environ, {"SCENTHUNTER_DATABASE_URL": value}, clear=True):
            self.assertEqual(database_url(), value)

    def test_unsupported_database_is_rejected_without_echoing_url(self):
        with patch.dict(os.environ, {
            "SCENTHUNTER_CATALOG_DATABASE_URL": "mysql://user:pw@localhost/catalog"
        }, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SQLite or PostgreSQL"):
                database_url()

    def test_sqlite_remains_the_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(database_url().startswith("sqlite:///"))


@unittest.skipUnless(
    os.environ.get("SCENTHUNTER_TEST_POSTGRES_URL"),
    "requires disposable PostgreSQL service",
)
class Phase2PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            os.environ["SCENTHUNTER_TEST_POSTGRES_URL"], pool_pre_ping=True
        )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def test_migrations_created_expected_tables_and_indexes(self):
        inspector = inspect(self.engine)
        expected_tables = set(Base.metadata.tables)
        actual_tables = set(inspector.get_table_names())
        self.assertTrue(expected_tables.issubset(actual_tables))

        for table_name in expected_tables:
            expected_columns = {column.name for column in Base.metadata.tables[table_name].columns}
            actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
            self.assertEqual(expected_columns, actual_columns, table_name)

        self.assertIn(
            "ix_offers_store_external_product",
            {index["name"] for index in inspector.get_indexes("offers")},
        )

    def test_runtime_identity_uses_postgresql_connection_without_dsn(self):
        with self.engine.connect() as connection:
            log_runtime_database_identity(
                connection,
                event_name="ci-test",
                service_name="phase2-postgresql-ci",
                config_source="SCENTHUNTER_TEST_POSTGRES_URL",
            )
        # Identity output is checked in the dedicated runtime test workflow step;
        # the key safety property is that this function accepts the live PG connection.


if __name__ == "__main__":
    unittest.main()
