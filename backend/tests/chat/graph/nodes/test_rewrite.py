"""rewrite: the follow-up it restates, what reads the restatement, and its failure path."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableBinding
from langchain_litellm import ChatLiteLLM

from app.chat.enums import ChatNode
from app.chat.graph.nodes.assess import build_assess_system_prompt
from app.chat.graph.nodes.rewrite import (
    REWRITE_SYSTEM_PROMPT,
    StandaloneQuestion,
    rewrite,
    rewrite_model,
)
from app.chat.graph.nodes.synthesize import SYSTEM_PROMPT
from app.chat.models import ChatState, ChatTurn
from app.chat.prompts import THREAD_NOTE, system_prompt
from app.core.config import config
from app.retrieval.models import SearchRequest
from tests.chat.conftest import (
    FailingModel,
    hits_for,
    restated_message,
    run_graph,
    split_message,
)
from tests.conftest import REPORTED_USAGE, search_result

pytestmark = pytest.mark.anyio

FOLLOW_UP = "What penalties does it impose?"
RESTATED = "What penalties does FuelEU Maritime impose?"
HISTORY = (ChatTurn(question="What is FuelEU Maritime?", answer="A regulation on fuel."),)


def test_rewrite_binds_the_output_format_on_a_blocking_call():
    """The restatement is asked for in the StandaloneQuestion shape, on the one model every
    node of the graph calls."""
    binding = rewrite_model()
    assert isinstance(binding, RunnableBinding)
    model = binding.bound
    assert isinstance(model, ChatLiteLLM)
    assert model.streaming is False
    assert binding.kwargs["response_format"] is StandaloneQuestion


class TestRewriteInTheGraph:
    async def test_a_first_question_runs_no_rewrite_step_and_sends_the_prompts_as_before(
        self, one_result, answer_model
    ):
        state = await run_graph()

        assert [r.step for r in state.steps] == [ChatNode.RETRIEVE, ChatNode.SYNTHESIZE]
        assert state.standalone_question == ""
        [messages] = answer_model.received
        assert [type(m) for m in messages] == [SystemMessage, HumanMessage]
        assert messages[0].content == SYSTEM_PROMPT

    async def test_a_follow_up_is_restated_searched_and_answered_with_the_thread_in_view(
        self, answer_model, rewrite_turns, monkeypatch
    ):
        rewrite = rewrite_turns(restated_message(RESTATED))
        requests = hits_for(monkeypatch, **{RESTATED: (search_result(),)})

        state = ChatState(question=FOLLOW_UP, history=HISTORY)
        state = await run_graph(state)

        assert [r.step for r in state.steps] == [
            ChatNode.REWRITE,
            ChatNode.RETRIEVE,
            ChatNode.SYNTHESIZE,
        ]
        assert state.standalone_question == RESTATED
        assert [r.query for r in requests] == [RESTATED]
        [rewrite_prompt] = rewrite.received
        assert rewrite_prompt[0].content == REWRITE_SYSTEM_PROMPT
        assert "What is FuelEU Maritime?" in rewrite_prompt[1].content
        assert rewrite_prompt[1].content.endswith(f"Latest question: {FOLLOW_UP}")
        [messages] = answer_model.received
        assert [type(m) for m in messages] == [SystemMessage, HumanMessage, AIMessage, HumanMessage]
        assert messages[0].content == SYSTEM_PROMPT + THREAD_NOTE
        assert messages[1].content == "What is FuelEU Maritime?"
        assert messages[2].content == "A regulation on fuel."
        assert messages[3].content.endswith(f"Question: {FOLLOW_UP}")

    async def test_the_rewrite_step_records_its_usage(self, rewrite_turns):
        rewrite_turns(restated_message(RESTATED))

        update = await rewrite(ChatState(question=FOLLOW_UP, history=HISTORY))

        assert update["standalone_question"] == RESTATED
        [step] = update["steps"]
        assert (step.step, step.usage) == (ChatNode.REWRITE, REPORTED_USAGE)

    async def test_an_answer_off_the_schema_searches_the_question_as_asked(
        self, rewrite_turns, caplog
    ):
        rewrite_turns(AIMessage(content="It refers to FuelEU."))

        update = await rewrite(ChatState(question=FOLLOW_UP, history=HISTORY))

        assert update["standalone_question"] == ""
        assert "rewrite answered off its schema" in caplog.text

    async def test_a_failing_call_searches_the_question_as_asked(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "app.chat.graph.nodes.rewrite.rewrite_model",
            lambda: FailingModel(messages=iter([]), failures=9),
        )

        update = await rewrite(ChatState(question=FOLLOW_UP, history=HISTORY))

        assert update["standalone_question"] == ""
        assert "rewrite call failed" in caplog.text

    async def test_with_decompose_on_the_restated_question_is_what_gets_split(
        self, decompose_on, one_result, answer_model, rewrite_turns, decompose_turns
    ):
        rewrite_turns(restated_message(RESTATED))
        decompose = decompose_turns(split_message(RESTATED))

        state = ChatState(question=FOLLOW_UP, history=HISTORY)
        state = await run_graph(state)

        assert [r.step for r in state.steps][:3] == [
            ChatNode.REWRITE,
            ChatNode.DECOMPOSE,
            ChatNode.RETRIEVE,
        ]
        [prompt] = decompose.received
        assert prompt[1].content == RESTATED
        assert one_result == [SearchRequest(query=RESTATED, limit=config.CHAT_SOURCES)]

    async def test_assess_sees_the_thread_before_the_context(
        self, loop_on, one_result, answer_model, rewrite_turns, assess_turns
    ):
        rewrite_turns(restated_message(RESTATED))
        assess = assess_turns(AIMessage(content=""))

        state = ChatState(question=FOLLOW_UP, history=HISTORY)
        state = await run_graph(state)

        [messages] = assess.received
        assert [type(m) for m in messages] == [SystemMessage, HumanMessage, AIMessage, HumanMessage]
        base = build_assess_system_prompt(may_refuse=config.ASSESS_MAY_REFUSE)
        assert messages[0].content == base + THREAD_NOTE
        assert messages[3].content.endswith(f"Question: {FOLLOW_UP}")

    def test_a_first_question_sends_the_base_prompt_and_a_follow_up_adds_the_thread_note(self):
        assert system_prompt(SYSTEM_PROMPT, ()) == SYSTEM_PROMPT
        assert system_prompt(SYSTEM_PROMPT, HISTORY) == SYSTEM_PROMPT + THREAD_NOTE
