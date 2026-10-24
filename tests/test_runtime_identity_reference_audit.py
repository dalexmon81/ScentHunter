"""Tests for the read-only SQLite identity-reference inventory."""
import sqlite3

from backend.scenthunter_next_engine.runtime_identity_reference_audit import audit_database


def test_finds_product_and_variant_ids_without_mutating_database(tmp_path):
    db_path = tmp_path / "catalog.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript("""
        CREATE TABLE products (product_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE variants (variant_id TEXT PRIMARY KEY, product_id TEXT);
        CREATE TABLE offers (id INTEGER PRIMARY KEY, payload TEXT);
        INSERT INTO products VALUES ('SH-0043', 'Acqua di Gio Profondo');
        INSERT INTO variants VALUES ('VAR-89c2a2a86bedb3c5', 'SH-0043');
        INSERT INTO offers VALUES (1, '{"product_id":"SH-AUTO-0018"}');
    """)
    connection.commit()
    connection.close()

    before = db_path.read_bytes()
    report = audit_database(
        db_path,
        ["SH-0043", "SH-AUTO-0018", "VAR-89c2a2a86bedb3c5"],
    )

    assert report["read_only"] is True
    assert report["database_mutated"] is False
    assert report["query_only_enabled"] is True
    assert report["objects_scanned"] == 3
    found = {(item["object"], item["column"]) for item in report["matches"]}
    assert ("products", "product_id") in found
    assert ("variants", "variant_id") in found
    assert ("variants", "product_id") in found
    assert ("offers", "payload") in found
    assert db_path.read_bytes() == before


def test_missing_database_fails_closed(tmp_path):
    try:
        audit_database(tmp_path / "missing.sqlite3", ["SH-0043"])
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Missing DB must not be created automatically")
