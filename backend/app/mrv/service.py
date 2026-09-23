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
"""How close the ETS figure must sit to the scope split to count within the reported share."""
FIGURE_COLUMNS = (
    ("total CO2", ShipEmissions.co2_total),
    ("to be reported under Directive 2003/87/EC", ShipEmissions.co2_ets),
    ("voyages between MS ports", ShipEmissions.co2_between_ms),
    ("voyages departed from MS ports", ShipEmissions.co2_departed_ms),
    ("voyages arrived at MS ports", ShipEmissions.co2_arrived_ms),
    ("within MS ports at berth", ShipEmissions.co2_at_berth),
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


def ets_scope_ratio() -> ColumnElement[float]:
    """The ETS figure as a share of the scope split."""
    return ShipEmissions.co2_ets / scoped()


async def fleet_figures(session: AsyncSession, period: int) -> DatasetBlock | None:
    """A period's totals per sheet and combined, with the ETS figure's spread against the
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
    ratio_stmt = select(
        func.count(),
        func.percentile_cont(0.5).within_group(ets_scope_ratio()),
        func.count().filter(
            func.abs(ShipEmissions.co2_ets - scoped()) <= SCOPE_TOLERANCE * ShipEmissions.co2_ets
        ),
    ).where(ShipEmissions.period == period, ShipEmissions.co2_ets > 0, scoped() != 0)
    with_ets, median, matching = (await session.execute(ratio_stmt)).one()
    _, version, generated, *_ = rows[0]
    return DatasetBlock(
        period=period,
        version=version,
        generated=generated,
        text=format_fleet_figures(
            period, version, generated, rows, median or 0.0, matching, with_ets
        ),
    )


def figure_group(heading: str, count: int, values: Sequence[float]) -> str:
    """One sheet's (or the fleet's) figures, each on its own labelled line."""
    lines = [f"{heading} — {count:,} reports"]
    lines += [
        f"  {name}: {value:,.0f} t" for (name, _), value in zip(FIGURE_COLUMNS, values, strict=True)
    ]
    return "\n".join(lines)


def format_fleet_figures(
    period: int,
    version: int,
    generated: date,
    rows: Sequence[FigureRow],
    median: float,
    matching: int,
    with_ets: int,
) -> str:
    """The period stated plainly, the totals as labelled figure lines per sheet and
    combined, and the ETS-to-scope ratio as one line."""
    heading = (
        f"Emissions reported for reporting period {period}, from the THETIS-MRV public "
        f"dataset (file version {version}, generated {generated.isoformat()})."
    )
    totals = [0.0] * len(FIGURE_COLUMNS)
    report_total = 0
    groups = []
    for sheet, _, _, count, *sums in rows:
        values = [value or 0.0 for value in sums]
        totals = [a + b for a, b in zip(totals, values, strict=True)]
        report_total += count
        groups.append(figure_group(f"{sheet.value} ERs", count, values))
    groups.append(figure_group("both", report_total, totals))
    share = matching / with_ets if with_ets else 0.0
    check = (
        f"Across the {with_ets:,} reports with an ETS figure, the ETS figure ÷ (100% between MS "
        "ports + 50% departed + 50% arrived + 100% at berth) has a median of "
        f"{median:.2f}, and {share:.0%} of reports sit within 1% of it."
    )
    return "\n\n".join([heading, *groups, check])
