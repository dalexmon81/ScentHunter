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
