"""Chat run state: what the stats line may carry, and when the context is final."""

import json

import pytest

from app.chat.enums import ChatNode, RefusalReason, ToolStep
from app.chat.models import ChatState, ChatStepResult, ChatTurn, Refusal
from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.service import build_call_step
from app.core.config import config
from tests.conftest import reply_message, search_result


def test_log_fields_count_what_was_found_and_leave_every_piece_of_content_out():
    """A tool step's subject is the query the model wrote from the question: content, so
    the line keeps the step and its timing and drops that."""
    search = ToolCall(name="search", args={"query": "penalties for a missing monitoring plan"})
    state = ChatState(
        question="What must ships report?",
        history=(ChatTurn(question="What is FuelEU?", answer="A regulation."),),
        standalone_question="What must ships report under FuelEU?",
        queries=("first part", "second part"),
        hits=(search_result(), search_result(id=2)),
        sources=(search_result(),),
        steps=(build_call_step(search, ms=80),),
        answer="Ships must report [1].",
    )

    fields = state.log_fields()

    assert (fields["hits"], fields["sources"], fields["queries"]) == (2, 1, 2)
    assert fields["thread_id"] == str(state.thread_id)
    assert fields["steps"] == [{"step": "tool_search", "ms": 80, "usage": None, "model": None}]
    logged = json.dumps(fields)
    for content in (
        state.question,
        state.history[0].answer,
        state.standalone_question,
        state.queries[0],
        search.args["query"],
        search_result().text,
        state.answer,
    ):
        assert content not in logged


def visited(*steps: ChatNode | ToolStep) -> tuple[ChatStepResult, ...]:
    return tuple(ChatStepResult(step=step, ms=1) for step in steps)


SOURCES = (search_result(),)
RETRIEVED = visited(ChatNode.RETRIEVE)
ASSESSED = visited(ChatNode.RETRIEVE, ChatNode.ASSESS)
SEARCHED = visited(ChatNode.RETRIEVE, ChatNode.ASSESS, ToolStep.SEARCH)
REFUSED = visited(ChatNode.RETRIEVE, ChatNode.ASSESS, ToolStep.REFUSE)


@pytest.mark.parametrize(
    ("state", "settings", "settled"),
    [
        pytest.param({}, {}, False, id="nothing has run yet"),
        pytest.param(
            {"steps": RETRIEVED, "sources": SOURCES},
            {"ASSESS_ENABLED": True},
            False,
            id="after retrieve with the loop on, assess still runs",
        ),
        pytest.param(
            {"steps": RETRIEVED, "sources": SOURCES},
            {"ASSESS_ENABLED": False},
            True,
            id="after retrieve with the loop off",
        ),
        pytest.param(
            {"steps": RETRIEVED},
            {"ASSESS_ENABLED": True},
            True,
            id="after a gated retrieve, settled for the refusal",
        ),
        pytest.param(
            {
                "steps": ASSESSED,
                "sources": SOURCES,
                "pending_calls": (ToolCall(name="search", args={"query": "penalties"}),),
            },
            {},
            False,
            id="assess asked for tools",
        ),
        pytest.param(
            {"steps": ASSESSED, "sources": SOURCES}, {}, True, id="assess asked for nothing"
        ),
        pytest.param(
            {"steps": SEARCHED, "sources": SOURCES},
            {"ASSESS_MAX_ROUNDS": 2},
            False,
            id="a tool round below the round cap",
        ),
        pytest.param(
            {"steps": SEARCHED, "sources": SOURCES},
            {"ASSESS_MAX_ROUNDS": 1},
            True,
            id="a tool round that used the last round",
        ),
        pytest.param(
            {
                "steps": REFUSED,
                "sources": SOURCES,
                "refusal": Refusal(reason=RefusalReason.INSUFFICIENT_CONTEXT),
            },
            {"ASSESS_MAX_ROUNDS": 3},
            True,
            id="a refuse call, whatever the budget left",
        ),
    ],
)
def test_the_context_is_settled_once_nothing_more_will_be_fetched(
    monkeypatch, state, settings, settled
):
    """The routing predicate the graph hangs on, and what sends the sources to the client."""
    for name, value in settings.items():
        monkeypatch.setattr(config, name, value)

    assert ChatState(question="q", **state).context_settled is settled


def test_usage_without_a_model_is_unmeasured_not_priced_at_a_guess():
    state = ChatState(
        question="q",
        steps=(ChatStepResult.from_reply(ChatNode.SYNTHESIZE, 1, reply_message(model=None)),),
    )
    usage = state.usage()
    assert usage is not None
    assert usage.cost_usd is None
