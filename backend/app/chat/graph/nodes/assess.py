"""assess ⇄ assess_tools: what the context still needs read, and the round that reads it."""

import asyncio
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
from app.chat.prompts import format_context, format_named, system_prompt, thread_messages
from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.service import (
    already_in_context,
    build_call_step,
    clarification_from,
    ends_the_run,
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
    "reports were filed and their CO2 totals, for the whole fleet or narrowed to companies or "
    "ships by IMO number, summed per report type (Full, Partial) or per company or ship "
    "to rank them or list a company's ships, and how the ETS figure compares with the ETS scope "
    "split — use it whenever the answer needs one of those figures or one worked out from "
    "them, such as a share, a change between periods, a company's exposure or an amount to "
    "surrender, or turns on what the dataset's figures include; the regulations say what is "
    "to be reported, never what the dataset holds, so a "
    "question about the dataset needs mrv_query even when the blocks state the rule. An "
    "amount to surrender or a company's exposure needs both mrv_query and, unless the context "
    "shows it, follow_reference to Article 3gb of Directive 2003/87/EC (32003L0087), the "
    "phase-in. "
    "A name the question gives is listed with every company or ship in THETIS-MRV it could "
    "mean, each with its IMO number and the years it reported; mrv_query takes them by those "
    "numbers, never by name. "
    "Names are matched on words alone, so a port, place or ordinary word can match too: use a "
    "candidate only when the question asks about that company or ship, and ignore the rest. "
    "When a name could mean one, query it. When it could mean two or "
    "three and the question does not say which, query them together in one call, so the "
    "answer gives each its own figures. "
    "Never query a candidate for a year it did not report: when it is the only one, query a "
    "year it reported instead. "
    "You get one round, so call every tool the question needs together. "
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

ASSESS_CLARIFY_INSTRUCTION = " When it could mean more than three, call clarify alone instead."


def build_assess_system_prompt(*, may_refuse: bool, may_clarify: bool) -> str:
    """The assess system prompt, telling the model when to refuse or ask back only when it
    is offered the tool to do it with."""
    prompt = ASSESS_SYSTEM_PROMPT
    prompt += ASSESS_REFUSAL_INSTRUCTION if may_refuse else ""
    prompt += ASSESS_CLARIFY_INSTRUCTION if may_clarify else ""
    return prompt


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
    named = format_named(entities)
    return f"{context}{named}\n\nQuestion: {question}"


def assess_model(*, may_clarify: bool) -> Runnable:
    """The assess model as assess calls it: one blocking turn, the tool surface bound."""
    return chat_model(streaming=False).bind_tools(tool_definitions(may_clarify=may_clarify))


@llm_retry
@wrap_provider_errors("assess call")
async def call_assess_model(state: ChatState) -> dict[str, Any]:
    """One model turn asking what would fill the gaps in the context — or, called alone,
    saying nothing bears on the question. A refuse or clarify call beside a fetch is dropped,
    the fetch being the model's own doubt; a fetch that would only re-fetch a division the
    context already shows is dropped too, then the rest are capped to the calls a round may
    run — none of the dropped reaches state or the ledger."""
    messages = [
        SystemMessage(
            system_prompt(
                build_assess_system_prompt(
                    may_refuse=config.ASSESS_MAY_REFUSE, may_clarify=state.may_clarify
                ),
                state.history,
            )
        ),
        *thread_messages(state.history),
        HumanMessage(
            build_assess_message(state.question, state.sources, state.matched_tools, state.entities)
        ),
    ]
    response = await assess_model(may_clarify=state.may_clarify).ainvoke(messages)
    asked = [ToolCall(name=c["name"], args=c["args"]) for c in response.tool_calls]
    endings = [call for call in asked if ends_the_run(call)]
    fetches = [call for call in asked if not ends_the_run(call)]
    if endings and not fetches:
        return {"pending_calls": (endings[0],), "reply": response}
    if endings:
        logger.info("assess hedged its refusal or question with a fetch, so the fetch runs")
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


async def run_timed_call(call: ToolCall) -> tuple[tuple[ContextBlock, ...], ChatStepResult]:
    """One call's chunks, with the step that says how long it took."""
    start = time.perf_counter()
    blocks = await run_tool_call(call)
    return blocks, build_call_step(call, ms=elapsed_ms(start))


async def assess_tools(state: ChatState) -> dict[str, Any]:
    """The round's calls run at once and folded into the context in the order asked: dedup
    by block, earlier context kept, growth capped. Each call is timed as its own step, so
    the path says what it cost. A refuse or clarify call fetches nothing and leaves its
    ending on the state, which is what routes the round to it."""
    results = await asyncio.gather(*(run_timed_call(call) for call in state.pending_calls))
    fetched = [block for blocks, _ in results for block in blocks]
    refusal, clarification = state.refusal, state.clarification
    for call in state.pending_calls:
        if refused := refusal_from(call):
            refusal = refused
            logger.info("assess refused for want of context: %s", refused.explanation)
        if clarified := clarification_from(call):
            clarification = clarified
            logger.info("assess asked which was meant: %s", clarified.question)

    cap = state.retrieved_sources + config.ASSESS_EXTRA_CHUNKS
    return {
        "sources": merge_sources(state.sources, fetched, cap=cap),
        "pending_calls": (),
        "refusal": refusal,
        "clarification": clarification,
        "steps": tuple(step for _, step in results),
    }
