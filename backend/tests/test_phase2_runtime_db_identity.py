from sqlalchemy import create_engine

from app.db_runtime_identity import (
    configuration_source,
    log_runtime_database_identity,
)


def test_configuration_source_reports_only_variable_name():
    assert configuration_source({
        "SCENTHUNTER_CATALOG_DATABASE_URL": "sqlite:////secret/first.db",
        "SCENTHUNTER_DATABASE_URL": "sqlite:////secret/second.db",
    }) == "SCENTHUNTER_CATALOG_DATABASE_URL"
    assert configuration_source({
        "SCENTHUNTER_DATABASE_URL": "sqlite:////secret/second.db",
    }) == "SCENTHUNTER_DATABASE_URL"
    assert configuration_source({}) == "application_default"


def test_runtime_identity_uses_supplied_connection_and_masks_path(capsys, tmp_path):
    database = tmp_path / "private-catalog.sqlite3"
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            log_runtime_database_identity(
                connection,
                event_name="persistence",
                service_name="catalog-hydration/bplatz-phase2",
                config_source="SCENTHUNTER_CATALOG_DATABASE_URL",
                opened_at="2026-11-03T12:00:00.000+00:00",
            )
        output = capsys.readouterr().out
        assert "PHASE2_RUNTIME_DATABASE" in output
        assert "database_path=.../private-catalog.sqlite3" in output
        assert "database_id=sha256:" in output
        assert "connection_opened_at=2026-11-03T12:00:00.000+00:00" in output
        assert str(tmp_path) not in output
        assert "sqlite:///" not in output
        assert "password" not in output.lower()
    finally:
        engine.dispose()
