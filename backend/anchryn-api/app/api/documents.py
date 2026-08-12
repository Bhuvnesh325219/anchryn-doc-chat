"""Upload, list, inspect and delete documents.

Every route here takes ``current_user`` and filters by ``user.id``. There is no
"fetch by id" that does not also check ownership: ``_require_document`` is the
only way a document is loaded, and it requires an owner. A document belonging to
someone else is reported as 404, not 403 — a 403 would confirm that the id
exists, which is itself a leak.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user
from app.models import Chunk, Document, Page, User
from app.schemas import ChunkSummary, DocumentSummary, PageText
from app.services.embedding import EmbeddingError
from app.services.ingestion import embed_missing_chunks, ingest_pdf
from app.services.pdf import PdfExtractionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

#: Generous for documentation, small enough that a stray upload cannot exhaust
#: memory — the whole file is read before parsing.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("", response_model=DocumentSummary, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Document:
    filename = file.filename or "upload.pdf"

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported.",
        )

    data = await file.read()

    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file is empty."
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.",
        )

    try:
        return ingest_pdf(session, user.id, filename, data)
    except PdfExtractionError as exc:
        # The file arrived intact but we cannot use it — that is 422, not 400,
        # and the message from the parser is already written for the user.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except EmbeddingError as exc:
        # Nothing wrong with the upload — the model could not be loaded or run.
        # 503 rather than 500: worth retrying once the model is available.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get("", response_model=list[DocumentSummary])
def list_documents(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[Document]:
    return list(
        session.scalars(
            select(Document)
            .where(Document.user_id == user.id)
            .order_by(Document.created_at.desc())
        ).all()
    )


@router.get("/{document_id}", response_model=DocumentSummary)
def get_document(
    document_id: uuid.UUID,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Document:
    return _require_document(session, user, document_id)


@router.get("/{document_id}/chunks", response_model=list[ChunkSummary])
def list_chunks(
    document_id: uuid.UUID,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[ChunkSummary]:
    """Every chunk of a document, in order.

    Mainly a debugging window: when a later answer is wrong, the first question
    is always whether the chunks themselves are sensible.
    """
    _require_document(session, user, document_id)

    chunks = session.scalars(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ordinal)
    ).all()

    return [
        ChunkSummary(
            id=chunk.id,
            ordinal=chunk.ordinal,
            page_number=chunk.page_number,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            text=chunk.text,
            embedded=chunk.embedding is not None,
        )
        for chunk in chunks
    ]


@router.get("/{document_id}/pages/{page_number}", response_model=PageText)
def get_page(
    document_id: uuid.UUID,
    page_number: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> PageText:
    """The extracted text of one page.

    This is what a chunk's char_start/char_end index into, so a client can slice
    the same range and show the cited passage highlighted in context.
    """
    _require_document(session, user, document_id)

    page = session.scalar(
        select(Page).where(Page.document_id == document_id, Page.page_number == page_number)
    )
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document has no page {page_number}",
        )
    return PageText(page_number=page.page_number, text=page.text)


@router.post("/{document_id}/embed", response_model=DocumentSummary)
def embed_document(
    document_id: uuid.UUID,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Document:
    """Fill in any missing embeddings for a document.

    A repair path rather than part of the normal flow — upload embeds as it goes.
    """
    document = _require_document(session, user, document_id)
    try:
        embedded = embed_missing_chunks(session, document)
    except EmbeddingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    logger.info("Backfilled %d embeddings for %s", embedded, document.filename)
    session.refresh(document)
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> None:
    document = _require_document(session, user, document_id)
    # Chunks and pages go with it via ON DELETE CASCADE.
    session.delete(document)
    session.commit()


def _require_document(session: Session, user: User, document_id: uuid.UUID) -> Document:
    """Load a document, or 404.

    Ownership is part of the lookup rather than a separate check afterwards, so
    there is no path that fetches a document without it.
    """
    document = session.scalar(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    if document is None:
        # Deliberately the same response for "does not exist" and "belongs to
        # someone else". A 403 would confirm the id is real.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No document with id {document_id}",
        )
    return document
