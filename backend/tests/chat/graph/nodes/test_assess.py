"""assess ⇄ assess_tools: what the round asks for, what it merges, and when it refuses."""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableBinding
from langchain_litellm import ChatLiteLLM

from app.chat.enums import ChatNode, RefusalReason, ToolStep
from app.chat.graph.nodes.assess import (
    ASSESS_SYSTEM_PROMPT,
    assess_model,
    build_assess_message,
    build_assess_system_prompt,
    merge_sources,
)
from app.chat.graph.nodes.refuse import REFUSAL_ANSWER
from app.chat.models import Refusal
from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.service import tool_definitions
from app.core.config import config
from app.ingestion.chunk.models import Reference
from tests.chat.conftest import (
    QUESTION,
    FailingModel,
    run_graph,
    tool_call_message,
)
from tests.conftest import TOKEN_USAGE, USAGE, install_search, search_result

pytestmark = pytest.mark.anyio


def test_assess_binds_its_tools_on_a_blocking_call():
    """The loop reads the context in one blocking turn and answers with tool calls, so the
    stream that suits the answer would leave it nothing to run."""
    binding = assess_model()
    assert isinstance(binding, RunnableBinding)
    model = binding.bound
    assert isinstance(model, ChatLiteLLM)
    assert model.streaming is False


class TestMergeSources:
    def test_appends_new_chunks_after_existing_in_arrival_order(self):
        existing = (search_result(id=1),)
        additions = [search_result(id=2), search_result(id=3)]

        merged = merge_sources(existing, additions, cap=10)

        assert tuple(chunk.id for chunk in merged) == (1, 2, 3)

    def test_deduplicates_by_chunk_id_keeping_the_earlier_chunk(self):
        existing = (search_result(id=1, text="first form"),)
        additions = [search_result(id=1, text="refetched form"), search_result(id=2)]

        merged = merge_sources(existing, additions, cap=10)

        assert tuple(chunk.id for chunk in merged) == (1, 2)
        assert merged[0].text == "first form"

    def test_stops_appending_at_the_cap_so_earlier_context_wins(self):
        existing = (search_result(id=1), search_result(id=2))
        additions = [search_result(id=3), search_result(id=4)]

        merged = merge_sources(existing, additions, cap=3)

        assert tuple(chunk.id for chunk in merged) == (1, 2, 3)

    def test_existing_beyond_the_cap_is_kept_but_nothing_is_added(self):
        existing = (search_result(id=1), search_result(id=2))

        merged = merge_sources(existing, [search_result(id=3)], cap=2)

        assert tuple(chunk.id for chunk in merged) == (1, 2)


