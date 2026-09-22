"""What the chat ledger measured over a range: the headline summary, each step, and the
questions asked most."""

from datetime import datetime

from app.chat.enums import ChatOutcome
from app.core.models import FrozenModel


class CostSummary(FrozenModel):
    """mean_usd: per generated answer in range. range_usd: every request in range. total_usd:
    every request the ledger still keeps, from the summary's kept_since."""

    mean_usd: float | None
    range_usd: float
    total_usd: float


class LatencySummary(FrozenModel):
    """How long a generated answer took, over the range."""

    mean_ms: int | None
    p50_ms: int | None
    p95_ms: int | None


class ChatSummary(FrozenModel):
    """The range's requests by how they ended, and what the generated answers cost and took.
    A cached answer adds nothing to either. kept_since: the oldest request kept."""

    outcomes: dict[ChatOutcome, int]
    cost: CostSummary
    latency: LatencySummary
    kept_since: datetime | None


class StepMetrics(FrozenModel):
    """One node or tool call over the range's requests: how often it ran, what it took and
    what it cost. Cost is over the runs that called a model."""

    step: str
    runs: int
    mean_ms: int
    mean_cost_usd: float | None


class GraphEdge(FrozenModel):
    """conditional: the edge is one a routing function may take, not one always taken."""

    source: str
    target: str
    conditional: bool


class ChatGraphMetrics(FrozenModel):
    """The compiled graph's nodes and edges, and what each step measured over the range."""

    nodes: tuple[str, ...]
    edges: tuple[GraphEdge, ...]
    steps: tuple[StepMetrics, ...]


class TopQuestion(FrozenModel):
    """A first question as the answer cache folds it, in the words it was last asked in."""

    question: str
    asked: int
    cached: int
    last_asked: datetime
