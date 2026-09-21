"""The tool surface: what one call adds to the context, and the step it records."""

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.chat.enums import ToolStep
from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.service import build_call_step, describe_call, run_tool_call
from app.core.llm.errors import LLMError
from tests.conftest import junk_result, search_result

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_tool_session")]

PENALTIES = ToolCall(name="search", args={"query": "penalties"})
HIT = (search_result(),)


@pytest.mark.parametrize(
    ("call", "search_gives", "added", "step"),
    [
        pytest.param(PENALTIES, HIT, HIT, ToolStep.SEARCH, id="hits over the bar are added"),
        pytest.param(
            PENALTIES, (junk_result(),), (), ToolStep.SEARCH, id="hits below the bar are not"
        ),
        pytest.param(
            ToolCall(name="check_in_force"),
            HIT,
            (),
            ToolStep.UNKNOWN,
            id="a tool the surface lacks adds nothing and records as unknown",
        ),
        pytest.param(
            ToolCall(name="search", args={"limit": 5}),
            HIT,
            (),
            ToolStep.SEARCH,
            id="arguments off the tool's schema add nothing",
        ),
        pytest.param(
            ToolCall(name="follow_reference", args={"celex": "32023R1805"}),
            HIT,
            (),
            ToolStep.FOLLOW_REFERENCE,
            id="an act followed without a division adds nothing",
        ),
        pytest.param(
            PENALTIES,
            LLMError("embedding call failed"),
            (),
            ToolStep.SEARCH,
            id="a search the provider fails adds nothing",
        ),
        pytest.param(
            PENALTIES,
            SQLAlchemyError("connection lost"),
            (),
            ToolStep.SEARCH,
            id="a search the database fails adds nothing",
        ),
    ],
)
async def test_a_call_adds_its_hits_and_a_bad_one_adds_nothing_without_raising(
    monkeypatch, call, search_gives, added, step
):
    async def fake_search(session, request):
        if isinstance(search_gives, Exception):
            raise search_gives
        return search_gives

    monkeypatch.setattr("app.chat.toolbox.tools.search.search", fake_search)

    assert await run_tool_call(call) == added
    assert build_call_step(call).step is step


def test_arguments_left_out_are_not_described():
    call = ToolCall(name="search", args={"query": "scope", "celex": None})
    assert describe_call(call) == "scope"
