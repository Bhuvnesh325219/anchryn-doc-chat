"""Tables for uploaded documents and their embedded chunks."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# bge-small-en-v1.5 emits 384-dimensional vectors. Switching embedding model
# almost always changes this, and that means a migration plus re-embedding every
# existing chunk — the stored vectors are not comparable across models.
EMBEDDING_DIMENSIONS = 384


class DocumentStatus:
    """Ingestion is multi-step and can fail partway, so the state is explicit.

    Plain strings rather than a database enum: adding a value to a Postgres enum
    needs its own migration, and this list will grow.
    """

    PENDING = "PENDING"
    PARSING = "PARSING"
    EMBEDDING = "EMBEDDING"
    READY = "READY"
    FAILED = "FAILED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    #: Stored lowercased so "A@b.com" and "a@b.com" cannot become two accounts.
    #: Uniqueness is enforced by the database, not only by a pre-insert check —
    #: two simultaneous registrations would otherwise both pass that check.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)

    #: Argon2 hash. The plaintext password is never stored or logged.
    password_hash: Mapped[str] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    #: Every document belongs to exactly one user. Not nullable on purpose: an
    #: ownerless document would be invisible to its uploader and reachable by
    #: any query that forgot to filter.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(20), default=DocumentStatus.PENDING, index=True)
    #: Why ingestion failed, shown to the user rather than buried in a log.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        # Let Postgres cascade the delete rather than loading every chunk into
        # memory first; a large PDF can be thousands of rows.
        passive_deletes=True,
    )

    pages: Mapped[list["Page"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    owner: Mapped["User"] = relationship(back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document {self.filename} ({self.status})>"


class Page(Base):
    """The extracted text of one page, exactly as the chunker saw it.

    Without this a chunk's char_start/char_end index into nothing — the offsets
    would be dead data. Keeping the page text means a citation can be shown
    highlighted in its original context, which is the whole point of the project.
    """

    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    #: 1-based, matching Chunk.page_number.
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    document: Mapped["Document"] = relationship(back_populates="pages")

    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_pages_document_number"),
    )

    def __repr__(self) -> str:
        return f"<Page doc={self.document_id} p{self.page_number}>"


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )

    #: Position within the document, so ordering never depends on insert order.
    ordinal: Mapped[int] = mapped_column(Integer)

    #: 1-based page this chunk came from, and where it sits within that page's
    #: text. Together these are what let a citation highlight the exact passage
    #: rather than just naming the file.
    page_number: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)

    text: Mapped[str] = mapped_column(Text)

    #: Nullable because chunks are stored during parsing and embedded afterwards.
    #: A null here means ingestion did not finish.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        # Guards against a re-ingest writing a document's chunks twice.
        UniqueConstraint("document_id", "ordinal", name="uq_chunks_document_ordinal"),
        # HNSW with cosine distance: bge embeddings are normalised, so cosine is
        # the matching operator class. Without this index pgvector falls back to
        # a sequential scan over every chunk.
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<Chunk doc={self.document_id} #{self.ordinal} p{self.page_number}>"
