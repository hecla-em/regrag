"""THETIS-MRV: load a reporting period, and read fleet figures from it."""

import logging

import httpx
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import ObjectStore
from app.mrv.download import MrvFile, fetch_file, list_files
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
