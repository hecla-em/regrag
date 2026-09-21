"""The refusal gate's bars: the best of each present signal, judged at call time."""

import pytest

from app.core.config import config
from app.retrieval.thresholds import meets_thresholds
from tests.conftest import search_result

COSINE_BAR = 0.4
RELEVANCE_BAR = 0.6


@pytest.fixture
def bars(monkeypatch):
    """Bars set away from their defaults, so a gate that read config at import fails here."""
    monkeypatch.setattr(config, "MIN_COSINE_SIMILARITY", COSINE_BAR)
    monkeypatch.setattr(config, "MIN_RERANKER_RELEVANCE", RELEVANCE_BAR)


@pytest.mark.parametrize(
    ("signals", "verdict"),
    [
        pytest.param([(0.5, 0.7)], True, id="both clear"),
        pytest.param([(0.2, 0.7)], False, id="cosine low"),
        pytest.param([(0.5, 0.3)], False, id="relevance low"),
        pytest.param([(0.35, 0.7)], False, id="cosine clears the default bar but not this one"),
        pytest.param([(0.5, 0.5)], False, id="relevance clears the default bar but not this one"),
        pytest.param([(0.5, None)], True, id="unjudged"),
        pytest.param([(None, 0.7)], True, id="text-only hit"),
        pytest.param([(None, None)], True, id="no signals"),
        pytest.param([], False, id="nothing found"),
        pytest.param([(0.2, 0.7), (0.5, 0.3)], True, id="best of each signal, not the top hit's"),
    ],
)
def test_met_when_the_best_of_each_present_signal_clears_its_bar(signals, verdict, bars):
    hits = tuple(
        search_result(cosine_similarity=cosine, reranker_relevance=relevance)
        for cosine, relevance in signals
    )

    assert meets_thresholds(hits) is verdict
