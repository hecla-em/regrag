"""formula renderings

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-22 20:00:00.000000

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
    """Parse's formula cache, filled by the first ingest after deploy."""
    op.create_table(
        "formula_renderings",
        sa.Column("image_hash", sa.String(length=16), nullable=False),
        sa.Column("latex", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("image_hash"),
    )


def downgrade() -> None:
    op.drop_table("formula_renderings")
