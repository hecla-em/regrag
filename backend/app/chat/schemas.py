"""Chat request tracking: one row per handled question, the ledger a spend cap sums over,
and one row per step it ran through."""

import uuid

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.chat.enums import ChatOutcome
from app.core.db.schema import BaseSchema


class ChatRequest(BaseSchema):
    """One handled question: its thread, how it ended, its answer, how long it lived, what it cost
    and which model it called, and what failed; its path is in chat_request_steps. The index
    serves the spend cap's window."""

    __tablename__ = "chat_requests"
    __table_args__ = (Index("ix_chat_requests_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str | None]
    question: Mapped[str]
    thread_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    answer: Mapped[str | None]
    outcome: Mapped[ChatOutcome]
    model: Mapped[str | None]
    total_ms: Mapped[int]
    sources: Mapped[int]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    cost_usd: Mapped[float | None]
    error: Mapped[str | None]

    steps: Mapped[list["ChatRequestStep"]] = relationship(
        cascade="all, delete-orphan", order_by="ChatRequestStep.position"
    )


class ChatRequestStep(BaseSchema):
    """One step of a request's path: which node or tool call, in what order, how long it
    took, and if it called a model: the tokens, what they cost, and the model they went to."""

    __tablename__ = "chat_request_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_request_id: Mapped[int] = mapped_column(
        ForeignKey("chat_requests.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    step: Mapped[str]
    ms: Mapped[int]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    cost_usd: Mapped[float | None]
    model: Mapped[str | None]
