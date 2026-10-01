from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

database_url = os.environ.get("CLINICAL_DATABASE_URL")
if not database_url:
    raise RuntimeError("CLINICAL_DATABASE_URL is required for migrations")


def run_migrations_offline() -> None:
    context.configure(url=database_url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    sqlalchemy_url = (database_url.replace("postgresql://", "postgresql+psycopg://", 1)
                      if database_url.startswith("postgresql://") else database_url)
    engine = create_engine(sqlalchemy_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
