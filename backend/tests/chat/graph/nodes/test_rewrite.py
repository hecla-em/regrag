"""rewrite: the follow-up it restates, what reads the restatement, and its failure path."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.chat.enums import ChatNode
from app.chat.graph.nodes.assess import build_assess_system_prompt
from app.chat.graph.nodes.rewrite import REWRITE_SYSTEM_PROMPT, rewrite
from app.chat.graph.nodes.rewrite import logger as rewrite_logger
from app.chat.graph.nodes.synthesize import SYSTEM_PROMPT
from app.chat.models import ChatState, ChatTurn
from app.chat.prompts import THREAD_NOTE
from app.core.config import config
from app.retrieval.models import SearchRequest
from tests.chat.conftest import (
    hits_for,
    model_answering,
    restated_message,
    run_graph,
    split_message,
    warnings_from,
)
from tests.conftest import search_result

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_tool_session")]

FOLLOW_UP = "What penalties does it impose?"
RESTATED = "What penalties does FuelEU Maritime impose?"
HISTORY = (ChatTurn(question="What is FuelEU Maritime?", answer="A regulation on fuel."),)


async def test_a_follow_up_is_restated_searched_and_answered_with_the_thread_in_view(
    decompose_on, loop_on, answer_model, rewrite_turns, decompose_turns, assess_turns, monkeypatch
):
    """Every optional node on: the restated question is what gets split and searched, while
    assess and the answer read the question as asked, behind the thread."""
    rewrite = rewrite_turns(restated_message(RESTATED))
    decompose = decompose_turns(split_message(RESTATED))
    assess = assess_turns(AIMessage(content=""))
    requests = hits_for(monkeypatch, **{RESTATED: (search_result(),)})

    state = await run_graph(ChatState(question=FOLLOW_UP, history=HISTORY))

    assert [r.step for r in state.steps] == [
        ChatNode.REWRITE,
        ChatNode.DECOMPOSE,
        ChatNode.RETRIEVE,
        ChatNode.ASSESS,
        ChatNode.SYNTHESIZE,
    ]
    assert state.standalone_question == RESTATED

    [rewrite_prompt] = rewrite.received
    assert rewrite_prompt[0].content == REWRITE_SYSTEM_PROMPT
    assert "What is FuelEU Maritime?" in rewrite_prompt[1].content
    assert rewrite_prompt[1].content.endswith(f"Latest question: {FOLLOW_UP}")

    [decompose_prompt] = decompose.received
    assert decompose_prompt[1].content == RESTATED
    assert requests == [SearchRequest(query=RESTATED, limit=config.CHAT_SOURCES)]

    [assess_prompt] = assess.received
    [answer_prompt] = answer_model.received
    assess_base = build_assess_system_prompt(may_refuse=config.ASSESS_MAY_REFUSE)
    for messages, base in ((assess_prompt, assess_base), (answer_prompt, SYSTEM_PROMPT)):
        assert [type(m) for m in messages] == [SystemMessage, HumanMessage, AIMessage, HumanMessage]
        assert messages[0].content == base + THREAD_NOTE
        assert messages[1].content == "What is FuelEU Maritime?"
        assert messages[2].content == "A regulation on fuel."
        assert messages[3].content.endswith(f"Question: {FOLLOW_UP}")


@pytest.mark.parametrize(
    "turn",
    [
        pytest.param(AIMessage(content="It refers to FuelEU."), id="an answer off the schema"),
        pytest.param(None, id="a call that keeps failing"),
    ],
)
async def test_without_a_restatement_the_question_is_searched_as_asked(monkeypatch, caplog, turn):
    """The restatement is best-effort: losing it costs the restatement, never the request."""
    model = model_answering(turn)
    monkeypatch.setattr("app.chat.graph.nodes.rewrite.rewrite_model", lambda: model)

    update = await rewrite(ChatState(question=FOLLOW_UP, history=HISTORY))

    assert update["standalone_question"] == ""
    assert warnings_from(caplog, rewrite_logger)
