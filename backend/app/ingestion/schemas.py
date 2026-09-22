"""Ingest tracking: one row per corpus fetch run."""

from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.schema import BaseSchema
from app.ingestion.enums import IngestRunStatus


class IngestRun(BaseSchema):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[IngestRunStatus]
    corpus_version: Mapped[str | None]
    completed_at: Mapped[datetime | None]
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """Per-stage counts and failures; NULL means the run died before a result existed."""
    chunk_count: Mapped[int | None]
    avg_chunk_chars: Mapped[float | None]
    """The corpus as the run left it, so BM25 reads its size and mean length instead of
    scanning for them; NULL on runs from before they were stamped."""
