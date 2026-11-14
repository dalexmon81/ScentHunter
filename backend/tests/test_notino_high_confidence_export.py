from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.export_notino_high_confidence_review import export_review_rows


class NotinoHighConfidenceExportTests(unittest.TestCase):
    def test_exports_only_manual_review_variant_candidates(self):
        fields = [
            "id", "title", "brand", "gtin", "priority", "canonical_product_id",
            "canonical_variant_id", "gender_conflict", "variant_format_conflict",
            "candidate_score", "review_instruction",
        ]
        rows = [
            {"id":"KEEP","title":"A perfume","brand":"A","gtin":"123","priority":"B_HIGH_CONFIDENCE_MANUAL_REVIEW","canonical_product_id":"P1","canonical_variant_id":"V1","gender_conflict":"False","variant_format_conflict":"False","candidate_score":"0.98","review_instruction":"Verify"},
            {"id":"AMBIG","priority":"A_AMBIGUOUS_CANDIDATES","canonical_product_id":"P2","canonical_variant_id":"V2"},
            {"id":"NO_VARIANT","priority":"B_HIGH_CONFIDENCE_MANUAL_REVIEW","canonical_product_id":"P3","canonical_variant_id":""},
            {"id":"GENDER","priority":"B_HIGH_CONFIDENCE_MANUAL_REVIEW","canonical_product_id":"P4","canonical_variant_id":"V4","gender_conflict":"True"},
            {"id":"REFILL","priority":"B_HIGH_CONFIDENCE_MANUAL_REVIEW","canonical_product_id":"P5","canonical_variant_id":"V5","variant_format_conflict":"True"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queue.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            selected, summary = export_review_rows(path)

        self.assertEqual([row["id"] for row in selected], ["KEEP"])
        self.assertEqual(summary["manual_review_rows"], 1)
        self.assertEqual(summary["automatic_approvals"], 0)
        self.assertEqual(summary["catalog_writes"], 0)


if __name__ == "__main__":
    unittest.main()
