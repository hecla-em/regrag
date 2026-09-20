"""The CELLAR query, and the rows it answers with."""

import httpx
import pytest

from app.ingestion.discover.sparql import run_acts_by_topic_query, run_cited_acts_query
from app.ingestion.exceptions import MalformedDiscoveryError
from tests.conftest import act_row, binding, payload

pytestmark = pytest.mark.anyio


async def test_the_query_asks_for_the_base_act_and_json_results():
    def handler(request):
        query = request.url.params["query"]
        assert "resource/celex/32023R1805" in query
        assert "resource_legal_based_on_resource_legal" in query
        assert "expression_title" in query
        assert "resource/authority/language/ENG" in query
        assert request.url.params["format"] == "application/sparql-results+json"
        return httpx.Response(200, json=payload(binding("32023R1805", force="1")))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await run_acts_by_topic_query(client, "32023R1805")

    assert rows == [act_row("32023R1805", in_force=True)]


async def test_unbound_variables_come_back_as_none():
    """SPARQL omits an OPTIONAL it could not bind, rather than sending it null."""

    def handler(request):
        return httpx.Response(200, json=payload(binding("32023R1805")))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await run_acts_by_topic_query(client, "32023R1805")

    assert rows == [act_row("32023R1805", in_force=None, consolidation=None)]


async def test_an_answer_without_the_base_act_is_malformed():
    """The query's second UNION branch matches the base act itself, so it always comes back."""

    def handler(request):
        return httpx.Response(200, json=payload(binding("32023R2449", force="1")))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MalformedDiscoveryError, match="32015R0757"):
            await run_acts_by_topic_query(client, "32015R0757")


async def test_a_body_that_is_not_a_result_set_is_malformed():
    def handler(request):
        return httpx.Response(200, json={"error": "service unavailable"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MalformedDiscoveryError, match="malformed"):
            await run_acts_by_topic_query(client, "32015R0757")


async def test_a_body_that_is_not_json_is_malformed():
    def handler(request):
        return httpx.Response(200, text="<html>gateway timeout</html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MalformedDiscoveryError, match="malformed"):
            await run_acts_by_topic_query(client, "32015R0757")


async def test_the_in_force_flag_is_read_as_a_bool():
    def handler(request):
        return httpx.Response(
            200,
            json=payload(binding("32016R1928", force="1"), binding("32016R1927", force="0")),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await run_acts_by_topic_query(client, "32016R1928")

    assert [row.in_force for row in rows] == [True, False]


async def test_the_title_is_read_with_its_spacing_normalised():
    """CELLAR sets titles with non-breaking spaces; a stored title should read as plain text."""

    def handler(request):
        title = "Regulation (EU) 2023/1805 of 13\xa0September 2023"
        return httpx.Response(200, json=payload(binding("32023R1805", title=title)))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await run_acts_by_topic_query(client, "32023R1805")

    assert rows[0].title == "Regulation (EU) 2023/1805 of 13 September 2023"


async def test_the_legal_basis_article_is_read_from_the_row():
    def handler(request):
        rows = payload(binding("32003L0087"), binding("32023R2599", basis="A03gfP4"))
        return httpx.Response(200, json=rows)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await run_acts_by_topic_query(client, "32003L0087")

    assert [row.basis_article for row in rows] == [None, "A03gfP4"]


async def test_the_cited_query_asks_for_every_celex_and_no_legal_basis():
    def handler(request):
        query = request.url.params["query"]
        assert "resource/celex/32018L2001" in query
        assert "resource/celex/32008R0765" in query
        assert "resource_legal_based_on_resource_legal" not in query
        assert "expression_title" in query
        return httpx.Response(200, json=payload(binding("32018L2001", force="1")))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await run_cited_acts_query(client, ["32018L2001", "32008R0765"])

    assert rows == [act_row("32018L2001", in_force=True)]


async def test_a_cited_celex_cellar_does_not_know_simply_does_not_come_back():
    """Unlike a base act, a cited celex may be a misparsed citation; its absence is not an error."""

    def handler(request):
        return httpx.Response(200, json=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await run_cited_acts_query(client, ["32018L2001"]) == []
