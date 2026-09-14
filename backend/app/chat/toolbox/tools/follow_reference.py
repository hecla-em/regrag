"""follow_reference: the full text of a division the context cites, fetched by its address."""

from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.enums import ToolStep
from app.chat.toolbox.models import ToolCall, ToolSpec
from app.core.config import config
from app.retrieval.follow import follow_reference
from app.retrieval.models import ReferenceTarget, RetrievedChunk


async def run_follow_reference(
    session: AsyncSession, target: ReferenceTarget
) -> tuple[RetrievedChunk, ...]:
    """The division's text from the top, capped: a long article or annex would otherwise
    spend the round's whole budget on one call. No score to gate on — the context cited it."""
    chunks = await follow_reference(session, target)
    return chunks[: config.ASSESS_FOLLOW_LIMIT]


def already_in_context(call: ToolCall, sources: Sequence[RetrievedChunk]) -> bool:
    """Whether the call would only fetch what the context already shows: a point some shown
    part lists, or a paragraph shown in full. A whole article or annex is never known to be
    shown in full: its chapeau's parts say nothing about what sits under it."""
    if call.name != FOLLOW_REFERENCE.name:
        return False
    try:
        target = ReferenceTarget.model_validate(call.args)
    except ValidationError:
        return False
    if target.article is None:
        return False
    shown = [
        s
        for s in sources
        if s.celex == target.celex
        and (s.article or "").lower() == target.article.lower()
        and s.paragraph == target.paragraph
    ]
    if target.point is not None and any(target.point.lower() in s.points for s in shown):
        return True
    if target.paragraph is None:
        return False
    return bool(shown) and len({s.part for s in shown}) == shown[0].parts


FOLLOW_REFERENCE = ToolSpec(
    name="follow_reference",
    step=ToolStep.FOLLOW_REFERENCE,
    args_model=ReferenceTarget,
    run=run_follow_reference,
    description="Fetch the full text of one cited division: an article (optionally one paragraph, "
    "or one point of it, as in 'Article 3, point (e)') or an annex of an act (celex). Use the "
    "addresses on the context's cites lines.",
)
