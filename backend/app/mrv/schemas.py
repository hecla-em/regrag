"""THETIS-MRV reports: one row per emissions report EMSA publishes."""

from datetime import date

from sqlalchemy import Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.schema import BaseSchema
from app.mrv.enums import MrvSheet


class ShipEmissions(BaseSchema):
    """One published report: the ship, its company, and its CO2 in tonnes, split by EU scope.
    A period's rows are replaced whole by each load, stamped with EMSA's file version."""

    __tablename__ = "ship_emissions"
    __table_args__ = (Index("ix_ship_emissions_period_sheet", "period", "sheet"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[int]
    period_label: Mapped[str]
    sheet: Mapped[MrvSheet]
    version: Mapped[int]
    generated: Mapped[date]
    imo: Mapped[str]
    ship_name: Mapped[str]
    ship_type: Mapped[str]
    company_imo: Mapped[str | None]
    company_name: Mapped[str | None]
    co2_total: Mapped[float | None]
    co2_ets: Mapped[float | None]
    co2_between_ms: Mapped[float | None]
    co2_departed_ms: Mapped[float | None]
    co2_arrived_ms: Mapped[float | None]
    co2_at_berth: Mapped[float | None]
