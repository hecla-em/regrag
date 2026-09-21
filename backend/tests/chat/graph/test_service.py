"""Chat graph: the routing that ends a run in the fixed refusal rather than an answer."""

import pytest

from app.chat.enums import RefusalReason
from app.chat.graph.nodes.refuse import REFUSAL_ANSWER
from app.chat.models import Refusal
from tests.chat.conftest import recording_search, run_graph
from tests.conftest import junk_result

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "found",
    [
        pytest.param((junk_result(),), id="every hit is below the bar"),
        pytest.param((), id="search finds nothing"),
    ],
)
async def test_a_question_with_no_hit_over_the_bar_is_refused_before_any_model_call(
    answer_model, monkeypatch, found
):
    """The hits the gate judged stay on the state, so a refusal can be told from a miss:
    what search found, and how it scored, is what an eval reads a too-tight gate from."""
    requests = recording_search(monkeypatch, *found)

    state = await run_graph()

    assert state.answer == REFUSAL_ANSWER
    assert state.refusal == Refusal(reason=RefusalReason.NOTHING_RETRIEVED)
    assert (state.hits, state.sources) == (found, ())
    assert answer_model.received == []
    assert len(requests) == 1
