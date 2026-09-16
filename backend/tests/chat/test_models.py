"""Chat run state: what a graph snapshot copies over, and what it leaves alone."""

from app.chat.enums import ChatNode, RefusalReason, ToolStep
from app.chat.models import ChatState, ChatStepResult, ChatTurn, Refusal
from app.chat.toolbox.models import ToolCall
from app.core.config import config
from app.core.exceptions import DomainError
from tests.conftest import TOKEN_USAGE, USAGE, search_result


def test_sync_from_snapshot_folds_the_snapshot_on_and_leaves_the_consumer_fields_alone():
    """A values snapshot carries only the graph's channels; total_ms and error, set by the
    stream's consumer, must survive it."""
    state = ChatState(question="q", total_ms=5, error="boom")
    retrieved = ChatStepResult(step=ChatNode.RETRIEVE, ms=12)

    state.sync_from_snapshot({"question": "q", "steps": (retrieved,), "sources": (), "answer": ""})

    assert state.steps == (retrieved,)
    assert (state.total_ms, state.error) == (5, "boom")


def test_a_state_is_born_in_a_thread_of_its_own():
    """A first question has no thread yet: the state mints one, and two states never share it."""
    assert ChatState(question="q").thread_id != ChatState(question="q").thread_id


def test_the_retrieval_question_is_the_standalone_one_when_rewrite_wrote_it():
    state = ChatState(question="What penalties does it impose?")
    assert state.retrieval_question == "What penalties does it impose?"
    state.standalone_question = "What penalties does FuelEU Maritime impose?"
    assert state.retrieval_question == "What penalties does FuelEU Maritime impose?"


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


def test_a_domain_error_is_recorded_by_its_message():
    state = ChatState(question="q")

    state.record_error(DomainError("embedding call failed"))

    assert state.error == "embedding call failed"


def test_an_unexpected_error_is_recorded_by_its_type():
    """The message of an unexpected error is not the ledger's to keep; its type names the
    failure well enough to triage, and the same name is what the stream sends."""
    state = ChatState(question="q")

    state.record_error(RuntimeError("pool exhausted"))

    assert state.error == "RuntimeError"


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


class TestAssessRounds:
    def test_counts_assess_visits_not_the_calls_they_asked_for(self):
        """A round is one assess visit however many tools it ran, so the budget is spent
        by asking, not by fanning out."""
        state = ChatState(
            question="q",
            steps=visited(ChatNode.RETRIEVE, ChatNode.ASSESS, ToolStep.SEARCH, ToolStep.SEARCH),
        )
        assert state.assess_rounds() == 1


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


def test_cost_is_each_steps_usage_at_the_model_that_step_called():
    state = ChatState(
        question="q",
        steps=(
            ChatStepResult(step=ChatNode.RETRIEVE, ms=1),
            ChatStepResult.from_usage(ChatNode.ASSESS, 1, USAGE, config.CHAT_MODEL),
            ChatStepResult.from_usage(ChatNode.SYNTHESIZE, 1, USAGE, config.CHAT_MODEL),
        ),
    )
    one_step = TOKEN_USAGE.cost_usd(config.CHAT_MODEL)
    assert one_step is not None
    assert state.cost_usd() == 2 * one_step
    assert state.called_model() == config.CHAT_MODEL


def test_a_run_with_no_reported_usage_has_no_cost_and_named_no_model():
    state = ChatState(question="q", steps=(ChatStepResult(step=ChatNode.RETRIEVE, ms=1),))
    assert state.cost_usd() is None
    assert state.called_model() is None


def test_usage_without_a_model_is_unmeasured_not_priced_at_a_guess():
    state = ChatState(
        question="q", steps=(ChatStepResult.from_usage(ChatNode.SYNTHESIZE, 1, USAGE),)
    )
    assert state.cost_usd() is None
