"""synthesize: one streamed model call answering from the context with [n] citations, or
from memory when there is no context."""

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.chat.graph.node import chat_model, traced
from app.chat.models import ChatState
from app.chat.prompts import format_context, system_prompt, thread_messages
from app.core.config import config
from app.core.llm.errors import llm_retry, wrap_provider_errors
from app.retrieval.models import RetrievedChunk

ROLE = "You are RegRag, an assistant answering questions about EU maritime regulation. "

STYLE = (
    "Start directly with the answer: no title, no restating the question, and no "
    "preamble such as 'Based on the regulations'. When several acts give the same "
    "answer, give it once and name the acts it holds for, then note only where they "
    "differ; do not repeat near-identical lists per act. "
)

UNCOVERED = (
    "The reader sees only your answer, so when the passages leave something unanswered, "
    "call them 'the passages I found', as in 'The passages I found from Regulation (EU) "
    "2023/1805 do not define…' or 'Article 3 of Directive 2003/87/EC is not among the "
    "passages I found'. "
)

SYSTEM_PROMPT = (
    f"{ROLE}"
    "Answer using only the numbered passages of regulation text you are shown. Cite every "
    "claim inline with the marker of the passage it comes from, like [1] or [2][3], placed "
    "after the punctuation that ends the claim (e.g. 'must be reported.[1]'), never before "
    "it. If the passages do not answer the question, say so plainly instead of guessing. "
    f"{UNCOVERED}"
    f"{STYLE}"
    "Refer to an act by the name and number the passages give it; never invent a title for one."
)

BASELINE_SYSTEM_PROMPT = (
    f"{ROLE}"
    "Answer from what you know of the regulations, naming the act and article each claim "
    "rests on. "
    f"{STYLE}"
    "Refer to an act by its official name and number; never invent a title for one."
)
"""The prompt a run with no sources answers under: the evals' no-retrieval baseline. The
graph refuses before synthesize when nothing was retrieved, so no chat request sees it."""


def build_user_message(question: str, sources: Sequence[RetrievedChunk]) -> str:
    """The full user turn: the numbered passages first, then the question."""
    return f"Passages found:\n\n{format_context(sources)}\n\nQuestion: {question}"


@traced
@llm_retry
@wrap_provider_errors("chat call")
async def synthesize(state: ChatState) -> dict[str, Any]:
    """One streamed model call answering from the context with [n] citations, or from
    memory under the baseline prompt when there are no sources.

    A transient provider failure is retried like embed and rerank; one that strikes
    mid-stream restarts the answer, so its tokens reach the client twice.
    """
    base = SYSTEM_PROMPT if state.sources else BASELINE_SYSTEM_PROMPT
    user = build_user_message(state.question, state.sources) if state.sources else state.question
    messages = [
        SystemMessage(system_prompt(base, state.history)),
        *thread_messages(state.history),
        HumanMessage(user),
    ]
    response = await chat_model(thinking=config.CHAT_THINKING_ENABLED).ainvoke(messages)
    return {"answer": response.text, "reply": response}
