"""THETIS-MRV: load a reporting period, and read fleet figures from it."""

import logging

import httpx
from sqlalchemy import ColumnElement, delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import ObjectStore
from app.mrv.download import MrvFile, fetch_file, list_files
from app.mrv.models import FIGURE_LABELS, DatasetBlock, FigureTotals
from app.mrv.parse import parse_workbook
from app.mrv.schemas import MrvReport

logger = logging.getLogger(__name__)

FIRST_PERIOD = 2024
"""The first reporting period the ETS covers shipping for."""


async def replace_period(session: AsyncSession, file: MrvFile, rows: list[dict]) -> None:
    """The period's rows swapped for this file's, in one transaction."""
    stmt = delete(MrvReport).where(MrvReport.period == file.period)
    await session.execute(stmt)
    await session.execute(insert(MrvReport), rows)
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


def scoped() -> ColumnElement[float]:
    """The ETS scope split: 100% between MS ports and at berth, 50% to or from them."""
    return (
        func.coalesce(MrvReport.co2_between_ms, 0)
        + 0.5 * func.coalesce(MrvReport.co2_departed_ms, 0)
        + 0.5 * func.coalesce(MrvReport.co2_arrived_ms, 0)
        + func.coalesce(MrvReport.co2_at_berth, 0)
    )


def ets_scope_ratio() -> ColumnElement[float]:
    """The ETS figure as a share of the scope split."""
    return MrvReport.co2_ets / scoped()


async def fleet_totals(session: AsyncSession, period: int) -> DatasetBlock | None:
    """A period's totals per sheet, with the ETS figure's spread against the scope split;
    None when the period is not loaded."""
    sums = [
        func.coalesce(func.sum(getattr(MrvReport, name)), 0).label(name) for name in FIGURE_LABELS
    ]
    stmt = (
        select(
            MrvReport.sheet,
            MrvReport.version,
            MrvReport.generated,
            func.count().label("reports"),
            *sums,
        )
        .where(MrvReport.period == period)
        .group_by(MrvReport.sheet, MrvReport.version, MrvReport.generated)
        .order_by(MrvReport.sheet)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return None
    ratio_stmt = select(
        func.count(),
        func.percentile_cont(0.5).within_group(ets_scope_ratio()),
        func.count().filter(
            func.abs(MrvReport.co2_ets - scoped()) <= SCOPE_TOLERANCE * MrvReport.co2_ets
        ),
    ).where(MrvReport.period == period, MrvReport.co2_ets > 0, scoped() != 0)
    with_ets, median, matching = (await session.execute(ratio_stmt)).one()
    return DatasetBlock(
        period=period,
        version=rows[0].version,
        generated=rows[0].generated,
        sheets=tuple(FigureTotals(**row._asdict(), label=f"{row.sheet.value} ERs") for row in rows),
        reports_with_ets=with_ets,
        median_ets_ratio=median or 0.0,
        matching_ets_ratio=matching,
    )
