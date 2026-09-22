"""Chat enumerations."""

from enum import StrEnum


class ChatNode(StrEnum):
    """The graph's nodes, as astream keys their updates."""

    REWRITE = "rewrite"
    DECOMPOSE = "decompose"
    RETRIEVE = "retrieve"
    ASSESS = "assess"
    ASSESS_TOOLS = "assess_tools"
    SYNTHESIZE = "synthesize"
    REFUSE = "refuse"


class ToolStep(StrEnum):
    """The tool calls a path records, prefixed so one column holds both these and the
    graph's nodes without either being read for the other."""

    SEARCH = "tool_search"
    FOLLOW_REFERENCE = "tool_follow_reference"
    MRV_FIGURES = "tool_mrv_figures"
    REFUSE = "tool_refuse"
    UNKNOWN = "tool_unknown"
    """A call to a tool the surface does not have, kept in the path because a model asking
    for one is worth seeing, and because a round that ran must leave a step behind."""


class ChatStepStatus(StrEnum):
    """Where a step is: announced as it starts, then reported again once it has finished."""

    RUNNING = "running"
    COMPLETED = "completed"


class ChatEventName(StrEnum):
    """The events a chat stream carries, as the SSE frames name them."""

    SOURCES = "sources"
    STEP = "step"
    TEXT = "text"
    DONE = "done"
    ERROR = "error"


class ChatOutcome(StrEnum):
    """How a chat stream ended: done, served from the cache, refused before any model call, an
    error event, or the client leaving first. An ERROR run's timings stop at the error."""

    DONE = "done"
    CACHED = "cached"
    REFUSED = "refused"
    ERROR = "error"
    ABORTED = "aborted"


class RefusalReason(StrEnum):
    """Why a question ended in the fixed refusal rather than an answer: search found
    nothing that cleared the gate, or assess read what it found and none of it bore on the
    question."""

    NOTHING_RETRIEVED = "nothing_retrieved"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class Vote(StrEnum):
    """Which way a reader voted on the answer they were given."""

    UP = "up"
    DOWN = "down"


ANSWERED_OUTCOMES = frozenset({ChatOutcome.DONE, ChatOutcome.CACHED})
"""The outcomes that left an answer on the thread: what a follow-up's history reads."""


class ChatErrorCode(StrEnum):
    """The names chat reports its own refusals under, beside core's ErrorCode."""

    SPEND_CAP_REACHED = "SpendCapReachedError"
    THREAD_FULL = "ThreadFullError"
