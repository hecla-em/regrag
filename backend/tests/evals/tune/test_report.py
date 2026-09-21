"""The tune table: ranked rows, read against the baseline."""

import pytest

from app.evals.tune.models import TuneResult
from app.evals.tune.report import format_tune_table
from tests.evals.tune.conftest import metrics, tune_run

BETTER = TuneResult(
    param="CHAT_SOURCES",
    value=8,
    metrics=metrics(expanded_recall=1.0, mean_context_chunks=17.1, mean_context_chars=34200.0),
)
WORSE = TuneResult(
    param="CHAT_SOURCES",
    value=3,
    metrics=metrics(expanded_recall=0.87, mean_context_chunks=10.4, mean_context_chars=20600.0),
)
SAME_BUT_CHEAPER = TuneResult(
    param="CHAT_CONTEXT_CHUNKS",
    value=10,
    metrics=metrics(mean_context_chunks=10.0, mean_context_chars=19800.0),
)
UNMEASURED = TuneResult(
    param="RERANK_ENABLED",
    value=False,
    metrics=metrics(mean_context_chunks=None, mean_context_chars=None, mean_step_ms={}),
)
"""A result every case errored under, which measures nothing."""

BASELINE = ["(baseline)", "-", "412"]


@pytest.mark.parametrize(
    ("results", "ranked"),
    [
        pytest.param(
            [WORSE, BETTER],
            [["CHAT_SOURCES", "8", "412"], BASELINE, ["CHAT_SOURCES", "3", "412"]],
            id="the best recall ranks first",
        ),
        pytest.param(
            [SAME_BUT_CHEAPER],
            [["CHAT_CONTEXT_CHUNKS", "10", "412"], BASELINE],
            id="identical recall is won by the cheaper context",
        ),
        pytest.param(
            [UNMEASURED],
            [BASELINE, ["RERANK_ENABLED", "False", "-"]],
            id="an unmeasured cost ranks after any measured one, as nothing is not cheap",
        ),
    ],
)
def test_rows_rank_by_expanded_recall_then_by_the_cheaper_context(
    results: list[TuneResult], ranked: list[list[str]]
) -> None:
    """Each row is read as its param, its value and its retrieve time, the last column."""
    table = format_tune_table(tune_run(*results))

    rows = [line.split() for line in table.splitlines()[1 : len(ranked) + 1]]
    assert [[*row[1:3], row[-1]] for row in rows] == ranked
