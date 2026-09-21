"""Tune values: the curated-param model's drift gate and its override window."""

from contextlib import suppress
from typing import Any

import pytest

from app.core.config import config
from app.evals.tune.models import TunableParam


@pytest.mark.parametrize(
    "param",
    [
        pytest.param({"name": "RENAMED_AWAY", "values": (1,)}, id="a renamed setting"),
        pytest.param({"name": "CHAT_SOURCES", "values": (0,)}, id="an out-of-range value"),
        pytest.param(
            {"name": "MAX_CHARS", "values": (1000,)},
            id="a live setting a run's snapshot does not record",
        ),
        pytest.param(
            {"name": "CHAT_CONTEXT_CHUNKS", "values": (10,), "requires": {"RENAMED_AWAY": True}},
            id="a renamed companion",
        ),
        pytest.param(
            {"name": "CHAT_CONTEXT_CHUNKS", "values": (10,), "requires": {"CHAT_SOURCES": 0}},
            id="an out-of-range companion value",
        ),
    ],
)
def test_a_param_that_no_longer_fits_the_config_fails_before_any_run(param: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        TunableParam(**param).validate_config()


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(None, id="when the block ends"),
        pytest.param(RuntimeError("boom"), id="even when the block raises"),
    ],
)
def test_override_applies_a_value_and_its_companions_then_restores_them(
    error: Exception | None,
) -> None:
    before = (config.CHAT_CONTEXT_CHUNKS, config.EXPAND_SECTIONS)
    chunks, expand = before[0] + 5, not before[1]
    param = TunableParam(
        name="CHAT_CONTEXT_CHUNKS", values=(chunks,), requires={"EXPAND_SECTIONS": expand}
    )

    with suppress(RuntimeError), param.override(chunks):
        applied = (config.CHAT_CONTEXT_CHUNKS, config.EXPAND_SECTIONS)
        if error:
            raise error

    assert applied == (chunks, expand)
    assert (config.CHAT_CONTEXT_CHUNKS, config.EXPAND_SECTIONS) == before
