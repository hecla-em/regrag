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
    """What a request cost at its model's prices when it was recorded, which the daily spend
    cap sums. Left NULL on existing rows: they are priced at the time, not re-priced."""
    op.add_column("chat_requests", sa.Column("cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_requests", "cost_usd")
