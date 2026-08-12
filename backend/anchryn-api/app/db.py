"""Database engine, session factory and the declarative base.

Kept separate from models.py so that Alembic can import ``Base`` without
pulling in anything else, and so models.py stays purely about tables.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    """Every model inherits from this, which is how Alembic discovers tables
    through ``Base.metadata``."""


# pool_pre_ping checks a connection is alive before handing it out. Hosted
# Postgres (Neon and friends) suspends when idle and silently drops pooled
# connections; without this the first query after a quiet spell fails.
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    with SessionLocal() as session:
        yield session
