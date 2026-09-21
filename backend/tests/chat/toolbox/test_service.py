"""The tool surface: what the model is shown, how a call is dispatched, and the step
one records."""

import pytest

from app.chat.enums import ToolStep
from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.service import build_call_step, describe_call, run_tool_call

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_tool_session")]


async def test_an_unknown_tool_name_returns_nothing():
    assert await run_tool_call(ToolCall(name="check_in_force", args={})) == ()


async def test_invalid_arguments_return_nothing():
    call = ToolCall(name="search", args={"limit": 5})
    assert await run_tool_call(call) == ()


class TestDescribeCall:
    def test_every_argument_given_is_described_in_order(self):
        call = ToolCall(name="follow_reference", args={"celex": "32023R1805", "article": "2"})
        assert describe_call(call) == "32023R1805 · 2"

    def test_arguments_left_out_are_not_described(self):
        call = ToolCall(name="search", args={"query": "scope", "celex": None})
        assert describe_call(call) == "scope"


class TestBuildCallStep:
    def test_a_tool_the_surface_lacks_is_recorded_as_unknown(self):
        assert build_call_step(ToolCall(name="teleport")).step is ToolStep.UNKNOWN