class TestAssessLoop:
    async def test_no_tool_calls_goes_straight_to_synthesize(
        self, loop_on, one_result, answer_model, assess_turns
    ):
        assess_turns(AIMessage(content=""))

        state = await run_graph()

        assert state.answer == "Answered [1]."
        assert [r.step for r in state.steps] == [
            ChatNode.RETRIEVE,
            ChatNode.ASSESS,
            ChatNode.SYNTHESIZE,
        ]

    async def test_a_tool_round_merges_its_chunks_then_answers(
        self, loop_on, one_result, answer_model, assess_turns, tool_results
    ):
        assess_turns(
            tool_call_message("follow_reference", {"celex": "32023R1805", "article": "6"}),
            AIMessage(content=""),
        )
        run_calls = tool_results(search_result(id=42, citation="Article 6"))

        state = await run_graph()

        assert [r.step for r in state.steps] == [
            ChatNode.RETRIEVE,
            ChatNode.ASSESS,
            ToolStep.FOLLOW_REFERENCE,
            ChatNode.ASSESS,
            ChatNode.SYNTHESIZE,
        ]
        assert run_calls == [
            ToolCall(name="follow_reference", args={"celex": "32023R1805", "article": "6"})
        ]
        assert tuple(chunk.id for chunk in state.sources) == (1, 42)
        assert state.pending_calls == ()

    async def test_the_round_cap_forces_synthesis_with_calls_still_pending(
        self, loop_on, one_result, answer_model, assess_turns, tool_results, monkeypatch
    ):
        monkeypatch.setattr(config, "ASSESS_MAX_ROUNDS", 1)
        assess_turns(
            tool_call_message("search", {"query": "first gap"}),
            tool_call_message("search", {"query": "never runs"}),
        )
        tool_results(search_result(id=2))

        state = await run_graph()

        assert [r.step for r in state.steps] == [
            ChatNode.RETRIEVE,
            ChatNode.ASSESS,
            ToolStep.SEARCH,
            ChatNode.SYNTHESIZE,
        ]

    async def test_a_call_to_a_tool_the_surface_does_not_have_is_still_a_step(
        self, loop_on, one_result, answer_model, assess_turns, tool_results
    ):
        """A model asking for a tool that does not exist is worth reading off the path,
        and the round it spent still shows there."""
        assess_turns(tool_call_message("summarize", {"query": "gap"}), AIMessage(content=""))
        tool_results()

        state = await run_graph()

        assert [r.step for r in state.steps] == [
            ChatNode.RETRIEVE,
            ChatNode.ASSESS,
            ToolStep.UNKNOWN,
            ChatNode.ASSESS,
            ChatNode.SYNTHESIZE,
        ]
        assert state.answer == "Answered [1]."

    async def test_each_tool_call_of_a_round_is_timed_as_its_own_step(
        self, loop_on, one_result, answer_model, assess_turns, tool_results
    ):
        """Two calls in one round leave two steps, so a slow round names the call that
        was slow rather than reporting the pair as one number."""
        assess_turns(
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search", "args": {"query": "a"}, "id": "c1", "type": "tool_call"},
                    {
                        "name": "follow_reference",
                        "args": {"celex": "32023R1805", "article": "6"},
                        "id": "c2",
                        "type": "tool_call",
                    },
                ],
            ),
            AIMessage(content=""),
        )
        tool_results(search_result(id=7))

        state = await run_graph()

        assert [r.step for r in state.steps] == [
            ChatNode.RETRIEVE,
            ChatNode.ASSESS,
            ToolStep.SEARCH,
            ToolStep.FOLLOW_REFERENCE,
            ChatNode.ASSESS,
            ChatNode.SYNTHESIZE,
        ]
        assert state.assess_rounds() == 2

    async def test_each_assess_visit_records_its_own_usage(
        self, loop_on, one_result, answer_model, assess_turns, tool_results
    ):
        assess_turns(tool_call_message("search", {"query": "gap"}), AIMessage(content=""))
        tool_results()

        state = await run_graph()

        assesses = [r for r in state.steps if r.step is ChatNode.ASSESS]
        assert len(assesses) == 2
        assert all(r.usage == TOKEN_USAGE for r in assesses)

    async def test_assess_sees_the_question_and_numbered_context(
        self, loop_on, one_result, answer_model, assess_turns
    ):
        assess = assess_turns(AIMessage(content=""))

        await run_graph()

        (prompt,) = assess.received
        assert str(prompt[0].content).startswith(ASSESS_SYSTEM_PROMPT)
        assert "[1] (Regulation (EU) 2023/1805" in prompt[1].content
        assert str(prompt[1].content).endswith(f"Question: {QUESTION}")

    async def test_a_gated_question_still_refuses_without_any_model_call(
        self, loop_on, monkeypatch
    ):
        async def empty_search(session, request):
            return ()

        install_search(monkeypatch, empty_search)

        state = await run_graph()

        assert state.answer == REFUSAL_ANSWER
        assert [r.step for r in state.steps] == [ChatNode.RETRIEVE, ChatNode.REFUSE]

    async def test_a_persistently_failing_assess_call_still_synthesizes_from_the_context(
        self, loop_on, one_result, answer_model, monkeypatch
    ):
        """An assess round is best-effort: it must never destroy a request that already
        has answerable context, even when the model keeps failing."""
        assess = FailingModel(messages=iter([]), failures=10, usage=USAGE)
        monkeypatch.setattr("app.chat.graph.nodes.assess.assess_model", lambda: assess)

        state = await run_graph()

        assert state.answer == "Answered [1]."
        assert [r.step for r in state.steps] == [
            ChatNode.RETRIEVE,
            ChatNode.ASSESS,
            ChatNode.SYNTHESIZE,
        ]

    async def test_an_assess_turn_asking_for_more_than_the_cap_runs_only_the_cap(
        self, loop_on, one_result, answer_model, assess_turns, tool_results, monkeypatch
    ):
        monkeypatch.setattr(config, "ASSESS_MAX_CALLS", 1)
        assess_turns(
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search", "args": {"query": "a"}, "id": "call_1", "type": "tool_call"},
                    {"name": "search", "args": {"query": "b"}, "id": "call_2", "type": "tool_call"},
                ],
            ),
            AIMessage(content=""),
        )
        run_calls = tool_results()

        await run_graph()

        assert run_calls == [ToolCall(name="search", args={"query": "a"})]

    async def test_growth_is_budgeted_from_the_context_retrieve_left(
        self, loop_on, one_result, answer_model, assess_turns, tool_results, monkeypatch
    ):
        """The budget is what the loop may add, not a ceiling the initial context is assumed
        to already fill: retrieve left one chunk, so two more is all two rounds may append."""
        monkeypatch.setattr(config, "ASSESS_EXTRA_CHUNKS", 2)
        monkeypatch.setattr(config, "CHAT_CONTEXT_CHUNKS", 15)
        assess_turns(
            tool_call_message("search", {"query": "gap"}),
            tool_call_message("search", {"query": "more"}),
        )
        tool_results(search_result(id=2), search_result(id=3), search_result(id=4))

        state = await run_graph()

        assert state.retrieved_sources == 1
        assert tuple(chunk.id for chunk in state.sources) == (1, 2, 3)

    async def test_a_zero_budget_reads_the_context_without_growing_it(
        self, loop_on, one_result, answer_model, assess_turns, tool_results, monkeypatch
    ):
        monkeypatch.setattr(config, "ASSESS_EXTRA_CHUNKS", 0)
        assess_turns(tool_call_message("search", {"query": "gap"}), AIMessage(content=""))
        tool_results(search_result(id=2))

        state = await run_graph()

        assert tuple(chunk.id for chunk in state.sources) == (1,)


