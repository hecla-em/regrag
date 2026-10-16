"""clarify: the question back to the reader, in place of an answer, when a name in the
question could mean several companies or ships."""

from typing import Any

from app.chat.graph.node import traced
from app.chat.models import ChatState, Clarification


def format_clarification(clarification: Clarification) -> str:
    """The question followed by its options as a markdown list, so thread history and rewrite
    see what was offered, not only what was asked."""
    options = "\n".join(f"- {option}" for option in clarification.options)
    return f"{clarification.question}\n\n{options}"


@traced
async def clarify(state: ChatState) -> dict[str, Any]:
    """The question and its options, as the turn's answer, so the thread's next turn can
    resolve a typed reply like 'the second one'."""
    if state.clarification is None:
        return {"answer": ""}
    return {"answer": format_clarification(state.clarification)}
