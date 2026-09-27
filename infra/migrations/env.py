"""Alembic environment for the PostgreSQL tenant schema."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text
from wso_core.db import Base
from wso_core.migration import migration_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url(*, offline: bool) -> str:
    return migration_database_url(
        config.get_main_option("sqlalchemy.url"),
        os.getenv("WSO_MIGRATION_DATABASE_URL"),
        offline=offline,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(offline=True),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url(offline=False)
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.begin() as connection:
        role = connection.execute(text("SELECT current_user")).scalar_one()
        if role in ("wso_app", "wso_identity_bootstrap"):
            raise PermissionError("migrations require a separate DDL role")
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        # Alembic creates its version table outside revision code. Keep it owned
        # by the DDL role so later revisions can run without an admin login.
        if (
            connection.execute(
                text("SELECT to_regrole('wso_migrator') IS NOT NULL")
            ).scalar_one()
            and connection.execute(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            ).scalar_one()
        ):
            connection.execute(
                text("ALTER TABLE public.alembic_version OWNER TO wso_migrator")
            )
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
