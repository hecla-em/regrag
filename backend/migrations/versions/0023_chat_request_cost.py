"""chat request cost

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-15 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """What a request cost, priced step by step at the model each step called, which the daily
    spend cap sums. Existing rows stay unpriced, and a request that called no model now
    records none rather than the configured one."""
    op.add_column("chat_requests", sa.Column("cost_usd", sa.Float(), nullable=True))
    op.alter_column("chat_requests", "model", nullable=True)
    op.add_column("chat_request_steps", sa.Column("cost_usd", sa.Float(), nullable=True))
    op.add_column("chat_request_steps", sa.Column("model", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_request_steps", "model")
    op.drop_column("chat_request_steps", "cost_usd")
    op.alter_column("chat_requests", "model", nullable=False)
    op.drop_column("chat_requests", "cost_usd")
