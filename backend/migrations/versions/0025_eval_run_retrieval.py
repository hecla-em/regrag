"""eval run retrieval

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-17 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Whether a run retrieved; every run stored before the column did."""
    op.add_column(
        "eval_runs",
        sa.Column("retrieval", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("eval_runs", "retrieval")
