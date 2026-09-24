"""refuse: the fixed decline, in place of an answer, for a question without context."""

from typing import Any

from app.chat.enums import RefusalReason
from app.chat.graph.node import traced
from app.chat.models import ChatState, Refusal

REFUSAL_ANSWER = (
    "The corpus doesn't cover this. RegRag answers questions about the EU maritime "
    "regulation it has ingested; try asking about that."
)


@traced
async def refuse(state: ChatState) -> dict[str, Any]:
    """The fixed refusal, in place of an answer, for a question without context: assess's
    own refusal where it made one; else assess's too when a card opened the gate and the
    loop fetched nothing; else the gate's, which nothing before this node records."""
    reason = (
        RefusalReason.INSUFFICIENT_CONTEXT
        if state.matched_tools
        else RefusalReason.NOTHING_RETRIEVED
    )
    refusal = state.refusal or Refusal(reason=reason)
    return {"answer": REFUSAL_ANSWER, "refusal": refusal}
