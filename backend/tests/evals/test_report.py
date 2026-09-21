"""The per-case lines `evals run --verbose` adds, and what `evals compare` prints."""

from app.evals.report import format_run_comparison
from tests.evals.conftest import (
    judged_metrics,
    stored_run,
)

# Two stored runs side by side


def comparison_line(output: str, name: str) -> list[str]:
    [line] = [line for line in output.splitlines() if line.split()[:1] == [name]]
    return line.split()


def test_a_comparison_lists_every_metric_by_its_path_with_the_delta():
    base = judged_metrics()
    other = base.model_copy(
        update={
            "judge": base.judge.model_copy(update={"judged": 3, "correctness": 0.7}),
            "latency": base.latency.model_copy(
                update={"mean_step_ms": {**base.latency.mean_step_ms, "rewrite": 300}}
            ),
        }
    )

    output = format_run_comparison(stored_run(42, base), stored_run(41, other))

    assert comparison_line(output, "metric") == ["metric", "#42", "#41", "delta"]
    assert comparison_line(output, "judge.correctness") == [
        "judge.correctness",
        "1.000",
        "0.700",
        "-0.300",
    ]
    assert comparison_line(output, "judge.judged") == ["judge.judged", "1", "3", "+2"]
    assert comparison_line(output, "gate.refusal_rate") == ["gate.refusal_rate", "-", "-"]
    assert comparison_line(output, "latency.mean_step_ms.rewrite") == [
        "latency.mean_step_ms.rewrite",
        "-",
        "300",
    ]


def test_a_comparison_names_only_the_settings_that_differ():
    other = stored_run(
        41,
        settings={"CHAT_MODEL": "anthropic/claude-haiku-4-5", "CHAT_THINKING_ENABLED": False},
    )

    output = format_run_comparison(stored_run(42), other)

    assert "settings that differ:" in output
    assert comparison_line(output, "CHAT_THINKING_ENABLED") == [
        "CHAT_THINKING_ENABLED",
        "true",
        "false",
    ]
    assert "CHAT_MODEL " not in output


def test_a_run_stored_before_a_metric_existed_still_compares():
    older = stored_run(41)
    older.metrics = {**older.metrics, "judge": {"judged": 1, "retired_metric": 0.5}}

    output = format_run_comparison(stored_run(42), older)

    assert comparison_line(output, "judge.correctness") == ["judge.correctness", "1.000", "-"]
    assert comparison_line(output, "judge.retired_metric") == ["judge.retired_metric", "-", "0.500"]
