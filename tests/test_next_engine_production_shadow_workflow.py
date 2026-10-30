from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW = Path(".github/workflows/next-engine-production-shadow.yml")


class ProductionShadowWorkflowTests(unittest.TestCase):
    def test_production_comparison_uses_async_search_contract(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('get_json("/search-start?q="', source)
        self.assertIn('get_json("/search-status?job_id="', source)
        self.assertNotIn('get_json("/search?q="', source)

    def test_production_comparison_is_manual_and_discloses_possible_side_effects(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", source)
        self.assertIn("confirm_production_shadow == 'yes'", source)
        self.assertIn("reprioritize hydration", source)
        self.assertIn('"workflow_direct_catalog_writes": False', source)
        self.assertIn('"production_search_may_reprioritize_hydration_queue": True', source)
        self.assertIn('"background_hydration_may_update_catalog": True', source)
        self.assertIn('"configured_live_retailer_fallbacks_may_run": True', source)
        self.assertNotIn('"catalog_modified": False', source)
        self.assertNotIn('"database_mutated": False', source)
        self.assertIn("hydration/fallback side effects were possible", source)
        self.assertNotIn("without changing production", source)
        self.assertNotIn("read-only report artifact", source)


if __name__ == "__main__":
    unittest.main()
