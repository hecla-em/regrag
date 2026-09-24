"""mrv reports

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-22 16:29:17.127070

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
    """THETIS-MRV reports, one row per ship per period, replaced whole on each load."""
    op.create_table(
        "mrv_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("period_label", sa.String(), nullable=False),
        sa.Column(
            "sheet",
            sa.Enum("full", "partial", name="mrvsheet", native_enum=False),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("generated", sa.Date(), nullable=False),
        sa.Column("imo", sa.String(), nullable=False),
        sa.Column("ship_name", sa.String(), nullable=False),
        sa.Column("ship_type", sa.String(), nullable=False),
        sa.Column("ship_key", sa.String(), nullable=False),
        sa.Column("company_imo", sa.String(), nullable=True),
        sa.Column("company_name", sa.String(), nullable=True),
        sa.Column("company_key", sa.String(), nullable=True),
        sa.Column("co2_total", sa.Float(), nullable=True),
        sa.Column("co2_ets", sa.Float(), nullable=True),
        sa.Column("co2_between_ms", sa.Float(), nullable=True),
        sa.Column("co2_departed_ms", sa.Float(), nullable=True),
        sa.Column("co2_arrived_ms", sa.Float(), nullable=True),
        sa.Column("co2_at_berth", sa.Float(), nullable=True),
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
    op.create_index("ix_mrv_reports_period_sheet", "mrv_reports", ["period", "sheet"], unique=False)
    op.create_index(
        "ix_mrv_reports_company_key",
        "mrv_reports",
        ["company_key"],
        unique=False,
        postgresql_ops={"company_key": "text_pattern_ops"},
    )
    op.create_index("ix_mrv_reports_ship_key", "mrv_reports", ["ship_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_mrv_reports_ship_key", table_name="mrv_reports")
    op.drop_index("ix_mrv_reports_company_key", table_name="mrv_reports")
    op.drop_index("ix_mrv_reports_period_sheet", table_name="mrv_reports")
    op.drop_table("mrv_reports")