class TestFollowsOfBlocksAlreadyShown:
    """A follow_reference of a paragraph the context already shows in full fetches nothing
    new, so it is dropped before the cap is counted, leaving the budget for what is missing."""

    SHOWN_ARGS = {"celex": "32023R1805", "article": "4", "paragraph": "1"}

    async def test_a_follow_of_a_block_already_shown_is_dropped_before_the_cap(
        self, loop_on, one_result, answer_model, assess_turns, tool_results, monkeypatch
    ):
        monkeypatch.setattr(config, "ASSESS_MAX_CALLS", 1)
        assess_turns(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "follow_reference",
                        "args": self.SHOWN_ARGS,
                        "id": "c1",
                        "type": "tool_call",
                    },
                    {"name": "search", "args": {"query": "a"}, "id": "c2", "type": "tool_call"},
                ],
            ),
            AIMessage(content=""),
        )
        run_calls = tool_results()

        await run_graph()

        assert run_calls == [ToolCall(name="search", args={"query": "a"})]

    async def test_a_follow_of_a_point_under_a_paragraph_already_shown_is_dropped(
        self, loop_on, one_result, answer_model, assess_turns, tool_results
    ):
        """A point sits inside the paragraph's text, so a paragraph shown in full shows it."""
        by_point = {**self.SHOWN_ARGS, "point": "a"}
        assess_turns(tool_call_message("follow_reference", by_point), AIMessage(content=""))
        run_calls = tool_results()

        await run_graph()

        assert run_calls == []

    async def test_a_follow_of_a_point_a_shown_part_lists_is_dropped(
        self, loop_on, answer_model, assess_turns, tool_results, monkeypatch
    ):
        """A definitions article numbers no paragraphs, so the part listing the point is
        the whole of what the follow would return."""

        async def fake_search(session, request):
            return (
                search_result(
                    celex="32015R0757",
                    citation="Article 3",
                    article="3",
                    paragraph=None,
                    points=("c", "d"),
                ),
            )

        install_search(monkeypatch, fake_search)
        by_point = {"celex": "32015R0757", "article": "3", "point": "c"}
        assess_turns(tool_call_message("follow_reference", by_point), AIMessage(content=""))
        run_calls = tool_results()

        await run_graph()

        assert run_calls == []

    async def test_a_follow_of_a_point_no_shown_part_lists_still_runs(
        self, loop_on, answer_model, assess_turns, tool_results, monkeypatch
    ):
        async def fake_search(session, request):
            return (
                search_result(
                    celex="32015R0757",
                    citation="Article 3",
                    article="3",
                    paragraph=None,
                    points=("a",),
                ),
            )

        install_search(monkeypatch, fake_search)
        by_point = {"celex": "32015R0757", "article": "3", "point": "c"}
        assess_turns(tool_call_message("follow_reference", by_point), AIMessage(content=""))
        run_calls = tool_results()

        await run_graph()

        assert run_calls == [ToolCall(name="follow_reference", args=by_point)]

    async def test_a_follow_of_a_paragraph_shown_only_in_part_still_runs(
        self, loop_on, answer_model, assess_turns, tool_results, monkeypatch
    ):
        async def fake_search(session, request):
            return (search_result(part=1, parts=2),)

        install_search(monkeypatch, fake_search)
        assess_turns(tool_call_message("follow_reference", self.SHOWN_ARGS), AIMessage(content=""))
        run_calls = tool_results()

        await run_graph()

        assert run_calls == [ToolCall(name="follow_reference", args=self.SHOWN_ARGS)]

    async def test_a_follow_of_a_whole_article_still_runs_when_only_its_chapeau_is_shown(
        self, loop_on, answer_model, assess_turns, tool_results, monkeypatch
    ):
        """The chapeau's parts say nothing about the paragraphs under it, so only a
        paragraph can be known to be shown in full."""

        async def fake_search(session, request):
            return (search_result(citation="Article 4", article="4"),)

        install_search(monkeypatch, fake_search)
        whole = {"celex": "32023R1805", "article": "4"}
        assess_turns(tool_call_message("follow_reference", whole), AIMessage(content=""))
        run_calls = tool_results()

        await run_graph()

        assert run_calls == [ToolCall(name="follow_reference", args=whole)]


