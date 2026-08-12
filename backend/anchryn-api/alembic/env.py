from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from app.config import get_settings
from app.db import Base

# Importing the models module has no direct use here, but it is what registers
# every table on Base.metadata. Without it autogenerate sees nothing and
# cheerfully writes an empty migration.
from app import models  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# The URL is deliberately absent from alembic.ini so no credentials sit in a
# committed file.
#
# It comes from Settings rather than straight out of the environment, so that
# migrations get the same normalisation the application does. Reading
# DATABASE_URL directly meant a provider's bare postgresql:// URL reached
# SQLAlchemy unchanged, which sent it looking for psycopg2 and broke every
# deploy at the migration step.
#
# Percent signs are doubled because Alembic parses this value through
# configparser, which treats % as interpolation — a password containing one
# would otherwise raise at startup.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# What autogenerate diffs the live database against.
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
