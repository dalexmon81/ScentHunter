import ast, pathlib
files = ["backend/catalog_engine.py", "backend/scrapers/deloox/scraper.py", "backend/tests/test_parfumzentrum_hydration.py"]
for name in files:
    ast.parse(pathlib.Path(name).read_text(encoding="utf-8"), filename=name)
print("AST parse: PASS")
