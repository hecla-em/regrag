"""Eval run tracking: one row per stored run, its setup and what it measured."""

from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.schema import BaseSchema


class EvalRun(BaseSchema):
    """One stored eval run: the code, models and dataset it scored, and its EvalMetrics.
    Settings and metrics are JSONB, since their shape grows with the config and the metrics."""

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    git_commit: Mapped[str | None]
    git_dirty: Mapped[bool]
    model: Mapped[str]
    judge_model: Mapped[str | None]
    dataset_sha: Mapped[str]
    corpus_version: Mapped[str | None]
    cached: Mapped[bool]
    judged: Mapped[bool]
    selection: Mapped[dict[str, Any]] = mapped_column(JSONB)
    stale_cases: Mapped[list[str]] = mapped_column(JSONB)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
