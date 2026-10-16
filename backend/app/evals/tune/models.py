"""Tune values: a configuration under test, one value's measurement, and the whole run."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from pydantic import Field

from app.core.config import EVAL_CONFIG_SECTIONS, Config, config
from app.core.models import FrozenModel
from app.evals.dataset.models import CaseSelection
from app.evals.models import EvalMetrics


class TunableParam(FrozenModel):
    """A config parameter, the values to test for it, and the companion settings it is
    only read under — a gated knob is measured with its companions applied."""

    name: str
    values: tuple[Any, ...]
    requires: dict[str, Any] = Field(default_factory=dict)

    def validate_config(self) -> None:
        recorded = {name for section in EVAL_CONFIG_SECTIONS for name in section.model_fields}
        for name in (self.name, *self.requires):
            if name not in Config.model_fields:
                raise ValueError(f"{name} is no longer a config field; update TUNABLE_PARAMS")
            if name not in recorded:
                raise ValueError(
                    f"{name} is a setting the run's snapshot does not record; "
                    "tune only over the EVAL_CONFIG_SECTIONS fields"
                )

        probe = config.model_copy()
        for name, value in self.requires.items():
            setattr(probe, name, value)
        for value in self.values:
            setattr(probe, self.name, value)

    @contextmanager
    def override(self, value: Any) -> Generator[None, None, None]:
        """Temporarily apply a value to this parameter, and its required companions."""
        applied = {**self.requires, self.name: value}
        previous = {name: getattr(config, name) for name in applied}

        try:
            for name, new_value in applied.items():
                setattr(config, name, new_value)
            yield
        finally:
            for name, old_value in previous.items():
                setattr(config, name, old_value)


class TuneResult(FrozenModel):
    """The result of trying one value for one config parameter."""

    param: str
    value: Any
    requires: dict[str, Any] = Field(default_factory=dict)
    metrics: EvalMetrics


class TuneRun(FrozenModel):
    """A complete tuning run against a fixed baseline configuration."""

    dataset_sha: str
    selection: CaseSelection = CaseSelection()
    cached: bool = False
    settings: dict[str, Any]
    baseline: EvalMetrics
    results: tuple[TuneResult, ...] = Field(default_factory=tuple)
