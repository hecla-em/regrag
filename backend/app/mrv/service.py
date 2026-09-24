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


async def loaded_files(session: AsyncSession) -> dict[int, int]:
    """Each loaded period's file version."""
    stmt = select(MrvReport.period, MrvReport.version).distinct().order_by(MrvReport.period)
    return {period: version for period, version in (await session.execute(stmt)).all()}


async def load_new_files(
    session: AsyncSession, client: httpx.AsyncClient, store: ObjectStore
) -> dict[int, int]:
    """Every period whose latest published file is not the one loaded; rows loaded per period."""
    loaded = await loaded_files(session)
    files = [file for file in await list_files(client) if loaded.get(file.period) != file.version]
    return {file.period: await load_period(session, client, store, file) for file in files}
