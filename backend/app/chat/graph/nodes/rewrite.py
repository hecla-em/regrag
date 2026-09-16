"""rewrite: a follow-up restated so it can be searched without the thread behind it."""

import logging
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from app.chat.enums import ChatNode
from app.chat.graph.node import chat_model, reply_spend, traced
from app.chat.models import ChatState, ChatTurn
from app.core.llm.errors import LLMError, llm_retry, parse_model_answer, wrap_provider_errors
from app.core.models import FrozenModel

logger = logging.getLogger(__name__)

REWRITE_SYSTEM_PROMPT = (
    "You restate the latest question of a conversation about EU maritime regulation so "
    "that it can be searched on its own, without the conversation. You are shown the "
    "earlier turns, then the question. Replace pronouns and shorthand — 'it', 'that "
    "regulation', 'the penalties' — with what the earlier turns show they refer to, and "
    "carry over the act or scheme the conversation is about when the question leaves it "
    "unsaid. Never answer, and never add anything the question did not ask. A question "
    "that already stands on its own is returned unchanged."
)


def build_rewrite_message(question: str, history: Sequence[ChatTurn]) -> str:
    """The full rewrite turn: the thread as a transcript, then the question to restate."""
    transcript = "\n\n".join(f"Q: {turn.question}\nA: {turn.answer}" for turn in history)
    return f"Conversation so far:\n\n{transcript}\n\nLatest question: {question}"


class StandaloneQuestion(FrozenModel):
    """What rewrite makes of a follow-up: the question restated so that it can be
    searched on its own, naming what the thread's pronouns and shorthand referred to."""

    question: str


def rewrite_model() -> Runnable:
    """The rewrite model as rewrite calls it: one blocking turn, answering in the
    StandaloneQuestion shape."""
    return chat_model(streaming=False).bind(response_format=StandaloneQuestion)


@llm_retry
@wrap_provider_errors("rewrite call")
async def call_rewrite_model(state: ChatState) -> dict[str, Any]:
    """One model turn restating the follow-up so it can be searched on its own; an answer
    off the schema is a failed call."""
    messages = [
        SystemMessage(REWRITE_SYSTEM_PROMPT),
        HumanMessage(build_rewrite_message(state.question, state.history)),
    ]
    response = await rewrite_model().ainvoke(messages)
    restated = parse_model_answer(StandaloneQuestion, response.text, label=ChatNode.REWRITE)
    return {"standalone_question": restated.question, **reply_spend(response)}


@traced
async def rewrite(state: ChatState) -> dict[str, Any]:
    """The follow-up restated for retrieval — or left as asked when the call fails, which
    costs the restatement rather than the request."""
    try:
        return await call_rewrite_model(state)
    except LLMError as exc:
        logger.warning("rewrite call failed, searching the question as asked: %s", exc)
        return {"standalone_question": ""}
