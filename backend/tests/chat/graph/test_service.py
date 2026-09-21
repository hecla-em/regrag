"""Chat graph: the compiled shape, and the routing that ends a run in an answer or the
fixed refusal."""

import pytest

from app.chat.enums import RefusalReason
from app.chat.graph.nodes.refuse import REFUSAL_ANSWER
from app.chat.models import ChatState, Refusal
from app.core.config import config
from app.retrieval.models import SearchRequest
from tests.chat.conftest import QUESTION, fake_chat_model, run_graph
from tests.conftest import install_chat_model, install_search, junk_result, search_result

pytestmark = pytest.mark.anyio


async def test_graph_retrieves_then_answers(one_result, monkeypatch):
    model = fake_chat_model("Yes, Article 4 [1].")
    install_chat_model(monkeypatch, model)

    state = await run_graph()

    assert state.answer == "Yes, Article 4 [1]."
    assert state.sources == (search_result(),)
    assert one_result == [SearchRequest(query=QUESTION, limit=config.CHAT_SOURCES)]


# The refusal gate


async def test_a_question_the_corpus_does_not_cover_is_refused_before_any_model_call(
    one_junk_result, answer_model
):
    state = await run_graph(ChatState(question="What is the best pizza topping?"))

    assert state.answer == REFUSAL_ANSWER
    assert state.sources == ()
    assert state.refusal == Refusal(reason=RefusalReason.NOTHING_RETRIEVED)
    assert answer_model.received == []
    assert len(one_junk_result) == 1


async def test_a_refused_question_still_keeps_what_search_found(one_junk_result, answer_model):
    """The hits the gate judged stay on the state, so a refusal can be told from a miss:
    what search found, and how it scored, is what an eval reads a too-tight gate from."""
    state = await run_graph(ChatState(question="What is the best pizza topping?"))

    assert state.hits == (junk_result(),)
    assert state.sources == ()


async def test_an_empty_search_is_refused_before_any_model_call(answer_model, monkeypatch):
    async def nothing(session, request):
        return ()

    install_search(monkeypatch, nothing)

    state = await run_graph()

    assert state.answer == REFUSAL_ANSWER
    assert answer_model.received == []
