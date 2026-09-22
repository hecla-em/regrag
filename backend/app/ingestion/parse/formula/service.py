"""Formula cache persistence: what each model has already read, and recording what it reads."""

from collections.abc import Collection, Mapping

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.parse.formula.schemas import FormulaRendering


async def get_renderings(
    session: AsyncSession, image_hashes: Collection[str], *, model: str
) -> dict[str, str | None]:
    """The LaTeX this model already read for these images, None where it found no formula."""
    stmt = select(FormulaRendering.image_hash, FormulaRendering.latex).where(
        FormulaRendering.image_hash.in_(image_hashes), FormulaRendering.model == model
    )
    rows = await session.execute(stmt)
    return {row.image_hash: row.latex for row in rows}


async def upsert_renderings(
    session: AsyncSession, renderings: Mapping[str, str | None], *, model: str
) -> None:
    """Record what the model read, replacing any row an earlier model left for the same image."""
    if not renderings:
        return
    stmt = insert(FormulaRendering).values(
        [
            {"image_hash": digest, "latex": latex, "model": model}
            for digest, latex in renderings.items()
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[FormulaRendering.image_hash],
        set_={"latex": stmt.excluded.latex, "model": stmt.excluded.model, "updated_at": func.now()},
    )
    await session.execute(stmt)
