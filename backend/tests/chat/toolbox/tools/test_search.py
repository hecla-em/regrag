"""search: the request it builds, the bar its hits face, and the failures it swallows."""

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.service import run_tool_call
from app.core.config import config
from app.core.llm.errors import LLMError
from app.retrieval.models import SearchFilters, SearchRequest
from tests.conftest import junk_result, search_result

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_tool_session")]


async def test_search_call_dispatches_with_filters_and_the_assess_limit(monkeypatch):
    requests: list[SearchRequest] = []

    async def fake_search(session, request):
        requests.append(request)
        return (search_result(),)

    monkeypatch.setattr("app.chat.toolbox.tools.search.search", fake_search)
    call = ToolCall(name="search", args={"query": "penalties", "celex": "32023R1805"})

    found = await run_tool_call(call)

    assert found == (search_result(),)
    assert requests == [
        SearchRequest(
            query="penalties",
            filters=SearchFilters(celex="32023R1805"),
            limit=config.ASSESS_SEARCH_LIMIT,
        )
    ]


async def test_a_search_call_that_raises_llmerror_returns_nothing(monkeypatch):
    async def failing_search(session, request):
        raise LLMError("embedding call failed")

    monkeypatch.setattr("app.chat.toolbox.tools.search.search", failing_search)
    call = ToolCall(name="search", args={"query": "penalties"})

    assert await run_tool_call(call) == ()


async def test_a_search_call_that_raises_a_database_error_returns_nothing(monkeypatch):
    async def failing_search(session, request):
        raise SQLAlchemyError("connection lost")

    monkeypatch.setattr("app.chat.toolbox.tools.search.search", failing_search)
    call = ToolCall(name="search", args={"query": "penalties"})

    assert await run_tool_call(call) == ()


async def test_hits_below_the_retrieval_bar_are_not_added_to_the_context(monkeypatch):
    """The gate refuses to answer from junk; the loop may not smuggle the same junk in."""

    async def junk_search(session, request):
        return (junk_result(),)

    monkeypatch.setattr("app.chat.toolbox.tools.search.search", junk_search)
    call = ToolCall(name="search", args={"query": "best pizza topping"})

    assert await run_tool_call(call) == ()
