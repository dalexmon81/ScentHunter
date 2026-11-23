import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from app.db import database_url, make_engine
from app.db_runtime_identity import configuration_source, log_runtime_database_identity


class PostgreSQLOnlyDatabaseTests(unittest.TestCase):
    def test_database_url_requires_explicit_postgresql_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "PostgreSQL catalog is mandatory"):
                database_url()

    def test_environment_precedence_is_preserved(self):
        env = {
            "SCENTHUNTER_CATALOG_DATABASE_URL": "postgresql://first:secret@db.example/catalog",
            "SCENTHUNTER_DATABASE_URL": "postgresql://second:secret@db.example/catalog",
        }
        self.assertEqual(
            database_url(env),
            "postgresql+psycopg://first:secret@db.example/catalog",
        )

    def test_postgres_urls_normalize_to_psycopg3(self):
        for scheme in ("postgresql", "postgres"):
            with self.subTest(scheme=scheme):
                self.assertEqual(
                    database_url({"SCENTHUNTER_DATABASE_URL": f"{scheme}://user:secret@db.example/catalog"}),
                    "postgresql+psycopg://user:secret@db.example/catalog",
                )

    def test_non_postgresql_urls_are_rejected_without_echoing_credentials(self):
        for value in ("not-a-url", "mysql://user:secret@db.example/catalog", "sqlite:///legacy.db"):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError) as caught:
                    database_url({"SCENTHUNTER_DATABASE_URL": value})
                self.assertNotIn("secret", str(caught.exception))

    def test_postgres_driver_is_not_silently_replaced(self):
        with self.assertRaisesRegex(RuntimeError, "psycopg 3"):
            database_url({"SCENTHUNTER_DATABASE_URL": "postgresql+psycopg2://user:secret@db.example/catalog"})

    def test_postgres_url_requires_database_name(self):
        with self.assertRaisesRegex(RuntimeError, "database name"):
            database_url({"SCENTHUNTER_DATABASE_URL": "postgresql://db.example"})

    def test_postgres_engine_uses_psycopg_without_opening_connection(self):
        with patch.dict(os.environ, {
            "SCENTHUNTER_CATALOG_DATABASE_URL": "postgresql://phase2:secret@db.example/catalog",
        }, clear=True):
            engine = make_engine()
        try:
            self.assertEqual(engine.dialect.name, "postgresql")
            self.assertEqual(engine.dialect.driver, "psycopg")
            self.assertEqual(engine.pool.size(), 5)
            self.assertEqual(engine.pool._max_overflow, 2)
        finally:
            engine.dispose()

    def test_postgres_runtime_identity_uses_supplied_connection(self):
        class Dialect:
            name = "postgresql"

        class Result:
            def one(self):
                return ("phase2_test_db", "public")

        class FakeConnection:
            dialect = Dialect()

            def __init__(self):
                self.statements = []

            def exec_driver_sql(self, statement):
                self.statements.append(statement)
                return Result()

        connection = FakeConnection()
        output = StringIO()
        with redirect_stdout(output):
            log_runtime_database_identity(
                connection, event_name="test", service_name="phase2-test",
                config_source="test", opened_at="2026-11-03T12:00:00+00:00",
            )
        self.assertEqual(connection.statements, ["SELECT current_database(), current_schema()"])
        self.assertIn("database_name=phase2_test_db", output.getvalue())
        self.assertNotIn("secret", output.getvalue())

    def test_configuration_source_never_returns_url(self):
        self.assertEqual(configuration_source({
            "SCENTHUNTER_CATALOG_DATABASE_URL": "postgresql://user:secret@host/db",
        }), "SCENTHUNTER_CATALOG_DATABASE_URL")
        self.assertEqual(configuration_source({}), "application_default")


if __name__ == "__main__":
    unittest.main()
