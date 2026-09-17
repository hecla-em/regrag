"""Chat query and graph state values: what a caller asks, and what one question produced."""

import operator
from typing import Annotated, Any
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage
from pydantic import Field, computed_field

from app.chat.enums import ChatNode, ChatOutcome, ChatStepStatus, RefusalReason, ToolStep
from app.chat.toolbox.models import ToolCall
from app.core.config import config
from app.core.exceptions import DomainError
from app.core.llm.models import Usage
from app.core.models import AppModel, FrozenModel
from app.retrieval.models import RetrievedChunk, SearchResult


class ChatQuery(AppModel):
    """The question a caller asks, and the thread it continues — none on a first question,
    when the server mints one and returns it on the done frame."""

    question: str = Field(min_length=1, max_length=2000)
    thread_id: UUID | None = None


class ChatStepResult(FrozenModel):
    """One step of the path — a graph node, or one tool call a round ran: what it was, how
    long it took, and what it spent and at which model if it called one. The shape the
    ledger persists per step, and the trace a run is read back from.

    status: whether the step has finished. Only the stream announces a running one; every step
        the graph appends to the path has returned, so completed is the default.
    ms: how long the step took, which a running one has not spent yet and nothing reads.
    subject: what the step was about where the step alone does not say — the query a search
        ran, the division a follow fetched. Carried to the client, not to the ledger.
    """

    step: ChatNode | ToolStep
    ms: int
    usage: Usage | None = None
    model: str | None = None
    status: ChatStepStatus = ChatStepStatus.COMPLETED
    subject: str | None = None

    @classmethod
    def from_reply(cls, step: ChatNode | ToolStep, ms: int, reply: AIMessage) -> "ChatStepResult":
        """The result of a step that called a model: what the reply says it spent, priced at
        the model litellm's wrapper stamps on it, unmeasured if the provider reported none."""
        model = reply.response_metadata.get("model_name")
        usage = reply.usage_metadata
        return cls(
            step=step,
            ms=ms,
            usage=Usage.from_metadata(usage, model) if usage else None,
            model=model,
        )


class ChatTurn(FrozenModel):
    """One earlier turn of the thread as the prompts see it: what was asked, and what was
    answered with its [n] markers stripped, since they numbered that turn's context."""

    question: str
    answer: str


class Refusal(FrozenModel):
    """How a question ended when it ended without an answer: why the refusal was owed, and
    the model's words for it — empty on a gate refusal, which asked no model."""

    reason: RefusalReason
    explanation: str = ""


class CachedAnswer(FrozenModel):
    """What the answer cache keeps for a question: the answer, and the blocks its [n]
    markers number."""

    answer: str
    sources: tuple[RetrievedChunk, ...]


