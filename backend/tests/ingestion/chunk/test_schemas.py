"""Roundtrip tests for the document chunks table."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBED_DIMENSIONS

pytestmark = pytest.mark.anyio


async def test_the_migrated_column_is_as_wide_as_the_embeddings_we_ask_for(
    db_session: AsyncSession,
):
    """A constant wider than the column embeds a whole run the database then refuses to store."""
    column_type = await db_session.scalar(
        text(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute"
            " WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
        )
    )

    assert column_type == f"vector({EMBED_DIMENSIONS})"
