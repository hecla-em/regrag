"""THETIS-MRV loading: each reporting period's latest file, fetched, kept and swapped in whole."""

import logging

import httpx
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import ObjectStore
from app.mrv.download import fetch_file, list_files
from app.mrv.models import MrvFile
from app.mrv.parse import parse_workbook
from app.mrv.schemas import MrvReport

logger = logging.getLogger(__name__)

FIRST_PERIOD = 2024
"""The first reporting period the ETS covers shipping for."""


async def load_period(
    session: AsyncSession, client: httpx.AsyncClient, store: ObjectStore, file: MrvFile
) -> int:
    """Fetch and keep one period's latest file, and swap its rows in, in one transaction; the
    rows it loaded."""
    content = await fetch_file(client, file)
    store.put(f"mrv/{file.period}/v{file.version}.xlsx", content)
    rows = parse_workbook(content, file)
    stmt = delete(MrvReport).where(MrvReport.period == file.period)
    await session.execute(stmt)
    await session.execute(insert(MrvReport), rows)
    await session.commit()
    logger.info("loaded %d MRV reports for %d v%d", len(rows), file.period, file.version)
    return len(rows)


async def load_periods(
    session: AsyncSession, client: httpx.AsyncClient, store: ObjectStore, periods: list[int] | None
) -> dict[int, int]:
    """Every requested period from FIRST_PERIOD on, or all of them; rows loaded per period."""
    chosen = [
        file
        for file in await list_files(client)
        if file.period >= FIRST_PERIOD and (periods is None or file.period in periods)
    ]
    return {file.period: await load_period(session, client, store, file) for file in chosen}


async def loaded_versions(session: AsyncSession) -> str:
    """Each loaded period with its file version, like '2024v243,2025v58'; empty when none is."""
    stmt = select(MrvReport.period, MrvReport.version).distinct().order_by(MrvReport.period)
    rows = (await session.execute(stmt)).all()
    return ",".join(f"{period}v{version}" for period, version in rows)
