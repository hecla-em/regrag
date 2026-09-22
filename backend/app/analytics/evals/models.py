"""The stored eval runs, and the settings the server runs with."""

from datetime import datetime
from typing import Any

from app.core.models import FrozenModel
from app.evals.dataset.models import CaseSelection


class EvalRunSummary(FrozenModel):
    """One stored eval run, as the page compares them: when it ran, the code, models and
    settings it scored, and its metrics. metrics is the stored EvalMetrics as JSON rather than
    the model, so a run stored before a metrics block changed still lists, as it still
    compares. metrics.usage.cost_usd sums the chat graph's calls over every case, judge
    apart, while the live FAQs cost leaves out cached answers: the two are not one measure."""

    id: int
    created_at: datetime
    git_commit: str | None
    git_dirty: bool
    model: str
    judge_model: str | None
    dataset_sha: str
    corpus_version: str | None
    cached: bool
    judged: bool
    retrieval: bool
    selection: CaseSelection
    stale_cases: tuple[str, ...]
    settings: dict[str, Any]
    metrics: dict[str, Any]


class EvalSettings(FrozenModel):
    """The settings the server is running with right now, as a stored run records them, so
    the page can mark the run that matches prod and show where the others differ."""

    build_id: str
    settings: dict[str, Any]
