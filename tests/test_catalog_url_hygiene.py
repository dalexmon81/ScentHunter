"""Regression tests for the strictly read-only Deloox URL hygiene audit."""
import sqlite3

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


def test_audit_is_read_only(monkeypatch, tmp_path):
    db_path = tmp_path / "catalog.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE store_urls (store TEXT, url TEXT, slug TEXT, active INTEGER)")
    conn.executemany(
        "INSERT INTO store_urls VALUES (?, ?, ?, ?)",
        [
            ("deloox", "https://www.deloox.com/search.html", "search", 1),
            ("deloox", "https://www.deloox.com/product/1380881/chloe-le-parfum-150-ml.html", "product", 1),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DB", str(db_path))
    before = db_path.read_bytes()

    report = hygiene.audit()

    assert report["status"] == "AUDIT_COMPLETE"
    assert report["scope"] == "local_database_only"
    assert report["read_only"] is True
    assert report["database_mutated"] is False
    assert report["active_deloox_urls_examined"] == 2
    assert report["invalid_active_urls_found"] == 1
    assert report["invalid_urls"][0]["url"] == "https://www.deloox.com/search.html"
    assert db_path.read_bytes() == before

    # Verify the audit's DB URI really prohibits writes.
    ro = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    ro.execute("PRAGMA query_only=ON")
    try:
        try:
            ro.execute("INSERT INTO store_urls VALUES ('deloox', 'https://example.test', 'x', 1)")
        except sqlite3.OperationalError:
            pass
        else:
            raise AssertionError("read-only SQLite connection unexpectedly accepted a write")
    finally:
        ro.close()


def test_empty_local_catalog_is_not_reported_as_a_clean_production_audit(monkeypatch, tmp_path):
    db_path = tmp_path / "empty.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE store_urls (store TEXT, url TEXT, slug TEXT, active INTEGER)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DB", str(db_path))

    report = hygiene.audit()

    assert report["status"] == "EMPTY_LOCAL_CATALOG"
    assert report["scope"] == "local_database_only"
    assert report["active_deloox_urls_examined"] == 0
    assert "not a production inventory" in report["note"]


def test_missing_local_database_does_not_create_or_initialize_it(monkeypatch, tmp_path):
    db_path = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DB", str(db_path))

    report = hygiene.audit()

    assert report["status"] == "DATABASE_NOT_FOUND"
    assert report["read_only"] is True
    assert report["database_mutated"] is False
    assert not db_path.exists()


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