class TestRefuseTool:
    """Assess may answer that nothing in the context bears on the question and no fetch would
    change that: that call alone runs as a tool step and routes to the fixed refusal, with
    no answer written."""

    REFUSED = {"explanation": "no block concerns airline luggage"}

    async def test_the_call_alone_ends_in_the_fixed_refusal_without_an_answer_call(
        self, loop_on, one_result, answer_model, assess_turns
    ):
        assess_turns(tool_call_message("refuse", self.REFUSED))

        state = await run_graph()

        assert state.answer == REFUSAL_ANSWER
        assert answer_model.received == []
        assert [r.step for r in state.steps] == [
            ChatNode.RETRIEVE,
            ChatNode.ASSESS,
            ToolStep.REFUSE,
            ChatNode.REFUSE,
        ]

    async def test_the_refusal_keeps_the_context_it_was_read_against_and_the_explanation(
        self, loop_on, one_result, answer_model, assess_turns
    ):
        assess_turns(tool_call_message("refuse", self.REFUSED))

        state = await run_graph()

        assert tuple(chunk.id for chunk in state.sources) == (1,)
        assert state.refusal == Refusal(
            reason=RefusalReason.INSUFFICIENT_CONTEXT,
            explanation="no block concerns airline luggage",
        )
        assert state.steps[2].subject == "no block concerns airline luggage"

    async def test_the_call_beside_a_fetch_is_dropped_and_the_fetch_runs(
        self, loop_on, one_result, answer_model, assess_turns, tool_results
    ):
        """A hedged turn is read as a fetch: the bias is toward answering."""
        assess_turns(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "refuse",
                        "args": self.REFUSED,
                        "id": "call_1",
                        "type": "tool_call",
                    },
                    {"name": "search", "args": {"query": "a"}, "id": "call_2", "type": "tool_call"},
                ],
            ),
            AIMessage(content=""),
        )
        run_calls = tool_results(search_result(id=2))

        state = await run_graph()

        assert run_calls == [ToolCall(name="search", args={"query": "a"})]
        assert state.answer == "Answered [1]."
        assert state.refusal is None
        assert ChatNode.REFUSE not in {r.step for r in state.steps}

    async def test_the_call_without_an_explanation_still_refuses(
        self, loop_on, one_result, answer_model, assess_turns
    ):
        assess_turns(tool_call_message("refuse", {}))

        state = await run_graph()

        assert state.answer == REFUSAL_ANSWER
        assert state.refusal == Refusal(reason=RefusalReason.INSUFFICIENT_CONTEXT)

    async def test_the_refusal_still_comes_with_rounds_left_in_the_budget(
        self, loop_on, one_result, answer_model, assess_turns, monkeypatch
    ):
        """Nothing bearing on the question is final: a second round would only read the
        same context again."""
        monkeypatch.setattr(config, "ASSESS_MAX_ROUNDS", 3)
        assess_turns(tool_call_message("refuse", self.REFUSED))

        state = await run_graph()

        assert state.answer == REFUSAL_ANSWER
        assert state.assess_rounds() == 1

    def test_assess_binds_the_surface_as_the_toolbox_offers_it(self, monkeypatch):
        """Which tools that is, switch on or off, the toolbox says and its tests hold."""
        monkeypatch.setattr(config, "ASSESS_MAY_REFUSE", False)

        binding = assess_model()

        assert isinstance(binding, RunnableBinding)
        assert binding.kwargs["tools"] == tool_definitions()

    async def test_the_prompt_tells_assess_when_to_call_it_while_the_switch_is_on(
        self, loop_on, one_result, answer_model, assess_turns, monkeypatch
    ):
        monkeypatch.setattr(config, "ASSESS_MAY_REFUSE", True)
        assess = assess_turns(AIMessage(content=""))

        await run_graph()

        (prompt,) = assess.received
        assert prompt[0].content == build_assess_system_prompt(may_refuse=True)
        assert "call refuse" in prompt[0].content

    async def test_the_prompt_says_nothing_of_it_while_the_switch_is_off(
        self, loop_on, one_result, answer_model, assess_turns, monkeypatch
    ):
        monkeypatch.setattr(config, "ASSESS_MAY_REFUSE", False)
        assess = assess_turns(AIMessage(content=""))

        await run_graph()

        (prompt,) = assess.received
        assert prompt[0].content == ASSESS_SYSTEM_PROMPT
        assert "call refuse" not in prompt[0].content


