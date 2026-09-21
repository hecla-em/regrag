"""What the chunk tests share with the script that regenerates their snapshots."""

from typing import Any

from app.ingestion.chunk.tree import chunk_document
from app.ingestion.parse.models import ParsedDocument

SNAPSHOT_MAX_CHARS = 2000
"""Pinned apart from config.MAX_CHARS, so tuning the chunk size does not churn the snapshots."""


def snapshot_chunks(document: ParsedDocument) -> list[dict[str, Any]]:
    """A parsed act's chunks as its snapshot file holds them."""
    chunks = chunk_document(document, max_chars=SNAPSHOT_MAX_CHARS)
    return [chunk.model_dump(mode="json") for chunk in chunks]
