"""Finding the chunks most likely to answer a question.

Deliberately separate from any generation step. Retrieval quality determines the
ceiling on answer quality — if the right passage is not in these results, no
prompt can rescue the answer — so it is worth being able to inspect on its own.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document
from app.services.embedding import embed_query

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: uuid.UUID
    filename: str
    page_number: int
    char_start: int
    char_end: int
    text: str
    #: Cosine similarity, 1.0 being identical. Derived as 1 - cosine distance.
    similarity: float


def search(
    session: Session,
    user_id: uuid.UUID,
    question: str,
    top_k: int = 5,
    document_id: uuid.UUID | None = None,
) -> list[RetrievedChunk]:
    """Return the ``top_k`` chunks closest to ``question``, best first.

    ``user_id`` is required, not optional. This is the one query in the app that
    reaches across documents by design, so a forgotten filter here would surface
    another user's private text inside an answer — the worst possible leak, and
    a silent one. Making it a positional argument means it cannot be omitted.

    Chunks without an embedding are excluded rather than treated as distant —
    an unembedded chunk is not "far away", it is simply not searchable yet.
    """
    vector = embed_query(question)

    distance = Chunk.embedding.cosine_distance(vector)

    statement = (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.filename,
            Chunk.page_number,
            Chunk.char_start,
            Chunk.char_end,
            Chunk.text,
            distance.label("distance"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.user_id == user_id)
        .where(Chunk.embedding.is_not(None))
        # ORDER BY distance with a LIMIT is the shape the HNSW index can serve;
        # filtering on the distance instead would force a sequential scan.
        .order_by(distance)
        .limit(top_k)
    )

    if document_id is not None:
        statement = statement.where(Chunk.document_id == document_id)

    rows = session.execute(statement).all()

    results = [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            filename=row.filename,
            page_number=row.page_number,
            char_start=row.char_start,
            char_end=row.char_end,
            text=row.text,
            similarity=1.0 - float(row.distance),
        )
        for row in rows
    ]

    logger.debug(
        "Retrieved %d chunks for %r (best=%.3f)",
        len(results),
        question[:60],
        results[0].similarity if results else 0.0,
    )
    return results


def is_grounded(results: list[RetrievedChunk], threshold: float) -> bool:
    """Whether the best match is close enough to answer from.

    The whole point of the project rests on this being allowed to be False: an
    answer with no supporting passage should be a refusal, not a guess.
    """
    return bool(results) and results[0].similarity >= threshold
