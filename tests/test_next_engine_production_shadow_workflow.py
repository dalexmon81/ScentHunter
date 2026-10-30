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

    def test_production_comparison_remains_read_only_and_manual(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", source)
        self.assertIn('"catalog_modified": False', source)
        self.assertIn('"database_mutated": False', source)
        self.assertIn("Production Next Engine shadow comparison: PASS", source)


if __name__ == "__main__":
    unittest.main()
