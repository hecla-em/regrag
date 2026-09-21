"""retrieve: what each query brings back, how the hits interleave, and section widening."""

import pytest

from app.chat.graph.nodes.retrieve import interleave_by_rank, retrieve
from app.chat.models import ChatState
from app.core.config import config
from tests.chat.conftest import hits_for
from tests.conftest import junk_result, search_result

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("per_query", "merged"),
    [
        pytest.param(
            [(1, 2), (3, 4)], (1, 3, 2, 4), id="every first hit comes before any second hit"
        ),
        pytest.param(
            [(1, 2), (2, 3)],
            (1, 2, 3),
            id="a chunk two queries found is kept at its earliest place",
        ),
        pytest.param(
            [(1,), (2, 3, 4)], (1, 2, 3, 4), id="a shorter list runs out without ending the longer"
        ),
        pytest.param([(1, 2)], (1, 2), id="one list comes back as it was"),
    ],
)
def test_hits_interleave_by_rank(per_query, merged):
    found = [tuple(search_result(id=n) for n in ids) for ids in per_query]

    assert tuple(chunk.id for chunk in interleave_by_rank(found)) == merged


@pytest.mark.parametrize(
    ("a", "b", "hits", "sources"),
    [
        pytest.param(
            (search_result(id=1), search_result(id=2)),
            (search_result(id=3),),
            (1, 3, 2),
            (1, 3, 2),
            id="every part over the bar is admitted, interleaved",
        ),
        pytest.param(
            (search_result(id=1),),
            (junk_result(id=9),),
            (1, 9),
            (1,),
            id="a part below the bar keeps its hits but admits no sources",
        ),
        pytest.param(
            (junk_result(id=8),),
            (junk_result(id=9),),
            (8, 9),
            (),
            id="no part over the bar leaves the context empty",
        ),
    ],
)
async def test_each_query_is_searched_and_gated_on_its_own(monkeypatch, a, b, hits, sources):
    requests = hits_for(monkeypatch, a=a, b=b)

    update = await retrieve(ChatState(question="A and B?", queries=("a", "b")))

    assert {r.query for r in requests} == {"a", "b"}
    assert all(r.limit == config.CHAT_SOURCES for r in requests)
    assert tuple(chunk.id for chunk in update["hits"]) == hits
    assert tuple(chunk.id for chunk in update["sources"]) == sources
    assert update["retrieved_sources"] == len(sources)


async def test_expansion_widens_the_interleaved_survivors(monkeypatch):
    hits_for(monkeypatch, a=(search_result(id=1),), b=(search_result(id=2),))
    widened: list[tuple[int, ...]] = []

    async def fake_expand(session, chunks, *, limit):
        widened.append(tuple(chunk.id for chunk in chunks))
        return (*chunks, search_result(id=3))

    monkeypatch.setattr(config, "EXPAND_SECTIONS", True)
    monkeypatch.setattr("app.chat.graph.nodes.retrieve.expand_sections", fake_expand)

    update = await retrieve(ChatState(question="A and B?", queries=("a", "b")))

    assert widened == [(1, 2)]
    assert tuple(chunk.id for chunk in update["sources"]) == (1, 2, 3)
