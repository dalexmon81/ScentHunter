from __future__ import annotations

import unittest

from app.connectors.registry import (
    EXPECTED_RETAILER_KEYS,
    RETAILER_CAPABILITIES,
    get_retailer_capability,
    list_retailer_capabilities,
)


class RetailerCapabilityRegistryTests(unittest.TestCase):
    def test_inventory_contains_exactly_the_nine_required_retailers(self):
        self.assertEqual(
            {item.key for item in list_retailer_capabilities()},
            EXPECTED_RETAILER_KEYS,
        )
        self.assertEqual(len(RETAILER_CAPABILITIES), 9)

    def test_only_existing_worker_routes_are_marked_registered(self):
        registered = {
            item.key for item in RETAILER_CAPABILITIES
            if item.readiness == "worker_registered"
        }
        self.assertEqual(
            registered,
            {"notino", "deloox", "easycosmetic", "parfumzentrum", "sabina", "bplatz"},
        )
        for key in registered:
            self.assertEqual(
                get_retailer_capability(key).worker_stages,
                ("discover", "fetch", "refresh"),
            )

    def test_adapter_only_retailers_are_not_claimed_as_worker_ready(self):
        adapter_only = {
            item.key for item in RETAILER_CAPABILITIES
            if item.readiness == "adapter_only"
        }
        self.assertEqual(
            adapter_only,
            {"orioudh", "parfumcity", "perfumemarket"},
        )
        for key in adapter_only:
            item = get_retailer_capability(key)
            self.assertTrue(item.adapter_module)
            self.assertEqual(item.worker_stages, ())

    def test_unknown_store_slugs_are_not_invented(self):
        for key in ("orioudh", "parfumcity", "perfumemarket"):
            with self.subTest(key=key):
                self.assertIsNone(get_retailer_capability(key).store_slug)

    def test_registry_is_metadata_only_and_does_not_activate_retailers(self):
        # A registry lookup is pure metadata: no scheduler flags, network
        # clients, worker registration, or database handles are exposed.
        item = get_retailer_capability("bplatz")
        self.assertEqual(item.readiness, "adapter_only")
        self.assertFalse(hasattr(item, "enabled"))
        self.assertFalse(hasattr(item, "health"))
        self.assertFalse(hasattr(item, "session"))

    def test_unknown_retailer_fails_closed(self):
        with self.assertRaisesRegex(KeyError, "unknown retailer capability"):
            get_retailer_capability("not-a-retailer")


if __name__ == "__main__":
    unittest.main()
