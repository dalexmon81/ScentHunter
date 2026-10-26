"""Tests for bounded, exact-signature stale parser error recovery."""
import sqlite3

from backend import recover_stale_parser_errors as recovery


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE store_urls (store TEXT, url TEXT, active INTEGER,
                                 PRIMARY KEY (store, url));
        CREATE TABLE hydration_queue (
            store TEXT, url TEXT, state TEXT, attempts INTEGER, available_at REAL,
            first_seen_at REAL, last_error TEXT, last_http_status INTEGER,
            last_started_at REAL, last_finished_at REAL, leased_until REAL,
            PRIMARY KEY (store, url));
    """)
    return conn


def _insert(conn, store, url, error, *, state="DEAD", active=1, attempts=8):
    conn.execute("INSERT INTO store_urls VALUES (?, ?, ?)", (store, url, active))
    conn.execute(
        """INSERT INTO hydration_queue
           (store,url,state,attempts,available_at,first_seen_at,last_error,
            last_http_status,last_started_at,last_finished_at,leased_until)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (store, url, state, attempts, 0, 0, error, 500, 1, 2, None),
    )


def test_recovery_plan_only_includes_exact_known_errors_and_active_product_urls(monkeypatch):
    conn = _db()
    _insert(conn, "orioudh", "https://orioudh.com/products/good-item",
            "ERROR:TypeError: _extract_product() missing 1 required positional argument: 'query'")
    _insert(conn, "perfumemarket", "https://perfumemarket.nl/products/good-item",
            "ERROR:NameError: name 'STORE' is not defined", state="ERROR")
    _insert(conn, "orioudh", "https://orioudh.com/products/other-item",
            "ERROR:HTTP 404")
    _insert(conn, "orioudh", "https://orioudh.com/products/inactive-item",
            "ERROR:TypeError: _extract_product() missing 1 required positional argument: 'query'",
            active=0)
    _insert(conn, "orioudh", "https://evil.example/products/unsafe",
            "ERROR:TypeError: _extract_product() missing 1 required positional argument: 'query'")
    monkeypatch.setattr(recovery, "_current_parser_available", lambda store: True)

    plan = recovery.build_recovery_plan(conn, now=100, limit_per_store=10)

    assert {(item["store"], item["url"]) for item in plan} == {
        ("orioudh", "https://orioudh.com/products/good-item"),
        ("perfumemarket", "https://perfumemarket.nl/products/good-item"),
    }
    assert all(item["new_state"] == "PENDING" for item in plan)
    conn.close()


def test_limit_is_hard_capped_at_ten_per_store(monkeypatch):
    conn = _db()
    signature = recovery.ELIGIBLE_ERRORS["orioudh"]
    for i in range(15):
        _insert(conn, "orioudh", f"https://orioudh.com/products/item-{i}", signature)
    monkeypatch.setattr(recovery, "_current_parser_available", lambda store: True)

    plan = recovery.build_recovery_plan(conn, now=100, limit_per_store=500)

    assert len(plan) == 10
    assert all(item["store"] == "orioudh" for item in plan)
    conn.close()


def test_unsafe_url_is_rejected():
    assert not recovery._is_safe_product_url("orioudh", "http://orioudh.com/products/a")
    assert not recovery._is_safe_product_url("orioudh", "https://orioudh.com/products/a?x=1")
    assert not recovery._is_safe_product_url("perfumemarket", "https://evil.example/products/a")
