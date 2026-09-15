"""The fetch stage's record of one downloaded document."""

from datetime import datetime

from sqlalchemy import ARRAY, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.schema import BaseSchema
from app.ingestion.schemas import IngestRun


class RawDocument(BaseSchema):
    """One source document as fetched: where it came from, which version, and its bytes.

    celex is the act discovery found and candidates the consolidations it offered; resolved_celex
    is the version EUR-Lex served, one of those candidates or the act itself. title is the act's
    official English title as discovery read it, NULL where CELLAR had none. No column names the
    stored object: its key is derived from celex, resolved_celex and sha256.
    """

    __tablename__ = "raw_documents"
    __table_args__ = (
        UniqueConstraint("ingest_run_id", "celex"),
        Index("ix_raw_documents_topic_run", "topic", "ingest_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ingest_run_id: Mapped[int] = mapped_column(ForeignKey("ingest_runs.id", ondelete="CASCADE"))
    source: Mapped[str]
    celex: Mapped[str]
    candidates: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    resolved_celex: Mapped[str]
    topic: Mapped[str]
    title: Mapped[str | None]
    sha256: Mapped[str]
    size_bytes: Mapped[int]
    fetched_at: Mapped[datetime]

    run: Mapped[IngestRun] = relationship()
