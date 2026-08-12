"""The embedding model itself.

These load the real model rather than mocking it. A mocked embedder would prove
the plumbing works while saying nothing about whether the vectors are
meaningful — which is the only property that matters. The first run downloads
roughly 67MB; afterwards it is cached.
"""

import math

import pytest

from app.models import EMBEDDING_DIMENSIONS
from app.services.embedding import embed_passages, embed_query, get_model


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


def test_vectors_match_the_database_column_width():
    # A mismatch here would fail deep inside an insert, one chunk at a time,
    # after all the parsing work was already done.
    vector = embed_query("how are chunks stored?")

    assert len(vector) == EMBEDDING_DIMENSIONS


def test_passage_embedding_preserves_order():
    vectors = embed_passages(["first text about cats", "second text about databases"])

    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIMENSIONS for v in vectors)
    assert vectors[0] != vectors[1]


def test_embedding_nothing_returns_nothing():
    # Guards the ingest path for a PDF that produced no chunks.
    assert embed_passages([]) == []


def test_related_text_scores_higher_than_unrelated_text():
    """The property the whole retrieval step depends on.

    If this fails, embeddings are being produced but carry no useful meaning,
    and every downstream answer would be wrong for reasons no prompt can fix.
    """
    query = embed_query("How do I reset my password?")

    relevant, irrelevant = embed_passages(
        [
            "To change your password, open account settings and choose Reset Password.",
            "The Cretaceous period ended about sixty-six million years ago.",
        ]
    )

    assert cosine(query, relevant) > cosine(query, irrelevant)


def test_paraphrases_score_close_together():
    a, b, c = embed_passages(
        [
            "The service returns an error when the quota is exceeded.",
            "When you go over the limit, the API responds with an error.",
            "Sourdough needs a starter and a long proof.",
        ]
    )

    assert cosine(a, b) > cosine(a, c)


def test_the_query_path_separates_relevant_from_irrelevant():
    """Whatever the query path does internally, it must rank correctly.

    Written as a behaviour check rather than asserting a particular internal
    treatment: fastembed's query_embed is currently an alias for embed on this
    model and applies no prefix, but that is an implementation detail that may
    change, and other models (the e5 family) genuinely do differ. What must hold
    either way is that a question ranks the answering passage above an unrelated
    one, by a clear margin.
    """
    query = embed_query("how do I reset my password")

    relevant, irrelevant = embed_passages(
        [
            "To change your password, open account settings and choose Reset Password.",
            "The Cretaceous period ended about sixty-six million years ago.",
        ]
    )

    assert cosine(query, relevant) - cosine(query, irrelevant) > 0.2


@pytest.mark.parametrize("text", ["", "   "])
def test_blank_text_still_produces_a_vector(text):
    # Not useful, but it must not raise — a chunk of whitespace should never
    # take down an ingest.
    assert len(embed_passages([text])[0]) == EMBEDDING_DIMENSIONS


def test_model_is_loaded_once():
    assert get_model() is get_model()
