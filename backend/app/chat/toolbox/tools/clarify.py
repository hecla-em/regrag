"""clarify: assess's question back to the reader when a name in the question could mean
several companies or ships and the question does not settle which."""

from pydantic import Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.enums import ToolStep
from app.chat.models import Clarification
from app.chat.toolbox.models import ToolCall, ToolSpec
from app.core.models import FrozenModel
from app.retrieval.models import RetrievedChunk

MAX_OPTIONS = 5


class ClarifyArgs(FrozenModel):
    """Assess's question back: the one call that ends the question in a question rather than an
    answer, with one option per candidate for the reader to pick."""

    question: str
    options: tuple[str, ...] = Field(min_length=2, max_length=MAX_OPTIONS)


async def run_clarification(session: AsyncSession, args: ClarifyArgs) -> tuple[RetrievedChunk, ...]:
    """Nothing to fetch: the call is its own result, read off it by the round."""
    return ()


CLARIFY = ToolSpec(
    name="clarify",
    step=ToolStep.CLARIFY,
    args_model=ClarifyArgs,
    run=run_clarification,
    description="Ask the reader which company or ship they mean, when a name in the question "
    "could be more than three in THETIS-MRV and the question does not settle which. Give a "
    "short question, and one option per candidate with its name and IMO number exactly as "
    "the question's candidates give them. Call it alone, never beside another tool.",
)


def is_clarification(call: ToolCall) -> bool:
    return call.name == CLARIFY.name


def clarification_from(call: ToolCall) -> Clarification | None:
    """The question a clarify call carries; None for any other call, and for a clarify call
    with malformed arguments, which then ends nothing."""
    if not is_clarification(call):
        return None
    try:
        args = ClarifyArgs.model_validate(call.args)
    except ValidationError:
        return None
    return Clarification(question=args.question, options=args.options)
