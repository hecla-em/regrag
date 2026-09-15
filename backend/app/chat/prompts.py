"""The wording more than one node shares: the thread note, and the numbered-context
formatting a citation marker refers to."""

from collections.abc import Callable, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.chat.models import ChatTurn
from app.ingestion.celex import format_act_name
from app.retrieval.models import RetrievedChunk

THREAD_NOTE = (
    " Earlier turns of the conversation come before the context; read them only to "
    "understand what the question refers to. They are not context to answer from: cite "
    "only this turn's numbered blocks."
)


def system_prompt(base: str, history: Sequence[ChatTurn]) -> str:
    """The system prompt as one turn sends it: the base alone on a first question, and
    with the thread note on a follow-up, so a first question's prompt is unchanged."""
    return f"{base}{THREAD_NOTE}" if history else base


def format_context_block(marker: int, source: RetrievedChunk) -> str:
    """One chunk as the numbered block a citation marker refers to, under the act's name
    as it is cited."""
    return f"[{marker}] ({format_act_name(source.celex)}, {source.citation})\n{source.text}"


def format_acts_legend(sources: Sequence[RetrievedChunk]) -> str:
    """Each act the chunks come from, once, in order of first appearance: the cited name the
    block headers use, then the official title. An act without a stored title is left out,
    and no titles at all leaves no legend; an official title is too long to repeat per block."""
    titles: dict[str, str] = {}
    for source in sources:
        if source.act_title and source.celex not in titles:
            titles[source.celex] = source.act_title
    if not titles:
        return ""
    lines = [f"{format_act_name(celex)}: {title}" for celex, title in titles.items()]
    return "\n".join(["Acts:", *lines])


def format_context(
    sources: Sequence[RetrievedChunk], footer: Callable[[RetrievedChunk], str] | None = None
) -> str:
    """The retrieved chunks as the numbered blocks the citation markers refer to, each
    block followed by what the caller's footer adds to it, under a legend naming the acts.
    One loop, so every node that shows the context numbers it the same way."""
    blocks = []
    if legend := format_acts_legend(sources):
        blocks.append(legend)
    for marker, source in enumerate(sources, start=1):
        block = format_context_block(marker, source)
        if footer and (line := footer(source)):
            block += f"\n{line}"
        blocks.append(block)
    return "\n\n".join(blocks)


def thread_messages(history: Sequence[ChatTurn]) -> list[BaseMessage]:
    """The thread's earlier turns as the message pairs a model reads them as, oldest first,
    to go between the system prompt and this turn's user message."""
    messages: list[BaseMessage] = []
    for turn in history:
        messages.append(HumanMessage(turn.question))
        messages.append(AIMessage(turn.answer))
    return messages
