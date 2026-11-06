from pathlib import Path
import ast


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def test_standalone_diagnostic_routers_are_not_imported_by_production_app():
    source = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(source)
    diagnostic_imports = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and any(
            "diagnose" in (alias.name if isinstance(node, ast.Import) else (node.module or "")).lower()
            for alias in (node.names if isinstance(node, ast.Import) else node.names)
        )
    ]
    assert not diagnostic_imports, "standalone diagnostic modules must not be imported by the production app"


def test_production_route_table_filters_inline_diagnostic_paths_by_default():
    source = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(source)
    guards = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and "SCENTHUNTER_DIAGNOSTICS_ENABLED" in ast.unparse(node.test)
    ]
    assert guards, "inline diagnostics must be disabled unless explicitly enabled"
    assert "('diagnose', 'diagnostic')" in source
    assert "'/admin/phase2/sql-verification'" in source
    assert "app.router.routes = [" in source
