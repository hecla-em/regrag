"""Whether the model a run is about to score honours what its nodes bind to it. A binding
the model drops fails no call: decompose falls back to the question as asked and assess
asks for nothing at all, so the run scores as though the node had been switched off, and
reads as a finding about the model rather than a missing capability."""

import logging
from collections.abc import Sequence
from enum import StrEnum

from langchain_core.messages import HumanMessage, SystemMessage

from app.chat.graph.nodes.assess import assess_model, build_assess_system_prompt
from app.chat.graph.nodes.decompose import (
    DECOMPOSE_SYSTEM_PROMPT,
    DecomposedQuestion,
    decompose_model,
)
from app.core.config import config
from app.core.llm.errors import LLMError, parse_model_answer, wrap_provider_errors
from app.core.llm.models import price_tokens
from app.core.models import FrozenModel

logger = logging.getLogger(__name__)


class ModelCapability(StrEnum):
    """What a node needs of the chat model, and what a run loses without it.

    LISTED_PRICE: litellm knows the model's prices. Without them every call records its
        usage unpriced, which empties the cost column and stops the daily spend cap firing.
    STRUCTURED_ANSWER: the model answers in the shape rewrite and decompose bind. Without it
        every question is searched as asked, in the words it was asked in.
    TOOL_CALLS: the model calls the tools assess binds. Without them assess asks for
        nothing, the loop never runs, and nothing is written to the log about it.
    """

    LISTED_PRICE = "listed_price"
    STRUCTURED_ANSWER = "structured_answer"
    TOOL_CALLS = "tool_calls"


class CapabilityCheck(FrozenModel):
    """One capability, whether the selected model showed it, and what it showed instead."""

    capability: ModelCapability
    supported: bool
    detail: str = ""


DECOMPOSE_PROBE = "What is the sulphur limit inside a SECA, and how is a ship's EEXI calculated?"
"""Two questions answered by different provisions, so a model honouring the bound shape has
something to put in it."""

ASSESS_PROBE = (
    "Context:\n\n"
    "[1] (Directive 2014/94/EU, Article 3)\n"
    "Each Member State shall adopt a national policy framework drawn up in accordance with "
    "the requirements of Article 4.\n"
    "cites: 32014L0094 Article 4\n\n"
    "Question: What does Article 4 require the national policy framework to contain?"
)
"""A block leaning on a provision it cites but does not quote: what the assess prompt names
as the case for follow_reference."""


def check_listed_price() -> CapabilityCheck:
    """Whether litellm prices the selected model, which costs no call: an unknown name is
    unpriced whatever the tokens."""
    priced = price_tokens(config.CHAT_MODEL, 1, 1) is not None
    return CapabilityCheck(
        capability=ModelCapability.LISTED_PRICE,
        supported=priced,
        detail="" if priced else "usage records unpriced, and the daily spend cap never fires",
    )


@wrap_provider_errors("structured answer probe")
async def check_structured_answer() -> CapabilityCheck:
    """Whether the model answers in the shape decompose binds, as rewrite binds its own. Only
    the shape is judged: how the model splits the question is a score, not a capability."""
    messages = [SystemMessage(DECOMPOSE_SYSTEM_PROMPT), HumanMessage(DECOMPOSE_PROBE)]
    response = await decompose_model().ainvoke(messages)
    try:
        split = parse_model_answer(
            DecomposedQuestion, response.text, label=ModelCapability.STRUCTURED_ANSWER
        )
    except LLMError:
        return CapabilityCheck(
            capability=ModelCapability.STRUCTURED_ANSWER,
            supported=False,
            detail="answered off the bound schema",
        )
    return CapabilityCheck(
        capability=ModelCapability.STRUCTURED_ANSWER,
        supported=True,
        detail=f"split the probe into {len(split.queries)}",
    )


@wrap_provider_errors("tool call probe")
async def check_tool_calls() -> CapabilityCheck:
    """Whether the model calls the tools assess binds, on a block the prompt tells it to
    follow. A model that could call one and judged it unnecessary reads the same way here,
    so this is the one check a capable model can fail."""
    messages = [
        SystemMessage(build_assess_system_prompt(may_refuse=config.ASSESS_MAY_REFUSE)),
        HumanMessage(ASSESS_PROBE),
    ]
    response = await assess_model().ainvoke(messages)
    called = [call["name"] for call in response.tool_calls]
    return CapabilityCheck(
        capability=ModelCapability.TOOL_CALLS,
        supported=bool(called),
        detail=", ".join(called) if called else "asked for no tool where the prompt calls for one",
    )


async def check_model_capabilities(*, retrieval: bool = True) -> tuple[CapabilityCheck, ...]:
    """Every capability the run ahead leans on, checked against the selected model. A node
    switched off is never checked, since the run binds nothing to it, and a run answering
    from memory alone binds nothing at all: two model calls at most, and none on a baseline."""
    checks = [check_listed_price()]
    if retrieval:
        checks.append(await check_structured_answer())
    if retrieval and config.ASSESS_ENABLED:
        checks.append(await check_tool_calls())
    return tuple(checks)


def unsupported_capabilities(checks: Sequence[CapabilityCheck]) -> tuple[ModelCapability, ...]:
    """The capabilities the model did not show, which is what a run is held back for."""
    return tuple(check.capability for check in checks if not check.supported)


def format_capabilities(checks: Sequence[CapabilityCheck]) -> list[str]:
    """The model under test, then one line per capability with what it showed."""
    width = max(len(check.capability) for check in checks)
    lines = [f"{config.CHAT_MODEL}:"]
    for check in checks:
        shown = "ok" if check.supported else "missing"
        detail = f"  ({check.detail})" if check.detail else ""
        lines.append(f"  {check.capability:<{width}}  {shown}{detail}")
    return lines
