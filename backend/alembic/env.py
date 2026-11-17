from alembic import context
from app.db import database_url, make_engine
from app.models import Base

config = context.config
configured_url = database_url()
config.set_main_option("sqlalchemy.url", configured_url.replace("%", "%%"))
target_metadata = Base.metadata

def _configure(connection=None, url=None):
    dialect = connection.dialect.name if connection is not None else "sqlite"
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        literal_binds=connection is None,
        dialect_opts={"paramstyle": "named"} if connection is None else {},
        compare_type=True,
        render_as_batch=(dialect == "sqlite"),
    )


def run_migrations_offline():
    from sqlalchemy.engine import make_url
    parsed = make_url(configured_url)
    context.configure(
        url=configured_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=(parsed.get_backend_name() == "sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = make_engine()
    try:
        with connectable.connect() as connection:
            sqlite_foreign_keys_disabled = connection.dialect.name == "sqlite"
            if sqlite_foreign_keys_disabled:
                # Alembic batch migrations rebuild tables. SQLite refuses to
                # DROP a referenced parent table while FK enforcement is ON.
                # Toggle it only outside a transaction, then validate every
                # relationship before allowing the migration command to finish.
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.commit()
            try:
                _configure(connection=connection)
                with context.begin_transaction():
                    context.run_migrations()
            except Exception:
                if connection.in_transaction():
                    connection.rollback()
                raise
            finally:
                if sqlite_foreign_keys_disabled:
                    if connection.in_transaction():
                        connection.rollback()
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                    connection.commit()
            if sqlite_foreign_keys_disabled:
                violations = connection.exec_driver_sql(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                if violations:
                    raise RuntimeError(
                        "SQLite migration left foreign-key violations: "
                        + repr(violations[:10])
                    )
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
