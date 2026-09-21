"""Tune values: the curated-param model's drift gate and its override window."""

import pytest
from pydantic import ValidationError

from app.core.config import config
from app.evals.tune.models import TunableParam


def test_a_renamed_setting_fails_the_drift_gate() -> None:
    with pytest.raises(ValueError, match="no longer a config field"):
        TunableParam(name="RENAMED_AWAY", values=(1,)).validate_config()


def test_an_out_of_range_value_fails_before_any_run() -> None:
    with pytest.raises(ValidationError):
        TunableParam(name="CHAT_SOURCES", values=(0,)).validate_config()


def test_override_applies_and_restores_the_setting() -> None:
    baseline = config.CHAT_SOURCES
    param = TunableParam(name="CHAT_SOURCES", values=(baseline + 3,))

    with param.override(baseline + 3):
        assert config.CHAT_SOURCES == baseline + 3

    assert config.CHAT_SOURCES == baseline


def test_override_restores_even_when_the_block_raises() -> None:
    baseline = config.CHAT_SOURCES
    param = TunableParam(name="CHAT_SOURCES", values=(baseline + 3,))

    with pytest.raises(RuntimeError):
        with param.override(baseline + 3):
            raise RuntimeError("boom")

    assert config.CHAT_SOURCES == baseline


def test_a_setting_a_run_does_not_record_fails_the_gate() -> None:
    """MAX_CHARS is a live config field, but outside the sections a run snapshots, so the
    report could not print its baseline."""
    with pytest.raises(ValueError, match="does not record"):
        TunableParam(name="MAX_CHARS", values=(1000,)).validate_config()


def test_override_applies_and_restores_the_companions_a_param_requires() -> None:
    baseline_expand = config.EXPAND_SECTIONS
    baseline_chunks = config.CHAT_CONTEXT_CHUNKS
    param = TunableParam(
        name="CHAT_CONTEXT_CHUNKS",
        values=(baseline_chunks + 5,),
        requires={"EXPAND_SECTIONS": not baseline_expand},
    )

    with param.override(baseline_chunks + 5):
        assert config.EXPAND_SECTIONS is (not baseline_expand)
        assert config.CHAT_CONTEXT_CHUNKS == baseline_chunks + 5

    assert config.EXPAND_SECTIONS is baseline_expand
    assert config.CHAT_CONTEXT_CHUNKS == baseline_chunks


def test_a_companion_no_longer_a_config_field_fails_the_gate() -> None:
    param = TunableParam(name="CHAT_CONTEXT_CHUNKS", values=(10,), requires={"RENAMED_AWAY": True})

    with pytest.raises(ValueError, match="no longer a config field"):
        param.validate_config()


def test_an_out_of_range_companion_value_fails_before_any_run() -> None:
    param = TunableParam(name="CHAT_CONTEXT_CHUNKS", values=(10,), requires={"CHAT_SOURCES": 0})

    with pytest.raises(ValidationError):
        param.validate_config()
