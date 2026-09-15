"""Persisted chunks: one row per retrievable unit of a regulation."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Computed, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import EMBED_DIMENSIONS
from app.core.db.schema import BaseSchema
from app.ingestion.enums import SectionKind
from app.ingestion.schemas import IngestRun

SEARCH_VECTOR_SQL = (
    """setweight(to_tsvector('english', citation || ' ' || coalesce(title, '')), 'A')"""
    """ || setweight(to_tsvector('english', "text"), 'B')"""
)


class DocumentChunk(BaseSchema):
    """One retrievable unit of a regulation, content-addressed so it survives re-runs."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("celex", "content_hash", "occurrence"),
        Index("ix_document_chunks_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_document_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_document_chunks_unembedded_cursor",
            "celex",
            "id",
            postgresql_where=text("embedding IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ingest_run_id: Mapped[int] = mapped_column(ForeignKey("ingest_runs.id", ondelete="CASCADE"))

    # Identity: hash and occurrence match a chunk to its stored row across re-runs.
    celex: Mapped[str]
    topic: Mapped[str]
    content_hash: Mapped[str]
    occurrence: Mapped[int]

    # Origin: the act's official title, copied from its document so a hit needs no join.
    act_title: Mapped[str | None]

    # Drift: fingerprint of the metadata columns; NULL predates the column and reads as drifted.
    metadata_hash: Mapped[str | None]

    # Locator: where the chunk sits in the document, and how it cites itself.
    kind: Mapped[SectionKind]
    article: Mapped[str | None]
    annex: Mapped[str | None]
    title: Mapped[str | None]
    paragraph: Mapped[str | None]
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(String))
    citation: Mapped[str]

    # Sizing: which piece of an over-long section this is.
    part: Mapped[int]
    parts: Mapped[int]

    # Placement: the chunk's ordinal in the document, the only sort key an annex has.
    position: Mapped[int]

    # Search: the text, the points it lists, the acts it cites, and the two indexes queried over it.
    text: Mapped[str]
    points: Mapped[list[str]] = mapped_column(ARRAY(String))
    references: Mapped[list[dict]] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIMENSIONS))
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR_SQL, persisted=True)
    )

    run: Mapped[IngestRun] = relationship()
