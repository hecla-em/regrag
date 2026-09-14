"""document chunk points

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-10 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


POINT_LINE = r"^\(([0-9a-z]+)\) "
"""The chunker's POINT_LINE, as Postgres reads it; 'n' makes ^ match at every line."""


def upgrade() -> None:
    """The points a chunk's text opens lines with, so a citation by point is a lookup rather
    than a regex over the text; filled here so a follow works before the next ingest run."""
    op.add_column(
        "document_chunks",
        sa.Column("points", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"),
    )
    op.execute(
        "UPDATE document_chunks SET points = ARRAY("
        f"SELECT m[1] FROM regexp_matches(\"text\", '{POINT_LINE}', 'gn') AS m)::varchar[]"
    )
    op.alter_column("document_chunks", "points", server_default=None)


def downgrade() -> None:
    op.drop_column("document_chunks", "points")
