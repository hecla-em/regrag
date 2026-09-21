"""refuse: the explanation it asks for, that it fetches nothing, and the step it leaves."""

import pytest

from app.chat.enums import RefusalReason
from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.tools.refuse import refusal_from

pytestmark = pytest.mark.anyio


def test_a_refuse_call_carries_its_explanation_as_the_refusal():
    refusal = refusal_from(ToolCall(name="refuse", args={"explanation": "nothing bears on it"}))

    assert refusal is not None
    assert (refusal.reason, refusal.explanation) == (
        RefusalReason.INSUFFICIENT_CONTEXT,
        "nothing bears on it",
    )


def test_a_refuse_call_without_an_explanation_is_recorded_as_empty():
    refusal = refusal_from(ToolCall(name="refuse", args={}))

    assert refusal is not None
    assert refusal.explanation == ""


def test_a_fetch_carries_no_refusal():
    assert refusal_from(ToolCall(name="search", args={"query": "refuse"})) is None
