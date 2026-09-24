"""assess ⇄ assess_tools: what the context still needs read, and the round that reads it."""

import logging
import time
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from app.chat.blocks import ContextBlock
from app.chat.graph.node import chat_model, traced
from app.chat.models import ChatState, ChatStepResult
from app.chat.prompts import format_context, system_prompt, thread_messages
from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.service import (
    already_in_context,
    build_call_step,
    is_refusal,
    refusal_from,
    run_tool_call,
    tool_definitions,
)
from app.core.clock import elapsed_ms
from app.core.config import config
from app.core.llm.errors import LLMError, llm_retry, wrap_provider_errors
from app.retrieval.models import ReferenceTarget, RetrievedChunk

logger = logging.getLogger(__name__)

ASSESS_SYSTEM_PROMPT = (
    "You decide what RegRag, an assistant answering questions about EU maritime "
    "regulation, still needs to read before answering. You are shown a question and "
    "the numbered context blocks retrieved so far; each block may list what it cites. "
    "If the context already answers the whole question, call no tools. Otherwise call "
    "what fills the gap: follow_reference fetches the exact text a block cites — "
    "prefer it whenever a block leans on a provision named in its cites line, passing "
    "that line's document number and division; search runs a fresh corpus search — "
    "use it when a needed concept is named without a citation, or a part of the "
    "question has no context at all, narrowing with celex when the act is known. "
    "mrv_query reads one reporting period of the THETIS-MRV public dataset: how many emissions "
    "reports were filed and their CO2 totals, for the whole fleet or narrowed to a company or "
    "ship named in the question, summed per report type (Full, Partial) or per company or ship "
    "to rank them or list a company's ships, and how the ETS figure compares with the ETS scope "
    "split — use it whenever the answer needs one of those figures or one worked out from "
    "them, such as a share, a change between periods, a company's exposure or an amount to "
    "surrender, or turns on what the dataset's figures include; the regulations say what is "
    "to be reported, never what the dataset holds, so a "
    "question about the dataset needs mrv_query even when the blocks state the rule. An "
    "amount to surrender or a company's exposure needs both mrv_query and, unless the context "
    "shows it, follow_reference to Article 3gb of Directive 2003/87/EC (32003L0087), the "
    "phase-in. You get one round, so call every tool the question needs together. "
    "Never re-fetch what the context already shows. You never answer the question "
    "yourself: your output is tool calls, or nothing when the context suffices."
)

ASSESS_REFUSAL_INSTRUCTION = (
    " If no block bears on the question and no search or fetch of this corpus of EU "
    "maritime regulation could — it asks about another regime, about an event, for a "
    "figure neither a provision nor mrv_query holds, or about a topic outside the corpus — "
    "call refuse, alone, saying why. Blocks on the "
    "subject the question touches that do not answer it are not a part answer. Never call "
    "it on a question the context answers in part, or one a search or fetch might yet "
    "answer."
)


def build_assess_system_prompt(*, may_refuse: bool) -> str:
    """The assess system prompt, telling the model when to refuse only when it is offered
    the tool to do it with."""
    return ASSESS_SYSTEM_PROMPT + (ASSESS_REFUSAL_INSTRUCTION if may_refuse else "")


def reference_addresses(source: RetrievedChunk) -> list[str]:
    """Each followable address once, as 'celex division': a reference naming no division is
    skipped, on the same rule follow_reference's target enforces, and two phrasings of one
    target are one place to fetch."""
    addresses = []
    for reference in source.references:
        try:
            target = ReferenceTarget.from_reference(reference, citing=source.celex)
        except ValidationError:
            continue
        addresses.append(f"{target.celex} {target.citation}")
    return list(dict.fromkeys(addresses))


def cites_line(block: ContextBlock) -> str:
    """What a chunk cites, as the line assess reads it off; nothing for a block that is not a
    chunk or cites no followable address."""
    if not isinstance(block, RetrievedChunk):
        return ""
    addresses = reference_addresses(block)
    return f"cites: {', '.join(addresses)}" if addresses else ""


