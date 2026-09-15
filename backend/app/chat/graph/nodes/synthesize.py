"""synthesize: one streamed model call answering from the context with [n] citations."""

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.chat.graph.node import chat_model, traced
from app.chat.models import ChatState
from app.chat.prompts import format_context, system_prompt, thread_messages
from app.core.llm.errors import llm_retry, wrap_provider_errors
from app.retrieval.models import RetrievedChunk

SYSTEM_PROMPT = (
    "You are RegRag, an assistant answering questions about EU maritime regulation. "
    "Answer using only the numbered context blocks provided. Cite every claim inline "
    "with the marker of the block it comes from, like [1] or [2][3], placed after the "
    "punctuation that ends the claim (e.g. 'must be reported.[1]'), never before it. "
    "If the context "
    "does not answer the question, say so plainly instead of guessing. "
    "Start directly with the answer: no title, no restating the question, and no "
    "preamble such as 'Based on the context provided'. When several acts give the same "
    "answer, give it once and name the acts it holds for, then note only where they "
    "differ; do not repeat near-identical lists per act. Refer to an act by the name and "
    "number the context gives it; never invent a title for one."
)


def build_user_message(question: str, sources: Sequence[RetrievedChunk]) -> str:
    """The full user turn: context blocks first, then the question."""
    return f"Context:\n\n{format_context(sources)}\n\nQuestion: {question}"


@traced
@llm_retry
@wrap_provider_errors("chat call")
async def synthesize(state: ChatState) -> dict[str, Any]:
    """One streamed model call answering from the context with [n] citations.

    A transient provider failure is retried like embed and rerank; one that strikes
    mid-stream restarts the answer, so its tokens reach the client twice.
    """
    messages = [
        SystemMessage(system_prompt(SYSTEM_PROMPT, state.history)),
        *thread_messages(state.history),
        HumanMessage(build_user_message(state.question, state.sources)),
    ]
    response = await chat_model().ainvoke(messages)
    return {"answer": response.text, "usage": response.usage_metadata}
