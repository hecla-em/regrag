"""assess ⇄ assess_tools: what the round asks for, what it merges, and when it refuses."""

import pytest
from langchain_core.messages import AIMessage

from app.chat.blocks import corpus_chunks
from app.chat.enums import ChatNode, RefusalReason, ToolStep
from app.chat.graph.nodes.assess import (
    ASSESS_SYSTEM_PROMPT,
    build_assess_message,
    merge_sources,
)
from app.chat.graph.nodes.refuse import REFUSAL_ANSWER
from app.chat.models import Refusal
from app.chat.toolbox.models import ToolCall
from app.core.config import config
from app.ingestion.chunk.models import Reference
from tests.chat.conftest import (
    QUESTION,
    FailingModel,
    run_graph,
    tool_call_message,
    tool_calls_message,
)
from tests.conftest import USAGE, search_result

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_tool_session")]


@pytest.mark.parametrize(
    ("existing", "additions", "cap", "merged"),
    [
        pytest.param((1,), (2, 3), 10, (1, 2, 3), id="new chunks follow in arrival order"),
        pytest.param((1,), (1, 2), 10, (1, 2), id="a chunk already there is kept as it was"),
        pytest.param((1, 2), (3, 4), 3, (1, 2, 3), id="nothing is appended past the cap"),
        pytest.param((1, 2), (3,), 1, (1, 2), id="a context over the cap is kept whole"),
    ],
)
def test_a_tool_round_grows_the_context_without_touching_what_was_there(
    existing, additions, cap, merged
):
    context = tuple(search_result(id=n, text="as first read") for n in existing)
    fetched = [search_result(id=n, text="as refetched") for n in additions]

    grown = merge_sources(context, fetched, cap=cap)

    assert tuple(chunk.id for chunk in corpus_chunks(grown)) == merged
    assert grown[: len(context)] == context


class TestAssessLoop:
    async def test_a_tool_round_merges_its_chunks_then_answers(
        self, loop_on, one_result, answer_model, assess_turns, tool_results
    ):
        assess = assess_turns(
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
        assert state.assess_rounds() == 2
        assert run_calls == [
            ToolCall(name="follow_reference", args={"celex": "32023R1805", "article": "6"})
        ]
        assert tuple(chunk.id for chunk in corpus_chunks(state.sources)) == (1, 42)
        assert state.pending_calls == ()
        first, second = assess.received
        assert str(first[0].content).startswith(ASSESS_SYSTEM_PROMPT)
        assert "[1] (Regulation (EU) 2023/1805, Article 4(1))" in first[1].content
        assert "[2] (" not in first[1].content
        assert "[2] (Regulation (EU) 2023/1805, Article 6)" in second[1].content
        assert str(second[1].content).endswith(f"Question: {QUESTION}")

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
        assert tuple(chunk.id for chunk in corpus_chunks(state.sources)) == (1, 2, 3)

    async def test_a_follow_of_a_block_already_shown_is_dropped_before_the_cap(
        self, loop_on, one_result, answer_model, assess_turns, tool_results, monkeypatch
    ):
        """It would fetch nothing new, so the one call the round may run goes to what is
        missing, and the call past the cap never runs."""
        monkeypatch.setattr(config, "ASSESS_MAX_CALLS", 1)
        shown = {"celex": "32023R1805", "article": "4", "paragraph": "1"}
        assess_turns(
            tool_calls_message(
                ("follow_reference", shown), ("search", {"query": "a"}), ("search", {"query": "b"})
            ),
            AIMessage(content=""),
        )
        run_calls = tool_results()

        await run_graph()

        assert run_calls == [ToolCall(name="search", args={"query": "a"})]


class TestRefuseTool:
    """Assess may answer that nothing in the context bears on the question and no fetch would
    change that: that call alone runs as a tool step and routes to the fixed refusal, with
    no answer written."""

    REFUSED = {"explanation": "no block concerns airline luggage"}

    async def test_the_call_alone_ends_in_the_fixed_refusal_keeping_the_context_it_read(
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
        assert tuple(chunk.id for chunk in corpus_chunks(state.sources)) == (1,)
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
            tool_calls_message(("refuse", self.REFUSED), ("search", {"query": "a"})),
            AIMessage(content=""),
        )
        run_calls = tool_results(search_result(id=2))

        state = await run_graph()

        assert run_calls == [ToolCall(name="search", args={"query": "a"})]
        assert state.answer == "Answered [1]."
        assert state.refusal is None
        assert ChatNode.REFUSE not in {r.step for r in state.steps}


MRV = "32015R0757"


@pytest.mark.parametrize(
    ("references", "cites"),
    [
        pytest.param(
            (Reference(raw="Article 6(2)", article="6", paragraph="2"),),
            ["cites: 32023R1805 Article 6(2)"],
            id="a reference within the act is addressed to the citing act",
        ),
        pytest.param(
            (Reference(raw="Article 3 of Regulation X", instrument=MRV, article="3"),),
            ["cites: 32015R0757 Article 3"],
            id="a reference across acts names the cited act",
        ),
        pytest.param(
            tuple(
                Reference(raw=f"point ({point})", instrument=MRV, article="3", point=point)
                for point in "cen"
            ),
            [
                "cites: 32015R0757 Article 3, point (c), 32015R0757 Article 3, point (e), "
                "32015R0757 Article 3, point (n)"
            ],
            id="each borrowed point is its own address",
        ),
        pytest.param(
            (
                Reference(raw="Article 6 of Regulation (EU) 2015/757", instrument=MRV, article="6"),
                Reference(raw="Article 6 of Regulation No 2015/757", instrument=MRV, article="6"),
            ),
            ["cites: 32015R0757 Article 6"],
            id="two phrasings of one address are named once",
        ),
        pytest.param(
            (Reference(raw="Regulation (EU) 2015/757", instrument=MRV),),
            [],
            id="a reference naming no division is skipped",
        ),
    ],
)
def test_a_block_lists_each_followable_address_it_cites(references, cites):
    message = build_assess_message("q", (search_result(references=references),))

    assert [line for line in message.splitlines() if line.startswith("cites:")] == cites
