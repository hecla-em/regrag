"""Ingest tracking: one row per corpus fetch run."""

from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.schema import BaseSchema
from app.ingestion.enums import IngestRunStatus


class IngestRun(BaseSchema):
    """One ingest run and the corpus it left behind.

    result: per-stage counts and failures, NULL if the run died before it had one.
    chunk_count, avg_chunk_chars: the corpus size and mean chunk length BM25 reads,
        NULL on runs from before they were stamped.
    """

    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[IngestRunStatus]
    corpus_version: Mapped[str | None]
    completed_at: Mapped[datetime | None]
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    chunk_count: Mapped[int | None]
    avg_chunk_chars: Mapped[float | None]
