"""synthesize: one streamed model call answering from the context with [n] citations, or
from memory when there is no context."""

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.chat.blocks import ContextBlock
from app.chat.graph.node import chat_model, traced
from app.chat.models import ChatState
from app.chat.prompts import format_context, system_prompt, thread_messages
from app.core.config import config
from app.core.llm.errors import llm_retry, wrap_provider_errors

ROLE = "You are RegRag, an assistant answering questions about EU maritime regulation. "

STYLE = (
    "Start directly with the answer: no title, no restating the question, and no "
    "preamble such as 'Based on the regulations'. A yes-or-no question gets its yes or "
    "no in the first sentence, then the reason. Say only what the question asks, in as "
    "few sentences as it takes: one for a fact, a short paragraph for a rule with its "
    "conditions, a table for figures. Leave out every passage that does not bear on the "
    "question, however close its subject; never summarise the passages for their own "
    "sake. When several acts give the same answer, give it once and name the acts it "
    "holds for, then note only where they differ. "
)

UNCOVERED = (
    "The reader sees only your answer, so when the passages leave something unanswered, "
    "call them 'the passages I found', as in 'The passages I found from Regulation (EU) "
    "2023/1805 do not set a deadline for…' or 'Article 3 of Directive 2003/87/EC is not among "
    "the passages I found'. Say so only of a part of what the question asks that no block "
    "answers, in one sentence, then answer the part the blocks do settle; never of a term, "
    "an identifier or a figure the answer does not need. "
)

TABLES = (
    "When you give more than a couple of rows from a passage's table, give them as a "
    "markdown table and cite it in the sentence that introduces it. "
)

SYSTEM_PROMPT = (
    f"{ROLE}"
    "Answer using only the numbered passages of regulation text you are shown. A block may "
    "instead hold figures from the THETIS-MRV public dataset; cite it by its number like "
    "any passage and say which figures you used. When the question needs a figure worked out "
    "from them, such as a share, a difference or a phase-in percentage applied, do the sum and "
    "show it. The figure to be reported under Directive 2003/87/EC is the emissions under the "
    "EU ETS; what is surrendered for a year, which is also a company's ETS exposure, is the "
    "block's surrendered-for line, so quote it rather than working it out; that line is "
    "worked out from the dataset, not a column of it. Cite every "
    "claim inline with the marker of the passage it comes from, like [1] or [2][3], placed "
    "after the punctuation that ends the claim (e.g. 'must be reported.[1]'), never before "
    "it. If the passages do not answer the question, say so plainly instead of guessing. "
    f"{UNCOVERED}"
    f"{TABLES}"
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


def build_user_message(question: str, sources: Sequence[ContextBlock]) -> str:
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
