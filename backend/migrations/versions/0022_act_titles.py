"""act titles

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The act's official title, read from CELLAR at discovery and copied onto its chunks.
    Left NULL here: the next ingest run fills both, reusing every stored document."""
    op.add_column("raw_documents", sa.Column("title", sa.String(), nullable=True))
    op.add_column("document_chunks", sa.Column("act_title", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "act_title")
    op.drop_column("raw_documents", "title")
