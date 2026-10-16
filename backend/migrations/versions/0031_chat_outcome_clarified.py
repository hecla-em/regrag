"""chat outcome clarified

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OUTCOMES = ("done", "cached", "refused", "error", "aborted")


def outcome_type(*outcomes: str) -> sa.Enum:
    return sa.Enum(*outcomes, name="chatoutcome", native_enum=False)


def upgrade() -> None:
    """Widen the outcome column for 'clarified', longer than the seven characters it held."""
    op.alter_column(
        "chat_requests",
        "outcome",
        existing_type=outcome_type(*OUTCOMES),
        type_=outcome_type(*OUTCOMES, "clarified"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "chat_requests",
        "outcome",
        existing_type=outcome_type(*OUTCOMES, "clarified"),
        type_=outcome_type(*OUTCOMES),
        existing_nullable=False,
    )
