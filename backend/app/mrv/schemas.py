"""THETIS-MRV reports: one row per emissions report EMSA publishes."""

from datetime import date

from sqlalchemy import Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.schema import BaseSchema
from app.mrv.enums import MrvSheet


class MrvReport(BaseSchema):
    """One published report: the ship, its company, their names as keys match them, and its CO2
    in tonnes, split by EU scope. A load replaces a period whole, stamped with EMSA's version."""

    __tablename__ = "mrv_reports"
    __table_args__ = (
        Index("ix_mrv_reports_period_sheet", "period", "sheet"),
        Index(
            "ix_mrv_reports_company_key",
            "company_key",
            postgresql_ops={"company_key": "text_pattern_ops"},
        ),
        Index("ix_mrv_reports_ship_key", "ship_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[int]
    period_label: Mapped[str]
    sheet: Mapped[MrvSheet]
    version: Mapped[int]
    generated: Mapped[date]
    imo: Mapped[str]
    ship_name: Mapped[str]
    ship_type: Mapped[str]
    ship_key: Mapped[str]
    company_imo: Mapped[str | None]
    company_name: Mapped[str | None]
    company_key: Mapped[str | None]
    co2_total: Mapped[float | None]
    co2_ets: Mapped[float | None]
    co2_between_ms: Mapped[float | None]
    co2_departed_ms: Mapped[float | None]
    co2_arrived_ms: Mapped[float | None]
    co2_at_berth: Mapped[float | None]