class TestBuildAssessMessage:
    def test_carries_numbered_blocks_and_the_question(self):
        sources = (search_result(text="A very specific clause."),)

        message = build_assess_message("What is the limit?", sources)

        assert "[1] (Regulation (EU) 2023/1805, Article 4(1))" in message
        assert "A very specific clause." in message
        assert message.endswith("Question: What is the limit?")

    def test_lists_a_blocks_followable_references_with_their_addresses(self):
        reference = Reference(raw="Article 6(2)", article="6", paragraph="2")
        sources = (search_result(references=(reference,)),)

        message = build_assess_message("q", sources)

        assert "cites: 32023R1805 Article 6(2)" in message

    def test_names_the_cited_act_when_the_reference_crosses_acts(self):
        reference = Reference(raw="Article 3 of Regulation X", instrument="32015R0757", article="3")
        sources = (search_result(references=(reference,)),)

        message = build_assess_message("q", sources)

        assert "cites: 32015R0757 Article 3" in message

    def test_names_each_borrowed_point_as_its_own_address(self):
        """Three terms borrowed from one definitions article are three places to fetch."""
        references = tuple(
            Reference(
                raw=f"Article 3, point ({point}), of Regulation X",
                instrument="32015R0757",
                article="3",
                point=point,
            )
            for point in "cen"
        )
        sources = (search_result(references=references),)

        message = build_assess_message("q", sources)

        assert (
            "cites: 32015R0757 Article 3, point (c), 32015R0757 Article 3, point (e), "
            "32015R0757 Article 3, point (n)"
        ) in message

    def test_names_an_address_once_however_it_is_phrased(self):
        """Two phrasings of one target are two references but one place to fetch."""
        references = (
            Reference(
                raw="Article 6 of Regulation (EU) 2015/757", instrument="32015R0757", article="6"
            ),
            Reference(
                raw="Article 6 of Regulation (EU) No 2015/757", instrument="32015R0757", article="6"
            ),
        )
        sources = (search_result(references=references),)

        message = build_assess_message("q", sources)

        assert message.count("32015R0757 Article 6") == 1

    def test_skips_references_that_name_no_division(self):
        reference = Reference(raw="Regulation (EU) 2015/757", instrument="32015R0757")
        sources = (search_result(references=(reference,)),)

        message = build_assess_message("q", sources)

        assert "cites:" not in message


class TestBuildAssessSystemPrompt:
    def test_with_refusal_allowed_the_prompt_adds_when_to_call_refuse(self):
        prompt = build_assess_system_prompt(may_refuse=True)
        assert prompt.startswith(ASSESS_SYSTEM_PROMPT)
        assert "call refuse" in prompt[len(ASSESS_SYSTEM_PROMPT) :]

    def test_without_it_the_prompt_is_the_bare_one(self):
        assert build_assess_system_prompt(may_refuse=False) == ASSESS_SYSTEM_PROMPT
