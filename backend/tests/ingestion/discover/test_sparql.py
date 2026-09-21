"""The CELLAR query, and the rows it answers with."""

import httpx
import pytest

from app.ingestion.discover.sparql import run_acts_by_topic_query
from app.ingestion.exceptions import MalformedDiscoveryError
from tests.conftest import act_row, binding, payload

pytestmark = pytest.mark.anyio


def answering(response: httpx.Response) -> httpx.AsyncClient:
    """A client whose every query gets the one response."""
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response))


async def test_a_binding_is_read_into_a_row_with_whatever_cellar_left_unbound_as_none():
    """SPARQL omits an OPTIONAL it could not bind, flags arrive as '1' and '0', and titles
    are set with non-breaking spaces."""
    answer = payload(
        binding("32003L0087"),
        binding(
            "32023R2599",
            force="1",
            cons="02023R2599-20240101",
            title="Regulation (EU) 2023/2599 of 22\xa0November 2023",
            basis="A03gfP4",
        ),
        binding("32016R1927", force="0"),
    )

    async with answering(httpx.Response(200, json=answer)) as client:
        rows = await run_acts_by_topic_query(client, "32003L0087")

    assert rows == [
        act_row("32003L0087"),
        act_row(
            "32023R2599",
            in_force=True,
            consolidation="02023R2599-20240101",
            title="Regulation (EU) 2023/2599 of 22 November 2023",
            basis_article="A03gfP4",
        ),
        act_row("32016R1927", in_force=False),
    ]


async def test_an_answer_without_the_base_act_is_malformed():
    """The query's second UNION branch matches the base act itself, so it always comes back."""

    def handler(request):
        return httpx.Response(200, json=payload(binding("32023R2449", force="1")))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MalformedDiscoveryError, match="32015R0757"):
            await run_acts_by_topic_query(client, "32015R0757")


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(
            httpx.Response(200, json={"error": "service unavailable"}),
            id="json that is not a result set",
        ),
        pytest.param(
            httpx.Response(200, text="<html>gateway timeout</html>"), id="a body that is not json"
        ),
    ],
)
async def test_a_body_cellar_answers_200_with_but_no_rows_in_is_malformed(
    response: httpx.Response,
) -> None:
    async with answering(response) as client:
        with pytest.raises(MalformedDiscoveryError):
            await run_acts_by_topic_query(client, "32015R0757")
