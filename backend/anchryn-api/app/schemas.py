"""Request and response shapes for the API.

Separate from models.py so the database schema and the wire format can move
independently — the vector column, for one, never leaves the server.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Credentials(BaseModel):
    email: EmailStr
    #: Argon2 has no length ceiling, so the maximum is only about refusing
    #: absurd input. The minimum is a floor, not a policy — length matters far
    #: more than character-class rules.
    password: str = Field(min_length=8, max_length=256)

    def normalised_email(self) -> str:
        return self.email.strip().lower()


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile


class DocumentSummary(BaseModel):
    """A document without its chunks."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    size_bytes: int
    page_count: int
    chunk_count: int
    status: str
    error: str | None
    created_at: datetime
    updated_at: datetime


class ChunkSummary(BaseModel):
    """One chunk. The embedding itself is never returned — it is 384 floats of
    no use to a client, and it would dominate the payload."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ordinal: int
    page_number: int
    char_start: int
    char_end: int
    text: str
    embedded: bool = Field(
        description="Whether this chunk has an embedding yet. False means ingestion did not finish."
    )


class PageText(BaseModel):
    """A page's extracted text, so a client can highlight a chunk's character
    range in its original context."""

    page_number: int
    text: str


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    #: Restrict the search to one document. None searches everything.
    document_id: uuid.UUID | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class Citation(BaseModel):
    """Where a retrieved passage came from.

    char_start/char_end index into GET /api/documents/{id}/pages/{page_number},
    so a client can slice that text and highlight exactly this passage.
    """

    chunk_id: int
    document_id: uuid.UUID
    filename: str
    page_number: int
    char_start: int
    char_end: int
    text: str
    similarity: float


class AskResponse(BaseModel):
    question: str
    results: list[Citation]
    #: Similarity of the best match, or 0.0 when nothing was found.
    best_similarity: float
    #: Whether the best match clears the threshold. False means the documents do
    #: not cover this question and the honest answer is to say so.
    grounded: bool
    threshold: float


class AnswerResponse(BaseModel):
    """A grounded answer, plus everything needed to check it.

    The retrieved passages and their scores are always returned, including when
    the answer is a refusal — that is what makes the decision inspectable rather
    than something you have to take on trust.
    """

    question: str
    answer: str
    grounded: bool
    #: Chunk ids the answer actually cited, a subset of ``results``.
    cited_chunk_ids: list[int]
    results: list[Citation]
    best_similarity: float
    threshold: float
    model: str


class ErrorResponse(BaseModel):
    error: str
    message: str
