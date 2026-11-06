from alembic import context
from app.db import database_url, make_engine
from app.models import Base
from sqlalchemy.engine import make_url

config = context.config
url = database_url()
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=make_url(url).get_backend_name() == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = make_engine()
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=connection.dialect.name == "sqlite",
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
