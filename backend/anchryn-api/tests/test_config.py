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


def cors_settings(value: str) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/d", cors_allowed_origins=value,
                    _env_file=None)


def test_a_trailing_slash_does_not_break_cors():
    # Browsers send the origin without one, so a configured trailing slash
    # matches nothing — and the symptom looks like anything but a slash.
    assert cors_settings("https://app.vercel.app/").cors_origins == ["https://app.vercel.app"]


def test_several_origins_are_split_and_trimmed():
    result = cors_settings(" http://localhost:4200 , https://app.vercel.app/ ").cors_origins

    assert result == ["http://localhost:4200", "https://app.vercel.app"]


def test_empty_entries_are_dropped():
    assert cors_settings("https://a.com,,").cors_origins == ["https://a.com"]
