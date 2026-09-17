"""The per-case lines `evals run --verbose` adds, and what `evals compare` prints."""

from app.evals.judge.enums import JudgeVerdict
from app.evals.report import format_case_lines, format_run_comparison
from tests.evals.conftest import (
    assess_refused_result,
    eval_case,
    eval_result,
    failed_judgement,
    judged_metrics,
    out_of_corpus_case,
    passed_judgement,
    refusal_judgement,
    refused_result,
    stored_run,
)


def test_a_case_line_shows_what_it_retrieved_what_it_cited_and_how_it_ended():
    [line] = format_case_lines((eval_result(),))

    assert line.startswith("case")
    assert "raw 1.00" in line
    assert "exp 1.00" in line
    assert "cite 1.00" in line
    assert "corr    -" in line
    assert "faith    -" in line
    assert "done" in line
    assert "1000ms" in line


def test_a_case_with_nothing_to_recall_prints_dashes_rather_than_zeroes():
    """An out-of-corpus case authors no reference, so its recall is unmeasured; a 0.00
    would read as a retrieval failure on a case that has nothing to retrieve."""
    [line] = format_case_lines((refused_result(),))

    assert "raw    -" in line
    assert "cite    -" in line
    assert "refused" in line


def test_a_case_the_graph_raised_on_scores_nothing_and_is_named_with_its_error():
    """The aggregate leaves an errored case out, so its line must not show scores either."""
    [line] = format_case_lines((eval_result(eval_case(id="boom"), error="TimeoutError"),))

    assert line.startswith("boom")
    assert "raw    -" in line
    assert "error" in line
    assert line.rstrip().endswith("TimeoutError")


def test_the_case_column_is_sized_to_the_longest_id_in_the_run():
    """The ids run from 13 to 44 characters, so a fixed column either wraps or wastes."""
    lines = format_case_lines(
        (eval_result(eval_case(id="short")), eval_result(eval_case(id="a" * 40)))
    )

    assert [line.index("raw") for line in lines] == [42, 42]


def test_a_judged_case_shows_its_scores_and_a_pass_stays_on_one_line():
    [line] = format_case_lines((eval_result(judgement=passed_judgement()),))

    assert "corr 1.00" in line
    assert "faith 1.00" in line


def test_a_case_the_judge_failed_prints_why_beneath_it():
    line, correctness, faithfulness, unsupported = format_case_lines(
        (eval_result(judgement=failed_judgement()),)
    )

    assert "corr 0.00" in line
    assert "faith 0.50" in line
    assert (
        correctness
        == "    correctness fail (wrong_figure): says all of it, the reference says half"
    )
    assert faithfulness == "    faithfulness 0.50: the 5,000 GT threshold is not in the cited block"
    assert unsupported == "    unsupported: ships above 5,000 GT"


def test_an_answer_that_did_not_decline_prints_the_judges_reason():
    result = eval_result(out_of_corpus_case(), judgement=refusal_judgement(JudgeVerdict.FAIL))

    line, refusal = format_case_lines((result,))

    assert "corr    -" in line
    assert refusal == "    refusal fail: says the corpus lacks it"


def test_a_split_case_shows_its_queries_beneath_it():
    result = eval_result(queries=("what is A", "what is B"))

    line, split = format_case_lines((result,))

    assert split == "    split: what is A | what is B"


def test_an_unsplit_case_prints_no_split_line():
    [line] = format_case_lines((eval_result(),))

    assert "split:" not in line


def test_a_case_assess_refused_shows_its_explanation_beneath_it():
    """Runs persist nothing, so the report is the one place a wrongful refusal is read."""
    line, explanation = format_case_lines((assess_refused_result(),))

    assert "refused" in line
    assert explanation == "    refused: no block concerns the question"


def test_a_gate_refusal_prints_no_explanation_line():
    """It has none to print: the gate asked no model."""
    [line] = format_case_lines((refused_result(),))

    assert "refused:" not in line


# Two stored runs side by side


def comparison_line(output: str, name: str) -> list[str]:
    [line] = [line for line in output.splitlines() if line.split()[:1] == [name]]
    return line.split()


def test_a_comparison_heads_each_run_with_its_origin():
    output = format_run_comparison(stored_run(42), stored_run(41, git_dirty=True))

    assert "#42  2026-09-18 03:00  12265d6  anthropic/claude-haiku-4-5" in output
    assert "#41  2026-09-18 03:00  12265d6 (dirty)  anthropic/claude-haiku-4-5" in output


def test_a_comparison_marks_the_run_that_had_retrieval_off():
    output = format_run_comparison(stored_run(42), stored_run(43, retrieval=False))

    assert "#42  2026-09-18 03:00  12265d6  anthropic/claude-haiku-4-5\n" in output
    assert "#43  2026-09-18 03:00  12265d6  anthropic/claude-haiku-4-5  no retrieval" in output


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


def test_a_comparison_keeps_the_metric_blocks_in_order_whatever_order_jsonb_returned():
    """JSONB sorts keys by length, so the stored dict is read back through EvalMetrics."""
    run = stored_run(42)
    run.metrics = dict(reversed(run.metrics.items()))

    output = format_run_comparison(run, stored_run(41))

    rows = output.split("\n\n")[1].splitlines()
    assert rows[1].split()[0] == "counts.cases"


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


def test_identical_settings_print_no_settings_block():
    assert "settings that differ" not in format_run_comparison(stored_run(42), stored_run(41))


def test_a_run_stored_before_a_metric_existed_still_compares():
    older = stored_run(41)
    older.metrics = {**older.metrics, "judge": {"judged": 1, "retired_metric": 0.5}}

    output = format_run_comparison(stored_run(42), older)

    assert comparison_line(output, "judge.correctness") == ["judge.correctness", "1.000", "-"]
    assert comparison_line(output, "judge.retired_metric") == ["judge.retired_metric", "-", "0.500"]
