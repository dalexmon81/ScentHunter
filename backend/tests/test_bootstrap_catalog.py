"""Regression tests for the restart-safe pilot catalog bootstrap."""
from __future__ import annotations

import unittest
from unittest.mock import call, patch

from scripts.bootstrap_catalog import BACKEND, bootstrap_commands, main


class PilotCatalogBootstrapTests(unittest.TestCase):
    def test_migrations_run_before_idempotent_canonical_seed(self):
        commands = bootstrap_commands("/python")
        self.assertEqual(commands, [
            ["/python", "-m", "alembic", "upgrade", "head"],
            ["/python", str(BACKEND / "scripts" / "seed_catalog.py"), "--apply"],
        ])

    @patch("scripts.bootstrap_catalog.sys.executable", "/python")
    @patch("scripts.bootstrap_catalog.subprocess.run")
    def test_main_runs_both_bootstrap_steps_from_backend_directory(self, run):
        self.assertEqual(main(), 0)
        run.assert_has_calls([
            call(
                ["/python", "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND,
                check=True,
            ),
            call(
                ["/python", str(BACKEND / "scripts" / "seed_catalog.py"), "--apply"],
                cwd=BACKEND,
                check=True,
            ),
        ], any_order=False)
        self.assertEqual(run.call_count, 2)

    @patch("scripts.bootstrap_catalog.subprocess.run")
    def test_bootstrap_stops_if_migration_fails(self, run):
        from subprocess import CalledProcessError
        run.side_effect = CalledProcessError(1, ["alembic"])
        with self.assertRaises(CalledProcessError):
            main()
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
