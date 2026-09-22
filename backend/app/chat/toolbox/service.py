"""The assess loop's tool surface: which tools the model may call, how one call runs, and
the step it records."""

import logging

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.chat.blocks import ContextBlock
from app.chat.enums import ChatStepStatus, ToolStep
from app.chat.models import ChatStepResult
from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.tools.follow_reference import (  # noqa: F401
    FOLLOW_REFERENCE,
    already_in_context,
)
from app.chat.toolbox.tools.refuse import REFUSE, is_refusal, refusal_from  # noqa: F401
from app.chat.toolbox.tools.search import SEARCH
from app.core.config import config
from app.core.db.session import get_session
from app.core.llm.errors import LLMError

logger = logging.getLogger(__name__)

TOOLS = {spec.name: spec for spec in (SEARCH, FOLLOW_REFERENCE, REFUSE)}
"""Every tool the surface has, whether or not this run offers it to the model."""


def tool_definitions() -> list[dict]:
    """The surface as assess is shown it: the fetch tools, and refuse while refusing is
    allowed."""
    return [
        spec.definition()
        for spec in TOOLS.values()
        if spec is not REFUSE or config.ASSESS_MAY_REFUSE
    ]


def describe_call(call: ToolCall) -> str | None:
    """What a call was for, as the trail shows it: the arguments it was given, in the order
    the model gave them — a query, or a citation's address — and nothing when it gave none."""
    given = [str(value) for value in call.args.values() if value]
    return " · ".join(given) or None


def build_call_step(
    call: ToolCall, *, ms: int = 0, status: ChatStepStatus = ChatStepStatus.COMPLETED
) -> ChatStepResult:
    """The step a call records, as announced when it starts and as settled once it has run:
    built in one place so the two frames the client pairs up cannot disagree. A tool the
    surface does not have records as unknown."""
    spec = TOOLS.get(call.name)
    return ChatStepResult(
        step=spec.step if spec else ToolStep.UNKNOWN,
        ms=ms,
        status=status,
        subject=describe_call(call),
    )


async def run_tool_call(call: ToolCall) -> tuple[ContextBlock, ...]:
    """One call's chunks; an unknown tool, an invalid target or a failing call yields
    nothing, never an error — the loop is best-effort and a bad call adds nothing.

    The session is the call's own, so a database error rolls back only the call that hit it;
    shared, the rollback it leaves owing would fail every later call in the round.
    """
    spec = TOOLS.get(call.name)
    if spec is None:
        logger.warning("assess called unknown tool %s", call.name)
        return ()
    try:
        args = spec.args_model.model_validate(call.args)
        async with get_session(auto_commit=False) as session:
            return await spec.run(session, args)
    except ValidationError:
        logger.warning("assess called %s with invalid arguments", call.name)
        return ()
    except (LLMError, SQLAlchemyError) as exc:
        logger.warning("assess call to %s failed: %s", call.name, exc)
        return ()
