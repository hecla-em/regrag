"""Chat run state: what a graph snapshot copies over, and what it leaves alone."""

from app.chat.enums import ChatNode, RefusalReason, ToolStep
from app.chat.models import ChatState, ChatStepResult, ChatTurn, Refusal
from app.chat.toolbox.models import ToolCall
from app.core.config import config
from tests.conftest import reply_message, search_result


def test_log_fields_leave_the_thread_content_out():
    state = ChatState(
        question="q",
        history=(ChatTurn(question="What is FuelEU?", answer="A regulation."),),
        standalone_question="What penalties does FuelEU impose?",
    )

    fields = state.log_fields()

    assert "history" not in fields
    assert "standalone_question" not in fields
    assert fields["thread_id"] == str(state.thread_id)


def test_log_fields_count_hits_sources_and_queries_rather_than_dumping_them():
    state = ChatState(
        question="q",
        queries=("first part", "second part"),
        hits=(search_result(), search_result(id=2)),
        sources=(search_result(),),
    )

    fields = state.log_fields()

    assert (fields["hits"], fields["sources"], fields["queries"]) == (2, 1, 2)
    assert "question" not in fields
    assert "first part" not in str(fields)


def visited(*steps: ChatNode | ToolStep) -> tuple[ChatStepResult, ...]:
    return tuple(ChatStepResult(step=step, ms=1) for step in steps)


class TestContextSettled:
    def test_not_settled_before_any_node(self):
        assert ChatState(question="q").context_settled is False

    def test_after_retrieve_with_loop_enabled_the_loop_still_runs(self, monkeypatch):
        monkeypatch.setattr(config, "ASSESS_ENABLED", True)
        state = ChatState(
            question="q", steps=visited(ChatNode.RETRIEVE), sources=(search_result(),)
        )
        assert state.context_settled is False

    def test_after_retrieve_with_loop_disabled_context_is_settled(self, monkeypatch):
        monkeypatch.setattr(config, "ASSESS_ENABLED", False)
        state = ChatState(
            question="q", steps=visited(ChatNode.RETRIEVE), sources=(search_result(),)
        )
        assert state.context_settled is True

    def test_after_a_gated_retrieve_context_is_settled_for_the_refusal(self, monkeypatch):
        monkeypatch.setattr(config, "ASSESS_ENABLED", True)
        state = ChatState(question="q", steps=visited(ChatNode.RETRIEVE), sources=())
        assert state.context_settled is True

    def test_assess_asking_for_tools_is_not_settled(self):
        state = ChatState(
            question="q",
            steps=visited(ChatNode.RETRIEVE, ChatNode.ASSESS),
            sources=(search_result(),),
            pending_calls=(ToolCall(name="search", args={"query": "penalties"}),),
        )
        assert state.context_settled is False

    def test_assess_asking_for_nothing_is_settled(self):
        state = ChatState(
            question="q",
            steps=visited(ChatNode.RETRIEVE, ChatNode.ASSESS),
            sources=(search_result(),),
        )
        assert state.context_settled is True

    def test_tool_step_below_the_round_cap_is_not_settled(self, monkeypatch):
        monkeypatch.setattr(config, "ASSESS_MAX_ROUNDS", 2)
        state = ChatState(
            question="q",
            steps=visited(ChatNode.RETRIEVE, ChatNode.ASSESS, ToolStep.SEARCH),
            sources=(search_result(),),
        )
        assert state.context_settled is False

    def test_tool_step_consuming_the_round_cap_is_settled(self, monkeypatch):
        monkeypatch.setattr(config, "ASSESS_MAX_ROUNDS", 1)
        state = ChatState(
            question="q",
            steps=visited(ChatNode.RETRIEVE, ChatNode.ASSESS, ToolStep.SEARCH),
            sources=(search_result(),),
        )
        assert state.context_settled is True

    def test_a_refuse_step_is_settled_whatever_the_budget(self, monkeypatch):
        """Nothing bearing on the question is final: the refusal follows, and the sources
        it was read against go out first."""
        monkeypatch.setattr(config, "ASSESS_MAX_ROUNDS", 3)
        state = ChatState(
            question="q",
            steps=visited(ChatNode.RETRIEVE, ChatNode.ASSESS, ToolStep.REFUSE),
            sources=(search_result(),),
            refusal=Refusal(
                reason=RefusalReason.INSUFFICIENT_CONTEXT,
                explanation="no block concerns the question",
            ),
        )
        assert state.context_settled is True


def test_usage_without_a_model_is_unmeasured_not_priced_at_a_guess():
    state = ChatState(
        question="q",
        steps=(ChatStepResult.from_reply(ChatNode.SYNTHESIZE, 1, reply_message(model=None)),),
    )
    usage = state.usage()
    assert usage is not None
    assert usage.cost_usd is None
