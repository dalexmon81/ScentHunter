from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_notino_review_priority import build_review_queue


class NotinoReviewPriorityTests(unittest.TestCase):
    def test_queue_holds_bad_and_duplicate_gtins_and_never_auto_approves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feed_path = root / "feed.csv"
            candidates_path = root / "candidates.csv"
            feed_fields = ["id", "title", "brand", "gtin", "gtin_valid", "price", "availability"]
            feed_rows = [
                {"id": "HIGH", "title": "Known EDP 100 ml", "brand": "Known", "gtin": "111", "gtin_valid": "True", "price": "20 EUR", "availability": "in stock"},
                {"id": "AMBIG", "title": "Close match EDP 100 ml", "brand": "Close", "gtin": "777", "gtin_valid": "True", "price": "20 EUR", "availability": "in stock"},
                {"id": "DUP-A", "title": "Duplicate A", "brand": "Dup", "gtin": "222", "gtin_valid": "True", "price": "20 EUR", "availability": "in stock"},
                {"id": "DUP-B", "title": "Duplicate B", "brand": "Dup", "gtin": "222", "gtin_valid": "True", "price": "20 EUR", "availability": "in stock"},
                {"id": "INVALID", "title": "Invalid GTIN", "brand": "Invalid", "gtin": "333", "gtin_valid": "False", "price": "20 EUR", "availability": "in stock"},
                {"id": "PRODUCT", "title": "Product only", "brand": "Product", "gtin": "444", "gtin_valid": "True", "price": "20 EUR", "availability": "in stock"},
                {"id": "NONE", "title": "No match", "brand": "None", "gtin": "555", "gtin_valid": "True", "price": "20 EUR", "availability": "in stock"},
                {"id": "CONFLICT", "title": "Wrong size", "brand": "Conflict", "gtin": "666", "gtin_valid": "True", "price": "20 EUR", "availability": "in stock"},
                {"id": "REFILL", "title": "Known Eau de Parfum Recharge Refill 100 ml", "brand": "Known", "gtin": "888", "gtin_valid": "True", "price": "20 EUR", "availability": "in stock"},
            ]
            with feed_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=feed_fields)
                writer.writeheader()
                writer.writerows(feed_rows)

            candidate_fields = [
                "feed_external_id", "candidate_score", "confidence_band", "review_status",
                "canonical_product_id", "canonical_variant_id", "candidate_scope",
                "canonical_brand", "canonical_names", "canonical_size_ml",
                "canonical_concentration", "name_similarity", "gtin_match",
                "size_match", "concentration_match", "gender_conflict",
            ]
            candidate_rows = [
                {"feed_external_id":"HIGH","candidate_score":"1.0","confidence_band":"review_high","review_status":"needs_human_review","canonical_product_id":"P1","canonical_variant_id":"V1","candidate_scope":"variant","canonical_brand":"Known","canonical_names":"known perfume","canonical_size_ml":"100","canonical_concentration":"EDP","name_similarity":"1.0","gtin_match":"False","size_match":"True","concentration_match":"True","gender_conflict":"False"},
                {"feed_external_id":"AMBIG","candidate_score":"0.93","confidence_band":"review_high","review_status":"needs_human_review","canonical_product_id":"PA","canonical_variant_id":"VA","candidate_scope":"variant","canonical_brand":"Close","canonical_names":"close perfume","canonical_size_ml":"100","canonical_concentration":"EDP","name_similarity":"0.93","gtin_match":"False","size_match":"True","concentration_match":"True","gender_conflict":"False"},
                {"feed_external_id":"AMBIG","candidate_score":"0.91","confidence_band":"review_high","review_status":"needs_human_review","canonical_product_id":"PB","canonical_variant_id":"VB","candidate_scope":"variant","canonical_brand":"Close","canonical_names":"close perfume alt","canonical_size_ml":"100","canonical_concentration":"EDP","name_similarity":"0.91","gtin_match":"False","size_match":"True","concentration_match":"True","gender_conflict":"False"},
                {"feed_external_id":"DUP-A","candidate_score":"0.9","confidence_band":"review_high","review_status":"needs_human_review","canonical_product_id":"P2","canonical_variant_id":"V2","candidate_scope":"variant","canonical_brand":"Dup","canonical_names":"dup","canonical_size_ml":"100","canonical_concentration":"EDP","name_similarity":"0.9","gtin_match":"False","size_match":"True","concentration_match":"True","gender_conflict":"False"},
                {"feed_external_id":"DUP-B","candidate_score":"0.9","confidence_band":"review_high","review_status":"needs_human_review","canonical_product_id":"P2","canonical_variant_id":"V2","candidate_scope":"variant","canonical_brand":"Dup","canonical_names":"dup","canonical_size_ml":"100","canonical_concentration":"EDP","name_similarity":"0.9","gtin_match":"False","size_match":"True","concentration_match":"True","gender_conflict":"False"},
                {"feed_external_id":"INVALID","candidate_score":"0.8","confidence_band":"review_medium","review_status":"needs_human_review","canonical_product_id":"P3","canonical_variant_id":"V3","candidate_scope":"variant","canonical_brand":"Invalid","canonical_names":"invalid","canonical_size_ml":"100","canonical_concentration":"EDP","name_similarity":"0.8","gtin_match":"False","size_match":"True","concentration_match":"True","gender_conflict":"False"},
                {"feed_external_id":"PRODUCT","candidate_score":"0.7","confidence_band":"review_low","review_status":"needs_human_review","canonical_product_id":"P4","canonical_variant_id":"","candidate_scope":"product_only","canonical_brand":"Product","canonical_names":"product","canonical_size_ml":"","canonical_concentration":"","name_similarity":"1.0","gtin_match":"False","size_match":"False","concentration_match":"False","gender_conflict":"False"},
                {"feed_external_id":"NONE","candidate_score":"0","confidence_band":"no_candidate","review_status":"no_candidate","canonical_product_id":"","canonical_variant_id":"","candidate_scope":"","canonical_brand":"","canonical_names":"","canonical_size_ml":"","canonical_concentration":"","name_similarity":"0","gtin_match":"False","size_match":"False","concentration_match":"False","gender_conflict":"False"},
                {"feed_external_id":"CONFLICT","candidate_score":"0.4","confidence_band":"low","review_status":"needs_human_review","canonical_product_id":"P5","canonical_variant_id":"V5","candidate_scope":"variant","canonical_brand":"Conflict","canonical_names":"conflict","canonical_size_ml":"50","canonical_concentration":"EDT","name_similarity":"0.7","gtin_match":"False","size_match":"False","concentration_match":"False","gender_conflict":"True"},
                {"feed_external_id":"REFILL","candidate_score":"1.0","confidence_band":"review_high","review_status":"needs_human_review","canonical_product_id":"P1","canonical_variant_id":"V1","candidate_scope":"variant","canonical_brand":"Known","canonical_names":"known perfume","canonical_size_ml":"100","canonical_concentration":"EDP","name_similarity":"1.0","gtin_match":"False","size_match":"True","concentration_match":"True","gender_conflict":"False"},
            ]
            with candidates_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=candidate_fields)
                writer.writeheader()
                writer.writerows(candidate_rows)

            rows, summary = build_review_queue(feed_path, candidates_path)
            by_id = {row["id"]: row for row in rows}
            self.assertEqual(by_id["HIGH"]["priority"], "B_HIGH_CONFIDENCE_MANUAL_REVIEW")
            self.assertEqual(by_id["AMBIG"]["priority"], "A_AMBIGUOUS_CANDIDATES")
            self.assertEqual(by_id["AMBIG"]["score_margin"], 0.02)
            self.assertTrue(by_id["AMBIG"]["ambiguous"])
            self.assertEqual(by_id["DUP-A"]["priority"], "0_HOLD_DUPLICATE_GTIN")
            self.assertEqual(by_id["DUP-B"]["priority"], "0_HOLD_DUPLICATE_GTIN")
            self.assertEqual(by_id["INVALID"]["priority"], "0_HOLD_INVALID_GTIN")
            self.assertEqual(by_id["PRODUCT"]["priority"], "F_PRODUCT_ONLY_REQUIRES_NEW_VARIANT")
            self.assertEqual(by_id["NONE"]["priority"], "G_NO_CANDIDATE")
            self.assertEqual(by_id["CONFLICT"]["priority"], "D_CONFLICT_OR_ATTRIBUTE_MISMATCH")
            self.assertEqual(by_id["REFILL"]["priority"], "0_HOLD_VARIANT_FORMAT")
            self.assertTrue(by_id["REFILL"]["variant_format_conflict"])
            self.assertEqual(summary["automatic_matches_approved"], 0)
            self.assertEqual(summary["catalog_writes"], 0)
            self.assertEqual(summary["invalid_gtin_hold_rows"], 1)
            self.assertEqual(summary["duplicate_gtin_hold_rows"], 2)


if __name__ == "__main__":
    unittest.main()
