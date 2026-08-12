"""Settings that are easy to get wrong and silent when they are."""

from app.config import Settings


def settings_with(url: str) -> Settings:
    return Settings(database_url=url, _env_file=None)


def test_a_bare_postgres_url_gets_the_psycopg_driver():
    # Neon, Supabase and Render all hand out this form. Left as-is, SQLAlchemy
    # reaches for psycopg2 and fails with an unhelpful ImportError.
    assert settings_with(
        "postgresql://user:pw@ep-x.aws.neon.tech/neondb?sslmode=require"
    ).database_url.startswith("postgresql+psycopg://")

    assert settings_with("postgres://user:pw@host/db").database_url.startswith(
        "postgresql+psycopg://"
    )


def test_the_rest_of_the_url_is_untouched():
    result = settings_with("postgresql://user:pw@ep-x.aws.neon.tech/neondb?sslmode=require")

    assert result.database_url == (
        "postgresql+psycopg://user:pw@ep-x.aws.neon.tech/neondb?sslmode=require"
    )


def test_an_explicit_driver_is_left_alone():
    # Someone naming a driver deliberately must not have it rewritten.
    for url in (
        "postgresql+psycopg://user:pw@host/db",
        "postgresql+asyncpg://user:pw@host/db",
    ):
        assert settings_with(url).database_url == url
