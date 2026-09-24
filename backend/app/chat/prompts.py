"""The wording more than one node shares: the thread note, and the numbered-context
formatting a citation marker refers to."""

from collections.abc import Callable, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.chat.blocks import ContextBlock, corpus_chunks
from app.chat.models import ChatTurn
from app.retrieval.models import RetrievedChunk

THREAD_NOTE = (
    " Earlier turns of the conversation come before the numbered passages; read them only to "
    "understand what the question refers to. They are not text to answer from: cite "
    "only this turn's numbered passages."
)


def system_prompt(base: str, history: Sequence[ChatTurn]) -> str:
    """The system prompt as one turn sends it: the base alone on a first question, and
    with the thread note on a follow-up, so a first question's prompt is unchanged."""
    return f"{base}{THREAD_NOTE}" if history else base


def format_context_block(marker: int, block: ContextBlock) -> str:
    """One block as the numbered block a citation marker refers to, under its name and citation."""
    return f"[{marker}] ({block.name}, {block.citation})\n{block.prompt_text}"


def format_acts_legend(sources: Sequence[ContextBlock]) -> str:
    """Each act the chunks come from, once, in order of first appearance: the cited name the
    block headers use, then the official title. An act without a stored title is left out,
    and no titles at all leaves no legend; an official title is too long to repeat per block."""
    acts: dict[str, RetrievedChunk] = {}
    for source in corpus_chunks(sources):
        if source.act_title and source.celex not in acts:
            acts[source.celex] = source
    if not acts:
        return ""
    lines = [f"{chunk.name}: {chunk.act_title}" for chunk in acts.values()]
    return "\n".join(["Acts:", *lines])


def format_context(
    sources: Sequence[ContextBlock], footer: Callable[[ContextBlock], str] | None = None
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
