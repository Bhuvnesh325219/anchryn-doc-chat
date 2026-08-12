"""Retrieval endpoint.

No language model is involved. This returns the passages a question matched,
with their scores, so retrieval can be judged on its own — before generation
exists to be blamed for a bad answer.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.deps import current_user
from app.models import User
from app.schemas import AnswerResponse, AskRequest, AskResponse, Citation
from app.services.embedding import EmbeddingError
from app.services.generation import (
    GenerationError,
    GenerationRateLimitError,
    answer_from_chunks,
)
from app.services.retrieval import RetrievedChunk, is_grounded, search

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["ask"])


@router.post("/answer", response_model=AnswerResponse)
def answer(
    request: AskRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> AnswerResponse:
    """Retrieve, then answer strictly from what was retrieved.

    Returns the passages alongside the answer so the reasoning can be checked —
    including on a refusal, where seeing the weak scores is the explanation.
    """
    settings = get_settings()

    try:
        results = search(
            session,
            user.id,
            question=request.question,
            top_k=request.top_k,
            document_id=request.document_id,
        )
    except EmbeddingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    threshold = settings.grounding_threshold
    grounded = is_grounded(results, threshold)

    try:
        generated = answer_from_chunks(request.question, results, grounded)
    except GenerationRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    return AnswerResponse(
        question=request.question,
        answer=generated.text,
        grounded=generated.grounded,
        cited_chunk_ids=generated.cited_chunk_ids,
        results=[_to_citation(result) for result in results],
        best_similarity=round(results[0].similarity, 4) if results else 0.0,
        threshold=threshold,
        model=generated.model,
    )


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> AskResponse:
    settings = get_settings()

    try:
        results = search(
            session,
            user.id,
            question=request.question,
            top_k=request.top_k,
            document_id=request.document_id,
        )
    except EmbeddingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    threshold = settings.grounding_threshold
    best = results[0].similarity if results else 0.0

    # Results are returned even when ungrounded, deliberately: seeing what *did*
    # come back and how weakly it scored is what makes a refusal debuggable.
    return AskResponse(
        question=request.question,
        results=[_to_citation(result) for result in results],
        best_similarity=round(best, 4),
        grounded=is_grounded(results, threshold),
        threshold=threshold,
    )


def _to_citation(result: RetrievedChunk) -> Citation:
    return Citation(
        chunk_id=result.chunk_id,
        document_id=result.document_id,
        filename=result.filename,
        page_number=result.page_number,
        char_start=result.char_start,
        char_end=result.char_end,
        text=result.text,
        similarity=round(result.similarity, 4),
    )
