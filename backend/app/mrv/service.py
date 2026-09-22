"""THETIS-MRV: load a reporting period, and read fleet figures from it."""

import logging
from collections.abc import Sequence
from datetime import date

import httpx
from sqlalchemy import ColumnElement, Row, delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import ObjectStore
from app.mrv.download import MrvFile, fetch_file, list_files
from app.mrv.enums import MrvSheet
from app.mrv.models import DatasetBlock
from app.mrv.parse import parse_workbook
from app.mrv.schemas import ShipEmissions

logger = logging.getLogger(__name__)

FIRST_PERIOD = 2024
"""The first reporting period the ETS covers shipping for."""


async def replace_period(session: AsyncSession, file: MrvFile, rows: list[dict]) -> None:
    """The period's rows swapped for this file's, in one transaction."""
    stmt = delete(ShipEmissions).where(ShipEmissions.period == file.period)
    await session.execute(stmt)
    await session.execute(insert(ShipEmissions), rows)
    await session.commit()


async def load_period(
    session: AsyncSession, client: httpx.AsyncClient, store: ObjectStore, file: MrvFile
) -> int:
    """Fetch, keep and load one period's latest file; the rows it loaded."""
    content = await fetch_file(client, file)
    store.put(f"mrv/{file.period}/v{file.version}.xlsx", content)
    rows = parse_workbook(content, file)
    await replace_period(session, file, rows)
    logger.info("loaded %d MRV reports for %d v%d", len(rows), file.period, file.version)
    return len(rows)


async def load_periods(
    session: AsyncSession, client: httpx.AsyncClient, store: ObjectStore, periods: list[int] | None
) -> dict[int, int]:
    """Every requested period from FIRST_PERIOD on, or all of them; rows loaded per period."""
    files = [f for f in await list_files(client) if f.period >= FIRST_PERIOD]
    chosen = [f for f in files if periods is None or f.period in periods]
    return {file.period: await load_period(session, client, store, file) for file in chosen}


SCOPE_TOLERANCE = 0.01
"""How far a ship's ETS figure may sit from its scope split and still count as matching it."""
FIGURE_COLUMNS = (
    ("total", ShipEmissions.co2_total),
    ("ETS", ShipEmissions.co2_ets),
    ("between MS", ShipEmissions.co2_between_ms),
    ("departed MS", ShipEmissions.co2_departed_ms),
    ("arrived MS", ShipEmissions.co2_arrived_ms),
    ("at berth", ShipEmissions.co2_at_berth),
)

Amount = float | None
FigureRow = Row[tuple[MrvSheet, int, date, int, Amount, Amount, Amount, Amount, Amount, Amount]]
"""One sheet's row from the fleet totals query: sheet, version, generated, reports, then
each FIGURE_COLUMNS sum."""


def scoped() -> ColumnElement[float]:
    """The ETS scope split: 100% between MS ports and at berth, 50% to or from them."""
    return (
        func.coalesce(ShipEmissions.co2_between_ms, 0)
        + 0.5 * func.coalesce(ShipEmissions.co2_departed_ms, 0)
        + 0.5 * func.coalesce(ShipEmissions.co2_arrived_ms, 0)
        + func.coalesce(ShipEmissions.co2_at_berth, 0)
    )


async def fleet_figures(session: AsyncSession, period: int) -> DatasetBlock | None:
    """A period's totals per sheet and combined, with how often the ETS column equals the
    scope split; None when the period is not loaded."""
    sums = [func.sum(column) for _, column in FIGURE_COLUMNS]
    stmt = (
        select(
            ShipEmissions.sheet, ShipEmissions.version, ShipEmissions.generated, func.count(), *sums
        )
        .where(ShipEmissions.period == period)
        .group_by(ShipEmissions.sheet, ShipEmissions.version, ShipEmissions.generated)
        .order_by(ShipEmissions.sheet)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return None
    matching_stmt = select(
        func.count().filter(
            func.abs(ShipEmissions.co2_ets - scoped()) <= SCOPE_TOLERANCE * ShipEmissions.co2_ets
        ),
        func.count(),
    ).where(ShipEmissions.period == period, ShipEmissions.co2_ets > 0)
    matching, with_ets = (await session.execute(matching_stmt)).one()
    _, version, generated, *_ = rows[0]
    return DatasetBlock(
        period=period,
        version=version,
        generated=generated,
        text=format_fleet_figures(rows, matching, with_ets),
    )


def format_fleet_figures(rows: Sequence[FigureRow], matching: int, with_ets: int) -> str:
    """The totals as a table in tonnes, and the scope check as one line."""
    headings = ["", "reports", *(name for name, _ in FIGURE_COLUMNS)]
    lines = [" | ".join(headings)]
    totals = [0.0] * (len(FIGURE_COLUMNS) + 1)
    for sheet, _, _, count, *sums in rows:
        values = [count, *(value or 0.0 for value in sums)]
        totals = [a + b for a, b in zip(totals, values, strict=True)]
        lines.append(" | ".join([f"{sheet.value} ERs", *(f"{value:,.0f}" for value in values)]))
    lines.append(" | ".join(["both", *(f"{value:,.0f}" for value in totals)]))
    share = matching / with_ets if with_ets else 0.0
    check = (
        f"Of the {with_ets:,} reports with an ETS figure, {share:.0%} equal 100% between MS "
        "ports + 50% departed + 50% arrived + 100% at berth: the ETS column carries no phase-in."
        if share >= 0.9
        else f"Of the {with_ets:,} reports with an ETS figure, {share:.0%} equal the scope split."
    )
    return "\n".join(["Tonnes CO2, summed over the period's emissions reports:", *lines, check])
