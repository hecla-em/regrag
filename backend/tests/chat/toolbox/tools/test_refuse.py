"""refuse: the refusal a call carries, and the calls that carry none."""

import pytest

from app.chat.enums import RefusalReason
from app.chat.models import Refusal
from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.tools.refuse import refusal_from

NO_CONTEXT = RefusalReason.INSUFFICIENT_CONTEXT


@pytest.mark.parametrize(
    ("call", "refusal"),
    [
        pytest.param(
            ToolCall(name="refuse", args={"explanation": "nothing bears on it"}),
            Refusal(reason=NO_CONTEXT, explanation="nothing bears on it"),
            id="a refuse call carries its explanation",
        ),
        pytest.param(
            ToolCall(name="refuse", args={}),
            Refusal(reason=NO_CONTEXT, explanation=""),
            id="an explanation left off is recorded as empty",
        ),
        pytest.param(
            ToolCall(name="search", args={"query": "refuse"}), None, id="a fetch carries no refusal"
        ),
    ],
)
def test_only_a_refuse_call_carries_a_refusal(call, refusal):
    assert refusal_from(call) == refusal
