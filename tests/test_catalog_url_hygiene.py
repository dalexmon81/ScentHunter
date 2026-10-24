"""Regression tests for the strictly read-only Deloox URL hygiene audit."""
from backend.scenthunter_next_engine import catalog_url_hygiene as hygiene


def test_classifies_stale_search_and_homepage_rows_but_keeps_numeric_products():
    rows = [
        {"store": "deloox", "url": "https://www.deloox.nl/zoeken.html", "slug": "zoeken", "active": 1},
        {"store": "deloox", "url": "https://www.deloox.lu/chercher.html", "slug": "chercher", "active": 1},
        {"store": "deloox", "url": "https://www.deloox.com/", "slug": "", "active": 1},
        {"store": "deloox", "url": "https://www.deloox.com/product/1380881/chloe-le-parfum-150-ml.html", "slug": "chloe-le-parfum-150-ml", "active": 1},
        {"store": "deloox", "url": "https://www.deloox.com/search.html", "slug": "search", "active": 0},
    ]
    invalid = hygiene.classify_invalid_urls(rows)
    assert {row["url"] for row in invalid} == {
        "https://www.deloox.nl/zoeken.html",
        "https://www.deloox.lu/chercher.html",
        "https://www.deloox.com/",
    }
    assert all(row["reason"] == "rejected_by_current_product_url_admission" for row in invalid)


def test_audit_is_read_only(monkeypatch):
    class FakeConnection:
        def __init__(self):
            self.closed = False
            self.queries = []

        def execute(self, query):
            self.queries.append(query)
            assert query.startswith("SELECT")
            return self

        def fetchall(self):
            return [
                {"store": "deloox", "url": "https://www.deloox.com/search.html", "slug": "search", "active": 1},
                {"store": "deloox", "url": "https://www.deloox.com/product/1380881/chloe-le-parfum-150-ml.html", "slug": "product", "active": 1},
            ]

        def close(self):
            self.closed = True

    conn = FakeConnection()
    monkeypatch.setattr(hygiene.catalog_engine, "db", lambda: conn)
    report = hygiene.audit()
    assert report["read_only"] is True
    assert report["database_mutated"] is False
    assert report["active_deloox_urls_examined"] == 2
    assert report["invalid_active_urls_found"] == 1
    assert report["invalid_urls"][0]["url"] == "https://www.deloox.com/search.html"
    assert conn.closed
    assert len(conn.queries) == 1


def test_production_read_only_audit_url_classifier():
    import runpy
    from pathlib import Path

    script = Path(__file__).with_name("fly_readonly_runtime_deloox_audit.py")
    is_product = runpy.run_path(str(script))["is_deloox_product_url"]
    assert is_product("https://www.deloox.com/product/1380881/chloe-le-parfum-150-ml.html")
    assert is_product("https://www.deloox.be/produit/1009926/hermes-eau-de-cologne-100-ml.html")
    assert not is_product("https://www.deloox.nl/zoeken.html")
    assert not is_product("https://www.deloox.lu/chercher.html")
    assert not is_product("https://www.deloox.es/buscar.html")
    assert not is_product("https://www.deloox.com/")
    assert not is_product("https://example.com/product/1380881/example.html")