def build_assess_message(
    question: str,
    sources: Sequence[ContextBlock],
    matched_tools: Sequence[str] = (),
    entities: Sequence[str] = (),
) -> str:
    """The full assess turn: the numbered blocks with their cites lines, or, when only a
    tool opened the gate, which tools the question matched; what the question names in a
    dataset's data; then the question."""
    context = (
        f"Context:\n\n{format_context(sources, cites_line)}"
        if sources
        else "Context: no corpus passage matched. The question matches what these tools hold: "
        f"{', '.join(matched_tools)}."
    )
    named = f"\n\nThe question names {'; '.join(entities)}." if entities else ""
    return f"{context}{named}\n\nQuestion: {question}"


def assess_model() -> Runnable:
    """The assess model as assess calls it: one blocking turn, the tool surface bound."""
    return chat_model(streaming=False).bind_tools(tool_definitions())


@llm_retry
@wrap_provider_errors("assess call")
async def call_assess_model(state: ChatState) -> dict[str, Any]:
    """One model turn asking what would fill the gaps in the context — or, called alone,
    saying nothing bears on the question. That call beside a fetch is dropped, the fetch
    being the model's own doubt; a fetch that would only re-fetch a division the context
    already shows is dropped too, then the rest are capped to the calls a round may run —
    none of the dropped reaches state or the ledger."""
    messages = [
        SystemMessage(
            system_prompt(
                build_assess_system_prompt(may_refuse=config.ASSESS_MAY_REFUSE), state.history
            )
        ),
        *thread_messages(state.history),
        HumanMessage(
            build_assess_message(state.question, state.sources, state.matched_tools, state.entities)
        ),
    ]
    response = await assess_model().ainvoke(messages)
    asked = [ToolCall(name=c["name"], args=c["args"]) for c in response.tool_calls]
    refusals = [call for call in asked if is_refusal(call)]
    fetches = [call for call in asked if not is_refusal(call)]
    if refusals and not fetches:
        return {"pending_calls": (refusals[0],), "reply": response}
    if refusals:
        logger.info("assess hedged its refusal with a fetch, so the fetch runs")
    useful = [call for call in fetches if not already_in_context(call, state.sources)]
    calls = tuple(useful[: config.ASSESS_MAX_CALLS])
    return {"pending_calls": calls, "reply": response}


@traced
async def assess(state: ChatState) -> dict[str, Any]:
    """One review of the context: the calls that would fill what is missing, or none when
    it suffices. A failing call settles for the context so far rather than failing the run."""
    try:
        return await call_assess_model(state)
    except LLMError as exc:
        logger.warning("assess call failed, settling for the context gathered so far: %s", exc)
        return {"pending_calls": ()}


def merge_sources(
    sources: tuple[ContextBlock, ...], additions: Sequence[ContextBlock], *, cap: int
) -> tuple[ContextBlock, ...]:
    """The context grown by a tool round: new blocks appended in arrival order, a block
    already present kept as it was, and nothing appended once the cap is reached. The cap
    counts the whole context, so it is read against what retrieve produced, not this round."""
    merged = list(sources)
    seen = {block.dedupe_key for block in merged}
    for block in additions:
        if len(merged) >= cap:
            break
        if block.dedupe_key in seen:
            continue
        seen.add(block.dedupe_key)
        merged.append(block)
    return tuple(merged)


async def assess_tools(state: ChatState) -> dict[str, Any]:
    """The round's calls run and folded into the context: dedup by block, earlier context
    kept, growth capped. Each call is timed as its own step, so the path says what it cost.
    A refuse call fetches nothing and leaves its refusal on the state, which is what routes
    the round to the refusal."""
    fetched: list[ContextBlock] = []
    steps: list[ChatStepResult] = []
    refusal = state.refusal
    for call in state.pending_calls:
        start = time.perf_counter()
        fetched.extend(await run_tool_call(call))
        steps.append(build_call_step(call, ms=elapsed_ms(start)))
        if refused := refusal_from(call):
            refusal = refused
            logger.info("assess refused for want of context: %s", refused.explanation)

    cap = state.retrieved_sources + config.ASSESS_EXTRA_CHUNKS
    return {
        "sources": merge_sources(state.sources, fetched, cap=cap),
        "pending_calls": (),
        "refusal": refusal,
        "steps": tuple(steps),
    }
