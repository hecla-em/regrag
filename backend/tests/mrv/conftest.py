"""THETIS-MRV test fixtures: build MrvReport rows with keys derived as the loader derives them."""

from datetime import date
from typing import Any

from app.mrv.enums import MrvSheet
from app.mrv.names import company_key, name_key
from app.mrv.schemas import MrvReport


def mrv_report(**overrides: Any) -> MrvReport:
    """One 2024 report, its keys derived from its names as the loader derives them."""
    fields: dict[str, Any] = {
        "period": 2024,
        "period_label": "2024",
        "sheet": MrvSheet.FULL,
        "version": 1,
        "generated": date(2025, 6, 30),
        "imo": "9000001",
        "ship_name": "SHIP ONE",
        "ship_type": "Bulk carrier",
        "company_imo": None,
        "company_name": None,
        "co2_total": 1000.0,
        "co2_ets": 400.0,
        "co2_between_ms": 200.0,
        "co2_departed_ms": 200.0,
        "co2_arrived_ms": 200.0,
        "co2_at_berth": 200.0,
    } | overrides
    fields["ship_key"] = name_key(fields["ship_name"])
    fields["company_key"] = company_key(fields["company_name"]) if fields["company_name"] else None
    return MrvReport(**fields)


def company_report(name: str, company_imo: str, period: int = 2024, **overrides: Any) -> MrvReport:
    return mrv_report(company_name=name, company_imo=company_imo, period=period, **overrides)