class ChatState(AppModel):
    """Everything one question produced, in the order it is produced: what was asked, what
    retrieval built from it, the path the graph took, and how it ended — the last including
    what only the stream's consumer knows once the graph is done, how long the request
    lived and whether it raised.

    Each field is one graph channel, since a node returns only the fields it sets and the
    graph merges them by name; they are grouped here, not nested, for that reason.

    thread_id: the thread the question belongs to, minted here when the caller sent none.
    history: the thread's earlier answered turns, oldest first; empty on a first question.
    standalone_question: the question as rewrite restated it for retrieval, or empty when
        there was nothing to restate or the call failed, so the question as asked is searched.
    queries: the searches decompose split the question into, in the order asked; empty
        when the node was skipped, found one part, or failed, so retrieve searches the
        question as asked.
    hits: what search returned, before the gate and before expansion, kept through a refusal.
    sources: the context blocks that reached the prompt, which the [n] markers number.
    retrieved_sources: how many blocks retrieve left, the base the loop's growth is budgeted
        against; sources grows each round, so the budget cannot be read off it.
    pending_calls: the tool calls assess asked for, not yet executed. Only a tool round
        starts holding any, since each round clears the calls it ran; the stream reads a
        round off that.
    steps: the path taken, each node appending its result as it returns and a tool round one
        per call; a sequence, since the loop visits a node more than once.
    refusal: why the question ended without an answer, set by the tool round that ran
        assess's refuse call, and by the refuse node itself when nothing was retrieved to
        assess; None on any run that has not refused.
    cached: whether the answer was served from the answer cache, with no graph run behind it.
    """

    # What was asked
    question: str
    thread_id: UUID = Field(default_factory=uuid4)
    history: tuple[ChatTurn, ...] = ()
    standalone_question: str = ""

    # What retrieval built
    queries: tuple[str, ...] = ()
    hits: tuple[SearchResult, ...] = ()
    sources: tuple[RetrievedChunk, ...] = ()
    retrieved_sources: int = 0
    pending_calls: tuple[ToolCall, ...] = ()

    # The path
    steps: Annotated[tuple[ChatStepResult, ...], operator.add] = ()

    # How it ended
    answer: str = ""
    refusal: Refusal | None = None
    total_ms: int | None = None
    error: str | None = None
    cached: bool = False

    @property
    def last_step(self) -> ChatNode | ToolStep | None:
        """The step that just finished — what a values update announces — or None before any."""
        return self.steps[-1].step if self.steps else None

    @property
    def retrieval_question(self) -> str:
        """What retrieval searches: the restated question when rewrite wrote one, else the
        question as asked."""
        return self.standalone_question or self.question

    def usage(self) -> Usage | None:
        """What the request spent, summed over the steps that reported usage, or None when
        none did."""
        return Usage.sum_reported(result.usage for result in self.steps)

    def called_model(self) -> str | None:
        """The model the run's steps called, or None when none asked one."""
        return next((result.model for result in self.steps if result.model), None)

    def sync_from_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Update this state with the graph's latest snapshot, so one object holds the run
        the ledger records. total_ms and error survive it: no node writes them, so no
        snapshot carries them."""
        fresh = self.model_validate(snapshot)
        for field in snapshot:
            setattr(self, field, getattr(fresh, field))

    def record_error(self, exc: Exception) -> None:
        """The run as failed: named by a DomainError's message, or the type of an unexpected
        one — what the ledger keeps, while the wire says only that something went wrong."""
        self.error = exc.message if isinstance(exc, DomainError) else type(exc).__name__

    def log_fields(self) -> dict[str, Any]:
        """The run as the stats line logs it: everything but the content — which, on a tool
        step, includes what the call was for."""
        content = (
            "question",
            "history",
            "standalone_question",
            "queries",
            "hits",
            "sources",
            "pending_calls",
            "answer",
        )
        exclude_fields: dict[str, Any] = {field: True for field in content} | {
            "steps": {"__all__": {"status", "subject"}}
        }
        fields = self.model_dump(mode="json", exclude=exclude_fields)
        return fields | {
            "hits": len(self.hits),
            "sources": len(self.sources),
            "queries": len(self.queries),
        }

    def assess_rounds(self) -> int:
        """How many times assess has asked — what the loop's budget is spent against. Read
        off assess rather than the tool steps, which number one per call, not per round."""
        return sum(1 for result in self.steps if result.step is ChatNode.ASSESS)

    @property
    def context_settled(self) -> bool:
        """Whether the context is final: retrieval ended with the loop off or the gate
        shut, assess asked for nothing, or the last round consumed the budget or refused."""
        match self.last_step:
            case ChatNode.RETRIEVE:
                return not self.sources or not config.ASSESS_ENABLED
            case ChatNode.ASSESS:
                return not self.pending_calls
            case ToolStep():
                return self.refusal is not None or self.assess_rounds() >= config.ASSESS_MAX_ROUNDS
            case _:
                return False

    @computed_field
    @property
    def outcome(self) -> ChatOutcome:
        """How the run ended, read off the error, the cache flag and the path: raised, served
        from the cache, refused, answered, or left by the client before any of them."""
        visited = {result.step for result in self.steps}
        if self.error:
            return ChatOutcome.ERROR
        if self.cached:
            return ChatOutcome.CACHED
        if ChatNode.REFUSE in visited:
            return ChatOutcome.REFUSED
        if ChatNode.SYNTHESIZE in visited:
            return ChatOutcome.DONE
        return ChatOutcome.ABORTED
