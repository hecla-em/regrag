"""raw document formex

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The stored Formex zip, NULL on existing rows: the next ingest re-fetches any version
    that needs one."""
    op.add_column("raw_documents", sa.Column("formex_sha256", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("raw_documents", "formex_sha256")
