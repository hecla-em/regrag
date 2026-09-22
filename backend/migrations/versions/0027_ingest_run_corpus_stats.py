"""ingest run corpus stats

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-22 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Corpus size and mean chunk length as each run left them, read by BM25.

    Not backfilled: the ingest run after deploy stamps them, and until then the text leg
    finds nothing rather than scoring against numbers no run recorded.
    """
    op.add_column("ingest_runs", sa.Column("chunk_count", sa.Integer(), nullable=True))
    op.add_column("ingest_runs", sa.Column("avg_chunk_chars", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("ingest_runs", "avg_chunk_chars")
    op.drop_column("ingest_runs", "chunk_count")
