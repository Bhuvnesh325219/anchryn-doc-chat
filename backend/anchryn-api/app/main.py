"""FastAPI application entry point.

Run with: uvicorn app.main:app --reload --port 8000
Interactive docs: http://localhost:8000/docs
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import ask, auth, documents
from app.config import get_settings
from app.db import engine
from app.services import embedding

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="Anchryn API",
    version="0.1.0",
    description="Answers questions from your documents, and cites the passage it used.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(ask.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, object]:
    """Liveness, plus enough detail to diagnose a misconfigured deployment.

    Deliberately returns 200 even when the database is unreachable. Hosted
    Postgres suspends when idle, and a health check that fails during a wakeup
    would have the platform restart a perfectly healthy service. The caller gets
    the database state as a field and can decide what it means.
    """
    database = "up"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — any failure means "not reachable"
        logger.warning("Health check could not reach the database: %s", exc)
        database = "down"

    return {
        "status": "UP",
        "database": database,
        "hf_configured": settings.hf_configured,
        "embedding_model": settings.embedding_model,
        # False until the first upload or search loads it. The first such
        # request is slow — it downloads the model — and this makes that
        # visible rather than looking like a hang.
        "embedding_model_loaded": embedding.is_loaded(),
        # Surfaced so a deployment running the development signing key is
        # visible rather than silently insecure.
        "auth_secret_is_default": settings.jwt_secret_is_default,
    }
