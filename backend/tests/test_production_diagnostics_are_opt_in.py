from pathlib import Path
import ast


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def test_diagnostic_router_imports_are_behind_explicit_opt_in():
    source = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(source)
    guards = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and "SCENTHUNTER_DIAGNOSTICS_ENABLED" in ast.unparse(node.test)
    ]
    assert guards, "diagnostic router mounting must require an explicit environment opt-in"
    assert any(
        "diagnose_two_scrapers" in ast.unparse(node)
        and "include_router" in ast.unparse(node)
        for guard in guards
        for node in guard.body
    ), "diagnostic routers must be mounted only inside the opt-in guard"


def test_production_route_table_filters_diagnostic_paths_by_default():
    source = MAIN.read_text(encoding="utf-8")
    assert "SCENTHUNTER_DIAGNOSTICS_ENABLED" in source
    assert "('diagnose', 'diagnostic')" in source
    assert "'/admin/phase2/sql-verification'" in source
    assert "app.router.routes = [" in source
