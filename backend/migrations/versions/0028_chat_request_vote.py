"""chat request vote

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-22 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The reader's vote on the answer, and when it was cast. A vote names its answer by
    request_id, so that gains the unique index the lookup needs."""
    op.add_column(
        "chat_requests",
        sa.Column("vote", sa.Enum("up", "down", name="vote", native_enum=False), nullable=True),
    )
    op.add_column("chat_requests", sa.Column("voted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_chat_requests_request_id", "chat_requests", ["request_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_chat_requests_request_id", table_name="chat_requests")
    op.drop_column("chat_requests", "voted_at")
    op.drop_column("chat_requests", "vote")
