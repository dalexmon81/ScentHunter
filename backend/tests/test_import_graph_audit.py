from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.audit_python_import_graph import build_import_graph


class ImportGraphAuditTests(unittest.TestCase):
    def test_records_absolute_and_relative_local_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir()
            (root / "app" / "__init__.py").write_text("from .catalog import normalize\n", encoding="utf-8")
            (root / "app" / "catalog.py").write_text("def normalize(value): return value\n", encoding="utf-8")
            (root / "workers.py").write_text("from app.catalog import normalize\n", encoding="utf-8")
            graph = build_import_graph(root)
        self.assertEqual(graph["syntax_errors"], [])
        self.assertEqual(graph["unresolved_relative_imports"], [])
        self.assertEqual(graph["modules"]["app"]["imports"][0]["module"], "app.catalog")
        self.assertEqual(graph["modules"]["workers"]["imports"][0]["module"], "app.catalog")

    def test_reports_python_syntax_errors_without_importing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
            graph = build_import_graph(root)
        self.assertEqual(graph["module_count"], 1)
        self.assertEqual(graph["syntax_errors"][0]["file"], "broken.py")


if __name__ == "__main__":
    unittest.main()
