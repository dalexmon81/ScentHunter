"""Partial persistent catalogs must bootstrap every missing retailer."""

import os
import unittest
from unittest.mock import patch

import main


class PartialCatalogBootstrapTests(unittest.TestCase):
    def test_partial_catalog_starts_immediate_discovery_for_missing_stores(self):
        missing = ["parfumzentrum", "sabina", "easycosmetic"]
        started = []

        class FakeThread:
            def __init__(self, *, target, args=(), kwargs=None, daemon=None, name=None):
                self.target = target
                self.args = args
                self.kwargs = kwargs or {}
                self.daemon = daemon
                self.name = name

            def start(self):
                started.append({
                    "target": self.target,
                    "args": self.args,
                    "name": self.name,
                    "daemon": self.daemon,
                })

        with patch.dict(os.environ, {"CATALOG_BACKGROUND_WORKERS_ENABLED": "1"}), \
             patch.object(main, "_CATALOG_BOOTSTRAP_STARTED", False), \
             patch.object(main, "_catalog_is_ready", return_value=True), \
             patch.object(main, "_stores_missing_catalog", return_value=missing), \
             patch.object(main, "_start_catalog_hydration", side_effect=lambda: started.append("hydration")), \
             patch.object(main, "_start_catalog_discovery", side_effect=lambda: started.append("discovery")), \
             patch.object(main.threading, "Thread", FakeThread):
            main._start_catalog_bootstrap()

        self.assertEqual(started[:2], ["hydration", "discovery"])
        self.assertEqual(started[2], {
            "target": main._discover_missing_catalog_stores,
            "args": (tuple(missing),),
            "name": "scenthunter-missing-store-bootstrap",
            "daemon": True,
        })


if __name__ == "__main__":
    unittest.main()
