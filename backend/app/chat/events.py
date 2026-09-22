"""SSE event values: every frame a chat stream carries, and what each one holds."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.chat.enums import ChatErrorCode, ChatEventName, ChatNode, ChatStepStatus, ToolStep
from app.chat.models import ChatStepResult
from app.core.exceptions import ErrorCode
from app.core.models import ErrorResponse, FrozenModel
from app.ingestion import celex
from app.retrieval.models import RetrievedChunk


class ChatSource(FrozenModel):
    """One context block as the sources event reports it, binding marker to chunk."""

    marker: int
    chunk_id: int
    celex: str
    act: str
    citation: str
    title: str | None
    text: str

    @classmethod
    def from_result(cls, marker: int, result: RetrievedChunk) -> "ChatSource":
        """The event payload for one retrieved chunk at one marker position."""
        return cls(
            marker=marker,
            chunk_id=result.id,
            celex=result.celex,
            act=celex.format_act_name(result.celex, result.act_title),
            citation=result.citation,
            title=result.title,
            text=result.text,
        )


class TurnRecord(FrozenModel):
    """Where the turn was recorded: the thread it joined, which a follow-up sends back, and
    the request it was written as, which a vote names. No request outside one, as in evals."""

    thread_id: UUID
    request_id: str | None


class ChatEventBase(FrozenModel):
    """One frame of the stream: which event, and that event's data. Each event narrows
    `event` to its own name — what the union discriminates on — defaulted but always sent,
    so the schema marks it required."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    event: ChatEventName


class SourcesEvent(ChatEventBase):
    """Sent once, first: the [n] markers the answer will cite, bound to their chunks."""

    event: Literal[ChatEventName.SOURCES] = ChatEventName.SOURCES
    data: tuple[ChatSource, ...]

    @classmethod
    def from_results(cls, results: tuple[RetrievedChunk, ...]) -> "SourcesEvent":
        """Markers run 1..n in context order, matching the prompt's numbering."""
        return cls(
            data=tuple(
                ChatSource.from_result(marker, result)
                for marker, result in enumerate(results, start=1)
            )
        )


class ChatUsage(FrozenModel):
    """A step's usage as the wire carries it: the tokens, not what they cost."""

    input_tokens: int
    output_tokens: int


class ChatStep(FrozenModel):
    """One step as the step event reports it: the result, less the money."""

    step: ChatNode | ToolStep
    ms: int
    usage: ChatUsage | None = None
    model: str | None = None
    status: ChatStepStatus = ChatStepStatus.COMPLETED
    subject: str | None = None

    @classmethod
    def from_result(cls, result: ChatStepResult) -> "ChatStep":
        """The event payload for one step result."""
        usage = result.usage
        return cls(
            step=result.step,
            ms=result.ms,
            usage=ChatUsage(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
            if usage
            else None,
            model=result.model,
            status=result.status,
            subject=result.subject,
        )


class StepEvent(ChatEventBase):
    """One step of the path, sent as it starts and again as it finishes."""

    event: Literal[ChatEventName.STEP] = ChatEventName.STEP
    data: ChatStep


class TextEvent(ChatEventBase):
    """One fragment of the answer's text, as the model streams it — or the whole refusal."""

    event: Literal[ChatEventName.TEXT] = ChatEventName.TEXT
    data: str


class DoneEvent(ChatEventBase):
    """The last event of a completed stream: where the turn was recorded."""

    event: Literal[ChatEventName.DONE] = ChatEventName.DONE
    data: TurnRecord


class ChatErrorResponse(ErrorResponse):
    """The app's one error shape, narrowed to the codes a chat stream can end on."""

    error: ErrorCode | ChatErrorCode


class ErrorEvent(ChatEventBase):
    """The last event of a failed stream, in the app's one error shape."""

    event: Literal[ChatEventName.ERROR] = ChatEventName.ERROR
    data: ChatErrorResponse


ChatEvent = Annotated[
    SourcesEvent | StepEvent | TextEvent | DoneEvent | ErrorEvent, Field(discriminator="event")
]
"""Every frame a chat stream carries, told apart by its event name."""
