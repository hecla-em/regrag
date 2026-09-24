"""decompose: the split it makes, the model it is bound to, and its best-effort failure."""

import json
from typing import Any

import litellm
import pytest
from langchain_core.messages import AIMessage

from app.chat.blocks import corpus_chunks
from app.chat.enums import ChatNode
from app.chat.graph.nodes.decompose import DecomposedQuestion, decompose
from app.chat.graph.nodes.decompose import logger as decompose_logger
from app.chat.models import ChatState
from tests.chat.conftest import (
    QUESTION,
    hits_for,
    model_answering,
    run_graph,
    split_message,
    warnings_from,
)
from tests.conftest import search_result

pytestmark = pytest.mark.anyio


def litellm_completion(monkeypatch, content: str, usage: dict[str, int]) -> list[dict[str, Any]]:
    """Stand litellm's completion call in for one blocking answer, returning the calls made."""
    calls: list[dict[str, Any]] = []

    async def fake_acompletion(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
            "usage": usage,
        }

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    return calls


async def test_the_decompose_client_sends_the_output_format_and_the_node_records_usage(
    monkeypatch,
):
    """The format is bound on the client and must reach litellm as response_format; the
    blocking answer carries usage on the message, which becomes the step's tokens."""
    calls = litellm_completion(
        monkeypatch,
        json.dumps({"queries": ["what is A", "what is B"]}),
        usage={"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140},
    )

    update = await decompose(ChatState(question="What are A and B?"))

    assert calls[0]["response_format"] is DecomposedQuestion
    assert calls[0]["stream"] is False
    assert update["queries"] == ("what is A", "what is B")
    [step] = update["steps"]
    assert step.usage is not None
    assert (step.usage.input_tokens, step.usage.output_tokens) == (120, 20)


class TestDecomposeInTheGraph:
    async def test_on_a_split_question_searches_each_part_then_answers_the_whole(
        self, decompose_on, answer_model, decompose_turns, monkeypatch
    ):
        decompose_turns(split_message("what is A", "what is B"))
        requests = hits_for(
            monkeypatch,
            **{"what is A": (search_result(id=1),), "what is B": (search_result(id=2),)},
        )

        state = ChatState(question="What are A and B?")
        state = await run_graph(state)

        assert [r.step for r in state.steps] == [
            ChatNode.DECOMPOSE,
            ChatNode.RETRIEVE,
            ChatNode.SYNTHESIZE,
        ]
        assert state.queries == ("what is A", "what is B")
        assert {r.query for r in requests} == {"what is A", "what is B"}
        assert tuple(chunk.id for chunk in corpus_chunks(state.sources)) == (1, 2)
        [messages] = answer_model.received
        assert messages[1].content.endswith("Question: What are A and B?")


@pytest.mark.parametrize(
    ("turn", "warned"),
    [
        pytest.param(
            split_message("What is the GHG intensity limit, rephrased?"),
            False,
            id="one part back is an echo, so the question asked one thing",
        ),
        pytest.param(
            AIMessage(content="I'd split this into two."), True, id="an answer off the schema"
        ),
        pytest.param(None, True, id="a call that keeps failing"),
    ],
)
async def test_without_a_split_the_question_is_searched_as_asked(monkeypatch, caplog, turn, warned):
    """The split is best-effort: losing it costs the split, never the request."""
    model = model_answering(turn)
    monkeypatch.setattr("app.chat.graph.nodes.decompose.decompose_model", lambda: model)

    update = await decompose(ChatState(question=QUESTION))

    assert update["queries"] == ()
    assert bool(warnings_from(caplog, decompose_logger)) is warned
