"""Regression tests for guarded Deloox recovery; all writes use temporary SQLite files."""
import sqlite3

from backend.scenthunter_next_engine.deloox_recovery import (
    apply_recovery,
    build_report,
    is_product_url,
)


def _db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE store_products (
            store TEXT, url TEXT, fetch_status TEXT, name TEXT, price REAL
        );
        CREATE TABLE store_urls (
            store TEXT, url TEXT, active INTEGER
        );
        CREATE TABLE hydration_queue (
            store TEXT, url TEXT, state TEXT, attempts INTEGER, available_at REAL,
            last_error TEXT, last_http_status INTEGER, last_started_at REAL,
            last_finished_at REAL, leased_until REAL, lease_token TEXT
        );
    """)
    rows = [
        ("https://www.deloox.com/product/1380881/chloe-le-parfum-150-ml.html", 1, "DEAD"),
        ("https://www.deloox.nl/zoeken.html", 1, "DEAD"),
        ("https://www.deloox.be/produit/1321602/armani-acqua-di-gio-profondo-30-ml.html", 1, "DONE"),
        ("https://www.deloox.be/produit/1323846/armani-acqua-di-gio-profondo-100-ml.html", 0, "DEAD"),
    ]
    for url, active, state in rows:
        conn.execute(
            "INSERT INTO store_products(store,url,fetch_status,name,price) VALUES(?,?,?,?,?)",
            ("deloox", url, "ERROR:RuntimeError: product_parser_not_found", "Existing good name", 60.99),
        )
        conn.execute("INSERT INTO store_urls(store,url,active) VALUES(?,?,?)", ("deloox", url, active))
        conn.execute(
            """INSERT INTO hydration_queue(
                store,url,state,attempts,available_at,last_error,last_http_status,
                last_started_at,last_finished_at,leased_until,lease_token
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ("deloox", url, state, 5, 100, "old error", 200, 90, 95, None, None),
        )
    conn.commit()
    conn.close()


def test_product_url_admission_is_strict():
    assert is_product_url("https://www.deloox.com/product/1380881/chloe.html")
    assert is_product_url("https://www.deloox.be/produit/123/test.html")
    assert not is_product_url("https://www.deloox.nl/zoeken.html")
    assert not is_product_url("https://www.deloox.com/")
    assert not is_product_url("https://evil.example/product/123/test.html")


def test_dry_run_reports_candidates_without_mutating_database(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    _db(path)
    before = path.read_bytes()

    report = build_report(str(path))

    assert report["status"] == "REVIEW_REQUIRED"
    assert report["read_only"] is True
    assert report["database_mutated"] is False
    assert report["eligible_product_urls"] == 1
    assert report["excluded_non_product_urls"] == 1
    assert path.read_bytes() == before


def test_apply_requeues_only_active_dead_valid_product_parser_errors(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    _db(path)

    report = apply_recovery(str(path))

    assert report["status"] == "RECOVERY_QUEUED"
    assert report["queue_rows_reset_to_pending"] == 1
    assert report["store_products_modified"] is False
    assert report["store_urls_modified"] is False

    conn = sqlite3.connect(path)
    try:
        states = dict(conn.execute("SELECT url, state FROM hydration_queue"))
        products = list(conn.execute("SELECT url, name, price FROM store_products"))
    finally:
        conn.close()

    valid_dead = "https://www.deloox.com/product/1380881/chloe-le-parfum-150-ml.html"
    search = "https://www.deloox.nl/zoeken.html"
    done = "https://www.deloox.be/produit/1321602/armani-acqua-di-gio-profondo-30-ml.html"
    inactive = "https://www.deloox.be/produit/1323846/armani-acqua-di-gio-profondo-100-ml.html"
    assert states[valid_dead] == "PENDING"
    assert states[search] == "DEAD"
    assert states[done] == "DONE"
    assert states[inactive] == "DEAD"
    assert all(name == "Existing good name" and price == 60.99 for _, name, price in products)
