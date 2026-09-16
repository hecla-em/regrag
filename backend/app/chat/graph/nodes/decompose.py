"""decompose: a multi-part question split into the separate searches it needs."""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from app.chat.enums import ChatNode
from app.chat.graph.node import chat_model, traced
from app.chat.models import ChatState
from app.core.config import config
from app.core.llm.errors import LLMError, llm_retry, parse_model_answer, wrap_provider_errors
from app.core.models import FrozenModel

logger = logging.getLogger(__name__)

DECOMPOSE_SYSTEM_PROMPT = (
    "You split a question about EU maritime regulation into the separate searches it "
    "needs, one per distinct thing it asks. A question asking one thing, however long, "
    "is one query: return it unchanged. Split only when the parts would be answered by "
    "different provisions; never split a single obligation into its conditions, and "
    "never rephrase, narrow or expand what was asked. Each query must stand alone, "
    "naming the act or scheme the question names, so that searching it without the "
    "others finds the right provision."
)


class DecomposedQuestion(FrozenModel):
    """What decompose splits a question into: one search query per thing it asks, in the
    order asked. One query means the question asked one thing."""

    queries: tuple[str, ...]


def decompose_model() -> Runnable:
    """The decompose model as decompose calls it: one blocking turn, answering in the
    DecomposedQuestion shape."""
    return chat_model(streaming=False).bind(response_format=DecomposedQuestion)


@llm_retry
@wrap_provider_errors("decompose call")
async def call_decompose_model(state: ChatState) -> dict[str, Any]:
    """One model turn splitting the question into the searches it needs, capped to the
    parts allowed. One part means the question asked one thing, and queries stays empty
    so retrieve searches the question as asked; an answer off the schema is a failed call."""
    messages = [SystemMessage(DECOMPOSE_SYSTEM_PROMPT), HumanMessage(state.retrieval_question)]
    response = await decompose_model().ainvoke(messages)
    split = parse_model_answer(DecomposedQuestion, response.text, label=ChatNode.DECOMPOSE)
    queries = split.queries[: config.DECOMPOSE_MAX_PARTS]
    return {"queries": queries if len(queries) > 1 else (), "reply": response}


@traced
async def decompose(state: ChatState) -> dict[str, Any]:
    """The question split into its parts, or left whole when it has one — or when the
    call fails, which costs the split rather than the request."""
    try:
        return await call_decompose_model(state)
    except LLMError as exc:
        logger.warning("decompose call failed, searching the question as asked: %s", exc)
        return {"queries": ()}
