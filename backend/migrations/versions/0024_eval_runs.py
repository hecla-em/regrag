"""eval runs

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-17 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """One row per stored eval run: the commit and models it scored, and its metrics."""
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("git_commit", sa.String(), nullable=True),
        sa.Column("git_dirty", sa.Boolean(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("judge_model", sa.String(), nullable=True),
        sa.Column("dataset_sha", sa.String(), nullable=False),
        sa.Column("corpus_version", sa.String(), nullable=True),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("judged", sa.Boolean(), nullable=False),
        sa.Column("selection", postgresql.JSONB(), nullable=False),
        sa.Column("stale_cases", postgresql.JSONB(), nullable=False),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("eval_runs")
