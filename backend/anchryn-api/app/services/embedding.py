"""Turning text into vectors, locally.

Embedding runs in-process via fastembed rather than through the Hugging Face
API. It is called constantly — once per chunk at ingest and once per question at
search — so putting it behind a rate-limited network call would make it the
first thing to break. fastembed uses ONNX rather than PyTorch, which keeps the
install around 50MB instead of 800MB and fits a small container.

Queries and passages go through separate functions even though, for
BAAI/bge-small-en-v1.5, fastembed currently treats them identically —
``query_embed`` is an alias for ``embed`` and applies no prefix. Prefixing BGE's
"Represent this sentence for searching relevant passages:" by hand was measured
and made separation marginally *worse*, so it is deliberately not done.

The seam is kept because it is model-dependent: e5-family models require
"query:" and "passage:" prefixes and lose real accuracy without them. Keeping
two functions means switching model is a change here, not at every call site.
"""

import logging
import threading

from fastembed import TextEmbedding

from app.config import get_settings
from app.models import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)

_model: TextEmbedding | None = None
_model_lock = threading.Lock()


class EmbeddingError(Exception):
    """Loading or running the embedding model failed."""


def get_model() -> TextEmbedding:
    """Load the model once, on first use.

    Loading downloads roughly 67MB the very first time and takes a few seconds,
    so the alternative — loading at startup — would mean the app cannot boot
    without network access. Paying it on the first request is the better trade,
    at the cost of that request being slow.
    """
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        # Checked again inside the lock: two concurrent first requests would
        # otherwise both load the model.
        if _model is not None:
            return _model

        settings = get_settings()
        logger.info("Loading embedding model %s", settings.embedding_model)
        try:
            model = TextEmbedding(model_name=settings.embedding_model)
        except Exception as exc:
            raise EmbeddingError(
                f"Could not load embedding model '{settings.embedding_model}': {exc}"
            ) from exc

        _assert_dimensions(model, settings.embedding_model)
        _model = model
        logger.info("Embedding model ready")
        return _model


def _assert_dimensions(model: TextEmbedding, model_name: str) -> None:
    """Fail loudly if the model's output does not match the database column.

    The vector column is a fixed 384 wide. A model with a different size would
    otherwise fail deep in an insert with a confusing dimension error, one chunk
    at a time, after the work of parsing was already done.
    """
    probe = next(iter(model.embed(["dimension probe"])))
    actual = len(probe)
    if actual != EMBEDDING_DIMENSIONS:
        raise EmbeddingError(
            f"Model '{model_name}' produces {actual}-dimensional vectors but the database "
            f"column is {EMBEDDING_DIMENSIONS}. Changing embedding model needs a migration "
            f"and a re-embed of every existing chunk."
        )


def is_loaded() -> bool:
    """Whether the model is in memory, for reporting on /api/health."""
    return _model is not None


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Embed document chunks. Order matches the input."""
    if not texts:
        return []
    model = get_model()
    try:
        return [vector.tolist() for vector in model.passage_embed(texts)]
    except Exception as exc:
        raise EmbeddingError(f"Embedding failed: {exc}") from exc


def embed_query(text: str) -> list[float]:
    """Embed a search query.

    Routed through query_embed so that a model which does distinguish the two
    gets the treatment it expects. For the current model this is the same
    computation as embed_passages — see the module docstring.
    """
    model = get_model()
    try:
        return next(iter(model.query_embed([text]))).tolist()
    except Exception as exc:
        raise EmbeddingError(f"Embedding failed: {exc}") from exc
