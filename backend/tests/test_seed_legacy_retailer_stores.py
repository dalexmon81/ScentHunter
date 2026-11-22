from __future__ import annotations

import unittest

from scripts.seed_legacy_retailer_stores import RETAILERS, provision


class FakeSession:
    def __init__(self, existing=None):
        self.existing = existing or {}
        self.added = []

    def scalar(self, statement):
        # Read the bound slug value from the SQLAlchemy expression.
        params = statement.compile().params
        slug = next(iter(params.values()))
        return self.existing.get(slug)

    def add(self, row):
        self.added.append(row)


class LegacyRetailerSeedTests(unittest.TestCase):
    def test_dry_run_does_not_write(self):
        session = FakeSession()
        report = provision(session, apply=False)
        self.assertEqual(report["status"], "validated")
        self.assertEqual(report["created"], [row["slug"] for row in RETAILERS])
        self.assertFalse(report["database_written"])
        self.assertEqual(session.added, [])

    def test_apply_creates_only_missing_rows(self):
        session = FakeSession()
        report = provision(session, apply=True)
        self.assertEqual(report["status"], "provisioned")
        self.assertEqual(len(session.added), 4)
        self.assertTrue(report["database_written"])
        self.assertTrue(all(row.status == "active" for row in session.added))

    def test_inactive_existing_store_is_not_reactivated(self):
        from app.models import Store
        existing = Store(
            name="Deloox.be", slug="deloox-be", domain="www.deloox.be",
            country="BE", currency="EUR", status="inactive",
        )
        session = FakeSession({"deloox-be": existing})
        with self.assertRaisesRegex(RuntimeError, "refusing to reactivate"):
            provision(session, apply=True)
        self.assertEqual(session.added, [])


if __name__ == "__main__":
    unittest.main()
