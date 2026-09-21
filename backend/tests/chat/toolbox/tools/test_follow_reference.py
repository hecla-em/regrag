"""follow_reference: the division it addresses, and the cap one call is held to."""

import pytest

from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.service import run_tool_call
from app.retrieval.models import ReferenceTarget
from tests.conftest import search_result

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_tool_session")]


async def test_follow_reference_call_dispatches_to_the_named_division(monkeypatch):
    targets: list[ReferenceTarget] = []

    async def fake_follow(session, target):
        targets.append(target)
        return (search_result(id=7),)

    monkeypatch.setattr("app.chat.toolbox.tools.follow_reference.follow_reference", fake_follow)
    call = ToolCall(name="follow_reference", args={"celex": "32023R1805", "article": "6"})

    found = await run_tool_call(call)

    assert found == (search_result(id=7),)
    assert targets == [ReferenceTarget(celex="32023R1805", article="6")]


async def test_an_act_without_a_division_returns_nothing():
    call = ToolCall(name="follow_reference", args={"celex": "32023R1805"})
    assert await run_tool_call(call) == ()
