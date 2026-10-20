import json
import tempfile
import unittest
from pathlib import Path

from scenthunter_next_engine.shadow_runner import run_shadow


class ShadowRunnerTests(unittest.TestCase):
    def test_writes_read_only_comparison_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            newer = root / "next.json"
            report_path = root / "out" / "report.json"
            row = {"store": "deloox", "brand": "Acme", "name": "Acme No. 1 100 ml Eau de Parfum",
                   "size_ml": 100, "concentration": "edp", "price": "89.99", "currency": "EUR",
                   "url": "https://shop.example/product"}
            legacy.write_text(json.dumps([row]), encoding="utf-8")
            newer.write_text(json.dumps([row]), encoding="utf-8")
            before = (legacy.read_bytes(), newer.read_bytes())
            report = run_shadow(legacy, newer, report_path)
            self.assertEqual(report["mode"], "offline_snapshot_only")
            self.assertFalse(report["mutated_database"])
            self.assertEqual(report["network_requests"], 0)
            self.assertEqual(report["comparison"]["matched_count"], 1)
            self.assertEqual(before, (legacy.read_bytes(), newer.read_bytes()))
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["comparison"]["matched_count"], 1)

    def test_refuses_same_input_and_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "same.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                run_shadow(path, path, Path(tmp) / "out.json")
            with self.assertRaises(ValueError):
                run_shadow(path, Path(tmp) / "other.json", path)

    def test_accepts_schema_aware_sqlite_export_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            product = {"store": "deloox", "url": "https://shop.example/p", "name": "Perfume X",
                       "brand": "Brand X", "size_ml": 100, "price": 50, "currency": "EUR"}
            variant = {"store": "deloox", "url": "https://shop.example/p", "variant_url": "https://shop.example/p?size=100",
                       "variant_key": "100ml", "name": "Perfume X", "brand": "Brand X", "size_ml": 100,
                       "price": 50, "currency": "EUR"}
            snapshot = {"schema_version": 1, "tables": {
                "store_products": {"rows": [product]},
                "store_product_variants": {"rows": [variant]},
            }}
            (root / "legacy.json").write_text(json.dumps(snapshot), encoding="utf-8")
            (root / "next.json").write_text(json.dumps([dict(variant, url=variant["variant_url"])]), encoding="utf-8")
            report = run_shadow(root / "legacy.json", root / "next.json", root / "report.json")
            self.assertEqual(report["comparison"]["legacy_count"], 1)
            self.assertEqual(report["comparison"]["matched_count"], 1)

    def test_rejects_invalid_json_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "legacy.json").write_text('{"oops": true}', encoding="utf-8")
            (root / "next.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                run_shadow(root / "legacy.json", root / "next.json", root / "report.json")


if __name__ == "__main__":
    unittest.main()
