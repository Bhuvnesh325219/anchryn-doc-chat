"""Application settings, read once from the environment.

Values come from real environment variables in production and from .env during
development. pydantic-settings matches case-insensitively, so DATABASE_URL in
the environment fills database_url here.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    #: Accepts the connection string a provider actually gives you. Neon,
    #: Supabase and Render all hand out ``postgresql://``, which makes SQLAlchemy
    #: reach for psycopg2 — not installed here. The driver is filled in below
    #: rather than making everyone remember to edit the URL by hand.
    database_url: str

    #: Blank until a Hugging Face token is supplied. The app still starts, so the
    #: UI can say what is missing rather than failing at import time.
    #:
    #: The token must be allowed to call Inference Providers — a fine-grained
    #: token without that permission returns 403, not 401.
    hf_token: str = ""

    hf_model: str = "Qwen/Qwen2.5-7B-Instruct"
    hf_base_url: str = "https://router.huggingface.co/v1"
    hf_timeout_seconds: float = 60.0

    #: Path to a CA bundle. Needed behind a TLS-inspecting corporate proxy,
    #: whose root is trusted by the OS but absent from certifi's bundle.
    #: Empty means use the default bundle.
    ca_bundle: str = ""

    #: Python 3.13 turned on VERIFY_X509_STRICT by default, which enforces
    #: RFC 5280 extensions that some corporate CAs omit — notably the Authority
    #: Key Identifier. Setting this False clears that one flag; certificate
    #: verification itself stays fully on. Leave it True anywhere without such
    #: a proxy — production included.
    tls_strict: bool = True

    #: Changing this almost certainly changes the vector dimension, which means a
    #: migration and re-embedding every chunk. See EMBEDDING_DIMENSIONS in models.
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    cors_allowed_origins: str = "http://localhost:4200"

    #: Signing key for access tokens. The default is for local development only;
    #: it is checked at startup and refused in production, because anyone who
    #: knows it can mint a token for any account.
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_expiry_minutes: int = 60 * 24 * 7  # a week

    @property
    def jwt_secret_is_default(self) -> bool:
        return self.jwt_secret == "dev-only-insecure-secret-change-me"

    #: Minimum cosine similarity for the best match to count as an answer.
    #:
    #: Measured on the sample corpus: questions the documents answered scored
    #: 0.62-0.79, one they did not scored 0.37. 0.45 sits in that gap while
    #: leaning permissive — retrieving a weak passage and letting the answering
    #: step decline is recoverable; refusing outright is not.
    #:
    #: Corpus-specific. Worth re-measuring on your own documents rather than
    #: trusting this number.
    grounding_threshold: float = 0.45

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, value: str) -> str:
        """Point a bare postgres URL at psycopg 3.

        Left alone if a driver is already named, so ``postgresql+asyncpg://`` or
        anything else deliberate is not silently rewritten.
        """
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @property
    def cors_origins(self) -> list[str]:
        """Comma-separated in the environment, a list here."""
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def hf_configured(self) -> bool:
        return bool(self.hf_token.strip())


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is parsed once rather than per request."""
    return Settings()
