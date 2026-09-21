"""decompose: the split it makes, the model it is bound to, and its best-effort failure."""

import json
from typing import Any

import litellm
import pytest
from langchain_core.messages import AIMessage

from app.chat.enums import ChatNode
from app.chat.graph.nodes.decompose import (
    DecomposedQuestion,
    decompose,
)
from app.chat.models import ChatState
from tests.chat.conftest import (
    QUESTION,
    FailingModel,
    hits_for,
    run_graph,
    split_message,
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
        assert tuple(chunk.id for chunk in state.sources) == (1, 2)
        [messages] = answer_model.received
        assert messages[1].content.endswith("Question: What are A and B?")


class TestDecompose:
    async def test_a_single_part_question_leaves_queries_empty(self, decompose_turns):
        """One query back means the question asked one thing; the original text is what
        retrieve searches, so a lightly rephrased echo cannot change retrieval."""
        decompose_turns(split_message("What is the GHG intensity limit, rephrased?"))

        update = await decompose(ChatState(question=QUESTION))

        assert update["queries"] == ()

    async def test_an_answer_off_the_schema_falls_back_to_the_question(
        self, decompose_turns, caplog
    ):
        decompose_turns(AIMessage(content="I'd split this into two."))

        update = await decompose(ChatState(question=QUESTION))

        assert update["queries"] == ()
        assert "decompose answered off its schema" in caplog.text

    async def test_a_failing_call_falls_back_to_the_question(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "app.chat.graph.nodes.decompose.decompose_model",
            lambda: FailingModel(messages=iter([]), failures=9),
        )

        update = await decompose(ChatState(question=QUESTION))

        assert update["queries"] == ()
        assert "decompose call failed" in caplog.text
