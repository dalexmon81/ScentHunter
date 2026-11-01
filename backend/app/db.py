import os
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

def database_url() -> str:
    value = os.environ.get("SCENTHUNTER_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError("Set SCENTHUNTER_DATABASE_URL to the PostgreSQL connection URL")
    value = value.strip()
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value[len("postgres://"):]
    elif value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    if not value.startswith("postgresql+psycopg://"):
        raise RuntimeError("SCENTHUNTER_DATABASE_URL must point to PostgreSQL via psycopg")
    return value

def make_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True, pool_recycle=1800)

def make_session_factory():
    return sessionmaker(bind=make_engine(), expire_on_commit=False)
