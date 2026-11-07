import pytest

import app.db as catalog_db
from app.db import database_url


def _clear_database_urls(monkeypatch):
    monkeypatch.delenv("SCENTHUNTER_CATALOG_DATABASE_URL", raising=False)
    monkeypatch.delenv("SCENTHUNTER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_postgresql_requirement_rejects_the_sqlite_default(monkeypatch):
    _clear_database_urls(monkeypatch)
    monkeypatch.setenv("SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL", "1")
    with pytest.raises(RuntimeError, match="requires a PostgreSQL catalog URL"):
        database_url()


def test_postgresql_requirement_accepts_explicit_postgresql_url(monkeypatch):
    monkeypatch.setenv(
        "SCENTHUNTER_CATALOG_DATABASE_URL",
        "postgresql+psycopg://catalog:secret@db.example.test/catalog",
    )
    monkeypatch.setenv("SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL", "true")
    assert database_url().startswith("postgresql+psycopg://")


def test_postgresql_requirement_can_be_explicitly_disabled(monkeypatch, tmp_path):
    _clear_database_urls(monkeypatch)
    monkeypatch.setenv("SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL", "false")
    monkeypatch.setattr(
        catalog_db,
        "DEFAULT_DATABASE_URL",
        f"sqlite:///{tmp_path / 'catalog' / 'catalog.sqlite3'}",
    )
    assert database_url().startswith("sqlite:///")


def test_invalid_postgresql_requirement_value_fails_closed(monkeypatch):
    monkeypatch.setenv(
        "SCENTHUNTER_CATALOG_DATABASE_URL",
        "postgresql+psycopg://catalog:secret@db.example.test/catalog",
    )
    monkeypatch.setenv("SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL", "sometimes")
    with pytest.raises(RuntimeError, match="expected a boolean"):
        database_url()


def test_fly_standard_database_url_is_accepted_when_specific_urls_are_absent(monkeypatch):
    _clear_database_urls(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://catalog:secret@fly-postgres.internal/catalog",
    )
    monkeypatch.setenv("SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL", "1")
    assert database_url() == "postgresql+psycopg://catalog:secret@fly-postgres.internal/catalog"


def test_fly_standard_sqlite_database_url_is_rejected_by_postgresql_guard(monkeypatch):
    _clear_database_urls(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite:////data/unintended.sqlite3")
    monkeypatch.setenv("SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL", "1")
    with pytest.raises(RuntimeError, match="requires a PostgreSQL catalog URL"):
        database_url()
