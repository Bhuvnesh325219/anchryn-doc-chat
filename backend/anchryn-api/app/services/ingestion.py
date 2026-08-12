"""Turning an uploaded PDF into stored pages and chunks.

Runs synchronously: parsing a PDF is fast, and doing it inline keeps the upload
endpoint honest — it either worked or it did not. Embedding, added next, is the
slow part and is where a background job starts to earn its keep.

Nothing is written until parsing succeeds. An earlier version created the
document row first and marked it FAILED on error, which left a row behind for
every rejected upload — rows the user could see in the list but do nothing
about. Recording a failure only makes sense once ingestion is asynchronous and
the caller is no longer holding the error in their hand.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document, DocumentStatus, Page
from app.services.chunking import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP_CHARS, chunk_pages
from app.services.embedding import embed_passages
from app.services.pdf import extract_pages

logger = logging.getLogger(__name__)


def ingest_pdf(
    session: Session,
    user_id: uuid.UUID,
    filename: str,
    data: bytes,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> Document:
    """Parse, chunk and store a PDF.

    Raises PdfExtractionError before writing anything if the file cannot be read.
    """
    # Parse first: a failure here must leave the database untouched.
    pages = extract_pages(data)
    chunks = chunk_pages(pages, max_chars=max_chars, overlap_chars=overlap_chars)

    document = Document(
        user_id=user_id,
        filename=filename,
        size_bytes=len(data),
        page_count=len(pages),
        chunk_count=len(chunks),
        # Not READY: the chunks exist but have no embeddings, so the document
        # cannot be searched yet. Saying READY here would be a lie the next
        # step has to undo.
        status=DocumentStatus.PENDING,
    )
    session.add(document)
    session.flush()  # assigns the id that pages and chunks reference

    # The page text the chunker just sliced. A chunk's offsets are meaningless
    # without the exact string they index into.
    session.add_all(
        Page(document_id=document.id, page_number=number, text=text)
        for number, text in enumerate(pages, start=1)
    )

    # Embedding is the slow part. It runs inline because a document that is not
    # searchable yet is of no use to anyone, and an upload that silently returns
    # before the work is done invites the user to search too early. If ingest
    # times start to bite on large PDFs, this is the piece to move to a job.
    vectors = embed_passages([chunk.text for chunk in chunks])

    session.add_all(
        Chunk(
            document_id=document.id,
            ordinal=ordinal,
            page_number=chunk.page_number,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            text=chunk.text,
            embedding=vector,
        )
        for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
    )

    document.status = DocumentStatus.READY

    session.commit()
    session.refresh(document)

    logger.info(
        "Ingested %s: %d pages, %d chunks", filename, document.page_count, document.chunk_count
    )
    return document


def embed_missing_chunks(session: Session, document: Document) -> int:
    """Embed any chunks of a document that have no vector yet.

    Needed for documents ingested before embedding existed, and as a repair path
    if embedding failed partway. Returns how many were filled in.
    """
    pending = list(
        session.scalars(
            select(Chunk)
            .where(Chunk.document_id == document.id, Chunk.embedding.is_(None))
            .order_by(Chunk.ordinal)
        ).all()
    )
    if not pending:
        if document.status != DocumentStatus.READY and document.chunk_count > 0:
            document.status = DocumentStatus.READY
            session.commit()
        return 0

    vectors = embed_passages([chunk.text for chunk in pending])
    for chunk, vector in zip(pending, vectors, strict=True):
        chunk.embedding = vector

    document.status = DocumentStatus.READY
    session.commit()

    logger.info("Embedded %d outstanding chunks for %s", len(pending), document.filename)
    return len(pending)
